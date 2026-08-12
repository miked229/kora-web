"""Testnet automation session (DISABLED by default).

Wires the full pipeline for Binance Spot **Testnet** only:

    LIVE market data (closed candle) -> SignalEngine -> Risk/Safety -> TESTNET
    order -> reconcile fill -> position -> TP1 -> TP2/STOP -> close -> PnL ->
    journal.

It reuses the exact same pieces as the rest of the system — the SignalEngine for
signals, ``resolve_candle`` for entry/exit timing, ``position_size`` for sizing,
and the ``SafeExecutor`` (kill switch + safety + testnet routing + reconciliation)
for every order. Nothing new decides trades.

Safety: ``enabled`` defaults to False AND the kill switch must be
``TRADING_TESTNET``. There is no mainnet path — orders can only reach Testnet.
Fills come from the exchange (reconciled), never assumed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from backtesting.engine import BacktestConfig
from backtesting.execution import ExitEvent, resolve_candle
from backtesting.portfolio import position_size
from backtesting.trade import Position
from core.enums import ExitReason, SignalType, StructureClass, Timeframe
from core.logger import get_logger
from core.models import Signal, SymbolFilters

from .execution_backend import ExecutionBackend, SpotTestnetExecution
from .executor import SafeExecutor
from .kill_switch import TradingState
from .overtrading import OvertradingConfig, OvertradingGuard
from .safety import OrderIntent, PortfolioState, conform_to_filters

logger = get_logger("trading.testnet_session")


@dataclass
class TestnetSession:
    __test__ = False   # not a pytest test class despite the name

    signal_engine: object
    cfg: BacktestConfig
    executor: SafeExecutor
    symbol: str
    timeframe: Timeframe
    filters: Optional[SymbolFilters] = None
    initial_balance: float = 10_000.0
    enabled: bool = False                 # DISABLED by default (spec 19)
    strategy: str = "confluence"
    backend: ExecutionBackend = field(default_factory=SpotTestnetExecution)
    overtrading: OvertradingConfig = field(default_factory=OvertradingConfig)

    cash: float = field(init=False)
    realized_pnl: float = field(init=False, default=0.0)
    fees: float = field(init=False, default=0.0)
    position: Optional[Position] = field(init=False, default=None)
    pending: Optional[dict] = field(init=False, default=None)
    cursor: int = field(init=False, default=-1)
    bars_seen: int = field(init=False, default=0)
    guard: OvertradingGuard = field(init=False)
    journal: List[dict] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.cash = float(self.initial_balance)
        self.guard = OvertradingGuard(self.overtrading)

    # -- public -------------------------------------------------------------

    def equity(self, price: float) -> float:
        # Direction-aware mark-to-market: a SHORT owes qty*(price-entry).
        pos_val = 0.0
        if self.position and self.position.is_open:
            if self.position.is_short:
                pos_val = self.position.remaining_qty * (self.position.entry_eff - price)
            else:
                pos_val = self.position.remaining_qty * price
        return self.cash + pos_val

    def run(self, df: pd.DataFrame) -> dict:
        """Process a stream of CLOSED candles. No-op unless enabled + testnet."""
        if df is None or len(df) == 0:
            return {"processed": 0}
        df = df.sort_values("open_time").drop_duplicates("close_time", keep="first").reset_index(drop=True)
        processed = 0
        for i in range(len(df)):
            ct = int(df["close_time"].iloc[i])
            if ct <= self.cursor:
                continue
            sig = self.signal_engine.evaluate_at(df, i, self.symbol, self.timeframe)
            self.process_candle(float(df["open"].iloc[i]), float(df["high"].iloc[i]),
                                float(df["low"].iloc[i]), float(df["close"].iloc[i]),
                                int(df["open_time"].iloc[i]), ct, sig)
            self.cursor = ct
            processed += 1
        return {"processed": processed, "equity": self.equity(float(df["close"].iloc[-1]))}

    def process_candle(self, o, h, l, c, open_time, close_time, sig: Signal) -> dict:
        bar_index = self.bars_seen
        self.bars_seen += 1
        if not self.enabled:
            return {"skipped": "session disabled"}
        if self.executor.kill.state is not TradingState.TESTNET:
            return {"skipped": f"kill switch is {self.executor.kill.state.value}"}

        self._journal("SIGNAL", close_time, signal=sig.direction.value,
                      raw=round(sig.raw_score, 2), blocked_by=list(sig.blocked_by))

        # 1. fill pending entry -> TESTNET order at this candle's open
        if self.pending is not None:
            self._open(o, open_time)
            self.pending = None

        # 2. manage exits per triggered leg (direction-aware invalidation).
        if self.position is not None and self.position.is_open:
            self.position.update_excursion(h, l)
            for ev in resolve_candle(self.position, o, h, l, c, self.cfg.execution):
                if not self.position.is_open:
                    break
                self._exit_leg(ev, close_time)
            if self.position is not None and self.position.is_open and self.cfg.exit_on_structure_break:
                adverse = (StructureClass.BULLISH_STRUCTURE if self.position.is_short
                           else StructureClass.BEARISH_STRUCTURE)
                if sig.structure_class is adverse:
                    self._exit_leg(ExitEvent(self.position.remaining_fraction, c, ExitReason.INVALIDATION),
                                   close_time)

        # 3. schedule an entry for the NEXT candle if flat and executable.
        if (self.position is None and self.pending is None and sig.direction.is_directional
                and sig.entry and sig.stop and len(sig.take_profits) >= 1):
            # (a) can this backend execute this direction? Spot refuses SHORT and
            #     NEVER turns it into a SELL-to-open order.
            decision = self.backend.decide(sig.direction)
            if not decision.allowed:
                self._journal("EXECUTION_SKIPPED", close_time, direction=sig.direction.value,
                              reason=decision.reason, note=decision.note)
                return {"equity": self.equity(c)}
            # (b) anti-overtrading (cooldown / per-day cap / consecutive losses).
            allowed, why = self.guard.allow_entry(bar_index, int(close_time))
            if not allowed:
                self._journal("OVERTRADING_BLOCKED", close_time,
                              direction=sig.direction.value, reason=why)
                return {"equity": self.equity(c)}
            tps = sig.take_profits
            self.pending = {"signal_time": int(close_time), "stop": float(sig.stop),
                            "tp1": float(tps[0]), "tp2": float(tps[1] if len(tps) > 1 else tps[0]),
                            "direction": sig.direction.value, "bar_index": bar_index}
        return {"equity": self.equity(c)}

    # -- internals ----------------------------------------------------------

    def _pstate(self, price: float) -> PortfolioState:
        return PortfolioState(
            equity=self.equity(price), available_balance=self.cash,
            open_positions=1 if (self.position and self.position.is_open) else 0,
            day_realized_pnl=self.realized_pnl, initial_capital=self.initial_balance)

    def _open(self, open_price: float, entry_time: int) -> None:
        plan = self.pending
        direction = plan.get("direction", "LONG")
        is_short = direction == "SHORT"
        # Defence in depth: the backend gate should already have refused a SHORT
        # on Spot, but never let a SHORT become a SELL-to-open here either.
        decision = self.backend.decide(SignalType.SHORT if is_short else SignalType.LONG)
        if not decision.allowed:
            self._journal("EXECUTION_SKIPPED", entry_time, direction=direction, reason=decision.reason)
            return
        sizing = position_size(
            capital=self.equity(open_price), risk_pct=self.cfg.risk_per_trade,
            entry=open_price, stop=plan["stop"], side=direction, filters=self.filters,
            max_exposure_value=self.cfg.limits.max_total_exposure * self.equity(open_price),
            available_cash=self.cash)
        if not sizing.ok:
            self._journal("RISK_BLOCKED", entry_time, detail=sizing.reason)
            return
        qty, ref_price = conform_to_filters(sizing.qty, open_price, self.filters)
        if qty <= 0:
            self._journal("RISK_BLOCKED", entry_time, detail="qty rounds to zero")
            return
        entry_side = "SELL" if is_short else "BUY"
        intent = OrderIntent(self.strategy, self.symbol, self.timeframe.value,
                             plan["signal_time"], entry_side, qty, ref_price, tag="entry")
        res = self.executor.submit(intent, self.filters, self._pstate(open_price))
        if not (res.submitted and res.reconciled and res.reconciled.executed_qty > 0):
            self._journal("ORDER_BLOCKED", entry_time, detail=f"{res.status}:{res.blocked_reason}")
            return
        fill_qty = res.reconciled.executed_qty
        fill_price = res.reconciled.avg_price or open_price
        self.position = Position(
            symbol=self.symbol, timeframe=self.timeframe.value, signal_time=plan["signal_time"],
            entry_time=int(entry_time), entry_raw=fill_price, entry_eff=fill_price,
            stop=plan["stop"], tp1=plan["tp1"], tp2=plan["tp2"],
            original_qty=fill_qty, remaining_qty=fill_qty,
            tp1_alloc=self.cfg.execution.tp1_alloc, tp2_alloc=self.cfg.execution.tp2_alloc,
            direction=direction,
            entry_fee=res.reconciled.fees, entry_slippage=0.0,
            fees_paid=res.reconciled.fees, slippage_paid=0.0)
        # LONG spends cash to buy; SHORT (futures, future path) only pays the fee.
        if is_short:
            self.cash -= res.reconciled.fees
        else:
            self.cash -= fill_qty * fill_price + res.reconciled.fees
        self.fees += res.reconciled.fees
        self.guard.record_entry(plan.get("bar_index", self.bars_seen), int(entry_time))
        self._journal("POSITION_OPEN", entry_time, signal_time=plan["signal_time"],
                      direction=direction, stop=plan["stop"], tp1=plan["tp1"], tp2=plan["tp2"],
                      detail=f"{direction} qty={fill_qty} entry={fill_price} cid={res.client_order_id}")

    def _exit_leg(self, ev: ExitEvent, close_time: int) -> None:
        pos = self.position
        qty = min(pos.original_qty * ev.fraction, pos.remaining_qty)
        qty, ref_price = conform_to_filters(qty, ev.price, self.filters)
        if qty <= 0:
            return
        # A LONG exit SELLS; a SHORT exit BUYS to cover.
        exit_side = "BUY" if pos.is_short else "SELL"
        intent = OrderIntent(self.strategy, self.symbol, self.timeframe.value,
                             pos.signal_time, exit_side, qty, ref_price, tag=ev.reason.value)
        res = self.executor.submit(intent, self.filters, self._pstate(ev.price))
        if not (res.submitted and res.reconciled and res.reconciled.executed_qty > 0):
            self._journal("ORDER_BLOCKED", close_time, detail=f"exit {ev.reason.value}: {res.status}")
            return
        fill_qty = res.reconciled.executed_qty
        fill_price = res.reconciled.avg_price or ev.price
        if pos.is_short:
            gross = fill_qty * (pos.entry_eff - fill_price)   # short profits as price falls
            self.cash += fill_qty * (pos.entry_eff - fill_price) - res.reconciled.fees
        else:
            gross = fill_qty * (fill_price - pos.entry_eff)
            self.cash += fill_qty * fill_price - res.reconciled.fees
        leg_net = gross - res.reconciled.fees
        self.realized_pnl += leg_net
        self.fees += res.reconciled.fees
        pos.realized_pnl += leg_net          # accumulate the trade's net over its legs
        pos.remaining_qty -= fill_qty
        if ev.reason is ExitReason.TP1:
            pos.tp1_done = True
        self._journal("EXIT", close_time,
                      detail=f"{ev.reason.value} qty={fill_qty} price={fill_price} pnl={leg_net:.4f}")
        if not pos.is_open:
            # Consecutive-loss protection keys off the CLOSED trade's total net.
            self.guard.record_result(pos.realized_pnl)
            self.position = None

    def _journal(self, event, ts, **kw) -> None:
        self.journal.append({"event": event, "timestamp": ts, **kw})


def run_testnet_session(session: TestnetSession, df: pd.DataFrame) -> dict:
    """Convenience runner. Requires the session to be explicitly enabled and the
    kill switch set to TRADING_TESTNET; otherwise it is a safe no-op per candle."""
    return session.run(df)
