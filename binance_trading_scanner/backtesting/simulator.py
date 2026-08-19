"""Shared candle-by-candle simulation core.

This is the SINGLE implementation of trade mechanics (entry at next open, fee/
slippage, intrabar exits, partial TP1->TP2, structure invalidation, force-close).
Both the backtester and the paper trader drive it, so they can never diverge —
"no dos motores con resultados diferentes".

The caller supplies the signal for each candle (computed via
``SignalEngine.evaluate_at``), so signals remain the single source of truth and
this module never re-decides them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core.enums import ExitReason, SignalType, StructureClass
from core.models import Signal

from .execution import ExitEvent, buy_fill_price, fee_on, leg_pnl, resolve_candle, sell_fill_price
from .portfolio import EquityPoint, Portfolio, day_key_of, position_size
from .trade import Leg, Position, Trade


@dataclass
class StepResult:
    """What happened on one candle (used by callers to journal orders/fills)."""

    opened: Optional[Position] = None
    entry_blocked_reason: Optional[str] = None
    closed_trades: List[Trade] = field(default_factory=list)
    exit_legs: List[Leg] = field(default_factory=list)
    scheduled_signal_time: Optional[int] = None
    equity_point: Optional[EquityPoint] = None


class Simulator:
    """Stateful per-candle simulator over a Portfolio. Direction-aware (LONG/SHORT)."""

    def __init__(self, cfg, portfolio: Portfolio, symbol: str, timeframe_value: str) -> None:
        self.cfg = cfg
        self.portfolio = portfolio
        self.symbol = symbol
        self.tf = timeframe_value
        self.exec = cfg.execution
        self.pending: Optional[dict] = None
        self.position: Optional[Position] = None
        self.trade_id = 0
        self._last_reason: Optional[str] = None

    # -- main step ----------------------------------------------------------

    def process_candle(self, o: float, h: float, l: float, c: float,
                       open_time: int, close_time: int, sig: Signal,
                       bar_index: int) -> StepResult:
        res = StepResult()
        day = day_key_of(close_time)

        # 1. Fill a pending entry at THIS candle's open (the "next candle").
        if self.pending is not None:
            pos = self._open(o, int(open_time), bar_index, day)
            if pos is not None:
                self.position = pos
                res.opened = pos
            else:
                res.entry_blocked_reason = self._last_reason
            self.pending = None

        # 2. Manage the open position on this candle (price exits first).
        if self.position is not None and self.position.is_open:
            self.position.update_excursion(h, l)
            for ev in resolve_candle(self.position, o, h, l, c, self.exec):
                if not self.position.is_open:
                    break
                res.exit_legs.append(self._apply_exit(ev, close_time, day))
            if not self.position.is_open:
                res.closed_trades.append(self._build_trade(bar_index))
                self.position = None

        # 3. Structure invalidation exit (uses the engine's own output). A LONG is
        #    invalidated by a bearish structure; a SHORT by a bullish one.
        if (self.position is not None and self.position.is_open
                and self.cfg.exit_on_structure_break):
            adverse = (StructureClass.BULLISH_STRUCTURE if self.position.is_short
                       else StructureClass.BEARISH_STRUCTURE)
            if sig.structure_class is adverse:
                ev = ExitEvent(self.position.remaining_fraction, c, ExitReason.INVALIDATION)
                res.exit_legs.append(self._apply_exit(ev, close_time, day))
                if not self.position.is_open:
                    res.closed_trades.append(self._build_trade(bar_index))
                    self.position = None

        # 4. Schedule an entry for the NEXT candle if flat and directional. The
        #    signal is unchanged; ``allowed_directions`` only filters execution
        #    (used by LONG-only / SHORT-only validation runs).
        allowed = getattr(self.cfg, "allowed_directions", frozenset({"LONG", "SHORT"}))
        if (self.position is None and self.pending is None
                and sig.direction.is_directional and sig.direction.value in allowed
                and sig.entry and sig.stop and len(sig.take_profits) >= 1):
            tps = sig.take_profits
            self.pending = {
                "signal_time": int(close_time), "stop": float(sig.stop),
                "tp1": float(tps[0]), "tp2": float(tps[1] if len(tps) > 1 else tps[0]),
                "direction": sig.direction.value,
            }
            res.scheduled_signal_time = int(close_time)

        # 5. Record equity at this candle close.
        res.equity_point = self.portfolio.record_equity(close_time, c)
        return res

    def force_close(self, last_close: float, last_close_time: int, bar_index: int) -> Optional[Trade]:
        """Close any residual position at the last close (END_OF_TEST)."""
        if self.position is not None and self.position.is_open:
            ev = ExitEvent(self.position.remaining_fraction, last_close, ExitReason.END_OF_TEST)
            self._apply_exit(ev, last_close_time, day_key_of(last_close_time))
            trade = self._build_trade(bar_index)
            self.position = None
            self.portfolio.record_equity(last_close_time, last_close)
            return trade
        return None

    # -- internals ----------------------------------------------------------

    def _open(self, open_price: float, entry_time: int, bar_index: int, day: str) -> Optional[Position]:
        cfg, exec_cfg, portfolio = self.cfg, self.exec, self.portfolio
        direction = self.pending.get("direction", "LONG")
        is_short = direction == "SHORT"
        entry_raw = float(open_price)
        # LONG entry BUYS (slippage up); SHORT entry SELLS (slippage down).
        entry_eff = sell_fill_price(entry_raw, exec_cfg) if is_short else buy_fill_price(entry_raw, exec_cfg)
        equity = portfolio.equity(entry_raw)
        sizing = position_size(
            capital=equity, risk_pct=cfg.risk_per_trade, entry=entry_eff, stop=self.pending["stop"],
            side=direction, filters=cfg.filters,
            max_exposure_value=cfg.limits.max_total_exposure * equity,
            available_cash=portfolio.cash,
        )
        if not sizing.ok:
            self._last_reason = f"sizing: {sizing.reason}"
            return None
        notional = sizing.qty * entry_eff
        ok, reason = portfolio.can_open(notional, entry_raw, day)
        if not ok:
            portfolio.risk_blocked += 1
            self._last_reason = f"risk: {reason}"
            return None
        entry_fee = fee_on(sizing.qty * entry_eff, exec_cfg)
        entry_slip = sizing.qty * entry_raw * exec_cfg.slippage_rate
        pos = Position(
            symbol=self.symbol, timeframe=self.tf, signal_time=int(self.pending["signal_time"]),
            entry_time=int(entry_time), entry_raw=entry_raw, entry_eff=entry_eff,
            stop=self.pending["stop"], tp1=self.pending["tp1"], tp2=self.pending["tp2"],
            original_qty=sizing.qty, remaining_qty=sizing.qty,
            tp1_alloc=exec_cfg.tp1_alloc, tp2_alloc=exec_cfg.tp2_alloc,
            direction=direction,
            entry_fee=entry_fee, entry_slippage=entry_slip,
            fees_paid=entry_fee, slippage_paid=entry_slip,
        )
        pos.entry_bar_index = bar_index  # type: ignore[attr-defined]
        portfolio.open_position(pos)
        return pos

    def _apply_exit(self, ev: ExitEvent, close_time: int, day: str) -> Leg:
        pos, exec_cfg, portfolio = self.position, self.exec, self.portfolio
        qty, exit_eff, gross, exit_fee, exit_slip, leg_net = leg_pnl(pos, ev, exec_cfg)
        qty = min(qty, pos.remaining_qty)
        leg = Leg(timestamp=int(close_time), qty=qty, price=exit_eff, reason=ev.reason,
                  gross_pnl=gross, fees=exit_fee, slippage=exit_slip, net_pnl=leg_net)
        pos.legs.append(leg)
        pos.fees_paid += exit_fee
        pos.slippage_paid += exit_slip
        if ev.reason is ExitReason.TP1:
            pos.tp1_done = True
        portfolio.apply_exit_leg(pos, qty, exit_eff, exit_fee, exit_slip, leg_net, day)
        return leg

    def _build_trade(self, exit_bar_index: int) -> Trade:
        pos = self.position
        gross_total = sum(leg.gross_pnl for leg in pos.legs)
        fees_total = pos.entry_fee + sum(leg.fees for leg in pos.legs)
        slippage_total = pos.entry_slippage + sum(leg.slippage for leg in pos.legs)
        net_total = gross_total - fees_total - slippage_total
        exit_qty = sum(leg.qty for leg in pos.legs) or pos.original_qty
        vwap_exit = sum(leg.qty * leg.price for leg in pos.legs) / exit_qty
        last_leg = pos.legs[-1]
        initial_risk = pos.initial_risk
        r_multiple = net_total / initial_risk if initial_risk > 0 else 0.0
        notional = pos.original_qty * pos.entry_eff
        return_pct = (net_total / notional * 100.0) if notional > 0 else 0.0
        entry_idx = getattr(pos, "entry_bar_index", exit_bar_index)
        trade = Trade(
            id=self.trade_id, symbol=pos.symbol, timeframe=pos.timeframe, direction=pos.direction,
            signal_timestamp=pos.signal_time, entry_timestamp=pos.entry_time,
            entry_price=pos.entry_eff, stop_price=pos.stop,
            tp1_price=pos.tp1, tp2_price=pos.tp2,
            exit_timestamp=last_leg.timestamp, exit_price=vwap_exit,
            quantity=pos.original_qty, fees=fees_total, slippage=slippage_total,
            gross_pnl=gross_total, net_pnl=net_total, return_pct=return_pct,
            r_multiple=r_multiple, exit_reason=last_leg.reason,
            duration_bars=max(exit_bar_index - entry_idx, 0),
            duration_ms=last_leg.timestamp - pos.entry_time,
            max_favorable_excursion=pos.mfe_r, max_adverse_excursion=pos.mae_r,
            tp1_hit=pos.tp1_done or any(leg.reason is ExitReason.TP1 for leg in pos.legs),
            legs=list(pos.legs),
        )
        self.trade_id += 1
        return trade
