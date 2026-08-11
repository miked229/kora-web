"""Event-driven, candle-by-candle backtesting engine.

For each candle (spec 2): fill any pending entry at THIS candle's open (the
entry scheduled by the previous candle's signal), manage the open position
against this candle's OHLC (stops / take-profits / invalidation), evaluate the
signal engine using only data up to this candle, optionally schedule an entry
for the NEXT candle, then record equity.

Guarantees:
  * The existing SignalEngine is the ONLY source of signals (``evaluate_at`` uses
    bars 0..i only) — signals are never recomputed or modified retrospectively.
  * Entry is at the NEXT candle open (no look-ahead); gaps are respected by
    filling at the actual open.
  * Stops / TPs come from the signal and are never changed after entry.
  * Intrabar SL/TP ambiguity is resolved by the configured policy (default
    conservative), never by picking the favourable outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from core.enums import ExitReason, SignalType, StructureClass, Timeframe
from core.logger import get_logger
from core.models import SymbolFilters
from signals import SignalEngine

from .data_split import split_in_out
from .execution import ExecutionConfig, ExitEvent, buy_fill_price, fee_on, leg_pnl, resolve_candle
from .metrics import Metrics, compute_metrics
from .portfolio import Portfolio, RiskLimits, day_key_of, position_size
from .trade import Leg, Position, Trade

logger = get_logger("backtesting.engine")

_REQUIRED_COLS = ("open", "high", "low", "close", "volume", "open_time", "close_time")


@dataclass
class BacktestConfig:
    capital: float = 10_000.0
    risk_per_trade: float = 0.01
    limits: RiskLimits = field(default_factory=RiskLimits)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    filters: Optional[SymbolFilters] = None
    exit_on_structure_break: bool = True
    min_bars: Optional[int] = None     # defaults to the signal engine's min_bars

    def __post_init__(self) -> None:
        self.limits.risk_per_trade = self.risk_per_trade


@dataclass
class DataQualityReport:
    n_bars: int
    ordered: bool
    duplicate_count: int
    gap_count: int
    gaps: List[dict]
    ohlc_valid: bool
    volume_valid: bool
    sufficient: bool
    messages: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "n_bars": self.n_bars, "ordered": self.ordered,
            "duplicate_count": self.duplicate_count, "gap_count": self.gap_count,
            "gaps": self.gaps[:20], "ohlc_valid": self.ohlc_valid,
            "volume_valid": self.volume_valid, "sufficient": self.sufficient,
            "messages": self.messages,
        }


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    label: str
    period_start: Optional[int]
    period_end: Optional[int]
    initial_capital: float
    final_equity: float
    trades: List[Trade]
    equity_curve: list
    signal_log: List[dict]
    metrics: Metrics
    data_quality: dict
    risk_blocked: int

    @property
    def net_return_pct(self) -> Optional[float]:
        return self.metrics.net_return_pct


def check_data_quality(df: pd.DataFrame, timeframe: Timeframe, min_bars: int) -> DataQualityReport:
    """Validate timestamps, duplicates, gaps, OHLC and volume. Never fills data."""
    n = len(df)
    messages: List[str] = []
    for col in _REQUIRED_COLS:
        if col not in df.columns:
            messages.append(f"missing column '{col}'")
    if any("missing column" in m for m in messages):
        return DataQualityReport(n, False, 0, 0, [], False, False, False, messages)

    ot = df["open_time"].to_numpy()
    ordered = bool(np.all(np.diff(ot) > 0)) if n > 1 else True
    if not ordered:
        messages.append("timestamps are not strictly increasing")
    diffs = np.diff(np.sort(ot)) if n > 1 else np.array([])
    duplicate_count = int(np.sum(diffs == 0))
    if duplicate_count:
        messages.append(f"{duplicate_count} duplicate timestamp(s)")

    step = timeframe.milliseconds
    gaps = []
    if n > 1:
        d = np.diff(np.sort(np.unique(ot)))
        for k, gap in enumerate(d):
            if gap != step:
                gaps.append({"after_index": int(k), "gap_ms": int(gap), "expected_ms": int(step)})
    if gaps:
        messages.append(f"{len(gaps)} gap(s) detected (not filled — reported only)")

    o, h, l, c = (df[x].to_numpy(dtype="float64") for x in ("open", "high", "low", "close"))
    ohlc_valid = bool(
        np.all(h >= np.maximum(o, c) - 1e-9) and np.all(l <= np.minimum(o, c) + 1e-9)
        and np.all(h >= l) and np.all((o > 0) & (c > 0) & (h > 0) & (l > 0))
    )
    if not ohlc_valid:
        messages.append("invalid OHLC relationships or non-positive prices")
    vol = df["volume"].to_numpy(dtype="float64")
    volume_valid = bool(np.all(np.isfinite(vol)) and np.all(vol >= 0))
    if not volume_valid:
        messages.append("invalid volume (NaN or negative)")

    sufficient = n >= min_bars
    if not sufficient:
        messages.append(f"insufficient candles: {n} < required {min_bars}")
    return DataQualityReport(n, ordered, duplicate_count, len(gaps), gaps,
                             ohlc_valid, volume_valid, sufficient, messages)


class BacktestEngine:
    """Runs one symbol/timeframe at a time (spec 23: symbols run separately)."""

    def __init__(self, signal_engine: Optional[SignalEngine] = None,
                 config: Optional[BacktestConfig] = None) -> None:
        self.signal_engine = signal_engine or SignalEngine()
        self.config = config or BacktestConfig()

    # -- public -------------------------------------------------------------

    def run(self, df: pd.DataFrame, symbol: str, timeframe: Timeframe,
            label: str = "full") -> BacktestResult:
        cfg = self.config
        min_bars = cfg.min_bars or self.signal_engine.cfg.min_bars
        quality = check_data_quality(df, timeframe, min_bars)

        # Clean deterministically: sort, drop duplicate timestamps (keep first).
        clean = df.sort_values("open_time").drop_duplicates("open_time", keep="first").reset_index(drop=True)

        portfolio = Portfolio(cfg.capital, cfg.limits)
        trades: List[Trade] = []
        signal_log: List[dict] = []

        if not quality.sufficient or len(clean) == 0:
            metrics = compute_metrics(trades, portfolio.equity_curve, cfg.capital, timeframe, cfg.capital)
            return self._result(symbol, timeframe, label, clean, cfg.capital, cfg.capital,
                                trades, portfolio, signal_log, metrics, quality)

        opens = clean["open"].to_numpy(dtype="float64")
        highs = clean["high"].to_numpy(dtype="float64")
        lows = clean["low"].to_numpy(dtype="float64")
        closes = clean["close"].to_numpy(dtype="float64")
        otimes = clean["open_time"].to_numpy()
        ctimes = clean["close_time"].to_numpy()
        n = len(clean)

        exec_cfg = cfg.execution
        pending: Optional[dict] = None
        position: Optional[Position] = None
        trade_id = 0

        for i in range(n):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            ct = int(ctimes[i])
            day = day_key_of(ct)

            # 1. Fill a pending entry at THIS candle's open (the "next candle").
            if pending is not None:
                position = self._open(portfolio, pending, symbol, timeframe.value,
                                      o, int(otimes[i]), i, day, exec_cfg, cfg)
                if position is None:
                    pending["log"]["note"] = pending.get("_reason", "not filled")
                else:
                    pending["log"]["executed"] = True
                pending = None

            # 2. Manage the open position on this candle (price exits first).
            if position is not None and position.is_open:
                position.update_excursion(h, l)
                for ev in resolve_candle(position, o, h, l, c, exec_cfg):
                    if not position.is_open:
                        break
                    self._apply_exit(portfolio, position, ev, ct, day, exec_cfg)
                if not position.is_open:
                    trades.append(self._build_trade(position, trade_id, i)); trade_id += 1
                    position = None

            # 3. Evaluate the signal at this candle close (bars 0..i only).
            sig = self.signal_engine.evaluate_at(clean, i, symbol, timeframe)
            log = {
                "timestamp": ct, "direction": sig.direction.value,
                "raw_score": round(sig.raw_score, 2), "final_score": round(sig.score, 2),
                "blocked_by": list(sig.blocked_by),
                "setup": sig.setup_type.value if sig.setup_type else None,
                "executed": False, "note": None,
            }
            signal_log.append(log)

            # 3b. Structure invalidation exit (uses the engine's own output).
            if (position is not None and position.is_open and cfg.exit_on_structure_break
                    and sig.structure_class is StructureClass.BEARISH_STRUCTURE):
                ev = ExitEvent(position.remaining_fraction, c, ExitReason.INVALIDATION)
                self._apply_exit(portfolio, position, ev, ct, day, exec_cfg)
                if not position.is_open:
                    trades.append(self._build_trade(position, trade_id, i)); trade_id += 1
                    position = None

            # 4. Schedule an entry for the NEXT candle if flat and LONG.
            if (position is None and pending is None and sig.direction is SignalType.LONG
                    and sig.entry and sig.stop and len(sig.take_profits) >= 1):
                tps = sig.take_profits
                pending = {
                    "signal_time": ct, "stop": float(sig.stop),
                    "tp1": float(tps[0]), "tp2": float(tps[1] if len(tps) > 1 else tps[0]),
                    "log": log,
                }

            # 5. Record equity at this candle close.
            portfolio.record_equity(ct, c)

        # Force-close any residual position at the last close (END_OF_TEST).
        if position is not None and position.is_open:
            last_c = float(closes[-1]); ct = int(ctimes[-1])
            ev = ExitEvent(position.remaining_fraction, last_c, ExitReason.END_OF_TEST)
            self._apply_exit(portfolio, position, ev, ct, day_key_of(ct), exec_cfg)
            trades.append(self._build_trade(position, trade_id, n - 1)); trade_id += 1
            portfolio.record_equity(ct, last_c)
            position = None

        final_equity = portfolio.equity_curve[-1].equity if portfolio.equity_curve else cfg.capital
        metrics = compute_metrics(trades, portfolio.equity_curve, cfg.capital, timeframe, final_equity)
        return self._result(symbol, timeframe, label, clean, cfg.capital, final_equity,
                            trades, portfolio, signal_log, metrics, quality)

    def run_split(self, df: pd.DataFrame, symbol: str, timeframe: Timeframe,
                  train_pct: float = 0.70):
        """Return (in_sample_result, out_of_sample_result). Never mixed."""
        sp = split_in_out(df, train_pct)
        in_res = self.run(sp.train, symbol, timeframe, label="in_sample")
        out_res = self.run(sp.test, symbol, timeframe, label="out_of_sample")
        return in_res, out_res

    # -- internals ----------------------------------------------------------

    def _open(self, portfolio, plan, symbol, tf_value, open_price, entry_time,
              bar_index, day, exec_cfg, cfg) -> Optional[Position]:
        entry_raw = float(open_price)
        entry_eff = buy_fill_price(entry_raw, exec_cfg)
        equity = portfolio.equity(entry_raw)
        sizing = position_size(
            capital=equity, risk_pct=cfg.risk_per_trade, entry=entry_eff, stop=plan["stop"],
            filters=cfg.filters,
            max_exposure_value=cfg.limits.max_total_exposure * equity,
            available_cash=portfolio.cash,
        )
        if not sizing.ok:
            plan["_reason"] = f"sizing: {sizing.reason}"
            return None
        notional = sizing.qty * entry_eff
        ok, reason = portfolio.can_open(notional, entry_raw, day)
        if not ok:
            portfolio.risk_blocked += 1
            plan["_reason"] = f"risk: {reason}"
            return None
        entry_fee = fee_on(sizing.qty * entry_eff, exec_cfg)
        entry_slip = sizing.qty * entry_raw * exec_cfg.slippage_rate
        pos = Position(
            symbol=symbol, timeframe=tf_value, signal_time=int(plan["signal_time"]),
            entry_time=int(entry_time), entry_raw=entry_raw, entry_eff=entry_eff,
            stop=plan["stop"], tp1=plan["tp1"], tp2=plan["tp2"],
            original_qty=sizing.qty, remaining_qty=sizing.qty,
            tp1_alloc=exec_cfg.tp1_alloc, tp2_alloc=exec_cfg.tp2_alloc,
            entry_fee=entry_fee, entry_slippage=entry_slip,
            fees_paid=entry_fee, slippage_paid=entry_slip,
        )
        pos.entry_bar_index = bar_index  # type: ignore[attr-defined]
        portfolio.open_position(pos)
        return pos

    def _apply_exit(self, portfolio, position, ev, ct, day, exec_cfg) -> None:
        qty, exit_eff, gross, exit_fee, exit_slip, leg_net = leg_pnl(position, ev, exec_cfg)
        qty = min(qty, position.remaining_qty)
        position.legs.append(Leg(
            timestamp=ct, qty=qty, price=exit_eff, reason=ev.reason,
            gross_pnl=gross, fees=exit_fee, slippage=exit_slip, net_pnl=leg_net,
        ))
        position.fees_paid += exit_fee
        position.slippage_paid += exit_slip
        if ev.reason is ExitReason.TP1:
            position.tp1_done = True
        portfolio.apply_exit_leg(position, qty, exit_eff, exit_fee, exit_slip, leg_net, day)

    def _build_trade(self, pos: Position, trade_id: int, exit_bar_index: int) -> Trade:
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
        return Trade(
            id=trade_id, symbol=pos.symbol, timeframe=pos.timeframe, direction="LONG",
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

    def _result(self, symbol, timeframe, label, clean, capital, final_equity,
                trades, portfolio, signal_log, metrics, quality) -> BacktestResult:
        period_start = int(clean["open_time"].iloc[0]) if len(clean) else None
        period_end = int(clean["close_time"].iloc[-1]) if len(clean) else None
        return BacktestResult(
            symbol=symbol, timeframe=timeframe.value, label=label,
            period_start=period_start, period_end=period_end,
            initial_capital=capital, final_equity=final_equity,
            trades=trades, equity_curve=portfolio.equity_curve, signal_log=signal_log,
            metrics=metrics, data_quality=quality.to_dict(), risk_blocked=portfolio.risk_blocked,
        )
