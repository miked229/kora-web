"""Trade & position records for the backtester.

``Position`` is the mutable open-trade state the engine mutates candle-by-candle.
``Trade`` is the immutable record written when a position is fully closed. A
position may close in several legs (e.g. partial TP1 then TP2/stop); the Trade
aggregates all legs while still exposing the individual fills for the report.

All prices/quantities are plain floats; timestamps are millisecond epochs taken
straight from the candles so records are deterministic and reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from core.enums import ExitReason


@dataclass
class Leg:
    """One (partial) exit fill."""

    timestamp: int          # ms epoch of the candle that produced the fill
    qty: float
    price: float            # effective fill price (after slippage)
    reason: ExitReason
    gross_pnl: float
    fees: float
    slippage: float
    net_pnl: float


@dataclass
class Position:
    """Open-trade state. Longs only (Spot)."""

    symbol: str
    timeframe: str
    signal_time: int
    entry_time: int
    entry_raw: float           # candle open before slippage
    entry_eff: float           # effective entry after slippage
    stop: float
    tp1: Optional[float]
    tp2: Optional[float]
    original_qty: float
    remaining_qty: float
    tp1_alloc: float
    tp2_alloc: float
    entry_fee: float = 0.0
    entry_slippage: float = 0.0
    fees_paid: float = 0.0         # includes entry_fee
    slippage_paid: float = 0.0     # includes entry_slippage
    realized_pnl: float = 0.0
    tp1_done: bool = False
    mfe_r: float = 0.0             # max favourable excursion, in R
    mae_r: float = 0.0             # max adverse excursion, in R (<= 0)
    legs: List[Leg] = field(default_factory=list)

    @property
    def risk_per_unit(self) -> float:
        return self.entry_eff - self.stop

    @property
    def initial_risk(self) -> float:
        return self.original_qty * self.risk_per_unit

    @property
    def remaining_fraction(self) -> float:
        return self.remaining_qty / self.original_qty if self.original_qty else 0.0

    @property
    def is_open(self) -> bool:
        return self.remaining_qty > 1e-12

    def update_excursion(self, high: float, low: float) -> None:
        """Track MFE/MAE in R units from the effective entry."""
        rpu = self.risk_per_unit
        if rpu <= 0:
            return
        self.mfe_r = max(self.mfe_r, (high - self.entry_eff) / rpu)
        self.mae_r = min(self.mae_r, (low - self.entry_eff) / rpu)


@dataclass
class Trade:
    """Immutable closed-trade record (spec section 14)."""

    id: int
    symbol: str
    timeframe: str
    direction: str
    signal_timestamp: int
    entry_timestamp: int
    entry_price: float
    stop_price: float
    tp1_price: Optional[float]
    tp2_price: Optional[float]
    exit_timestamp: int
    exit_price: float
    quantity: float
    fees: float
    slippage: float
    gross_pnl: float
    net_pnl: float
    return_pct: float
    r_multiple: float
    exit_reason: ExitReason
    duration_bars: int
    duration_ms: int
    max_favorable_excursion: float   # in R
    max_adverse_excursion: float     # in R
    tp1_hit: bool
    legs: List[Leg] = field(default_factory=list)

    @property
    def is_winner(self) -> bool:
        return self.net_pnl > 0

    @property
    def entry_dt(self) -> datetime:
        return datetime.fromtimestamp(self.entry_timestamp / 1000, tz=timezone.utc)

    @property
    def exit_dt(self) -> datetime:
        return datetime.fromtimestamp(self.exit_timestamp / 1000, tz=timezone.utc)

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in (
            "id", "symbol", "timeframe", "direction", "signal_timestamp",
            "entry_timestamp", "entry_price", "stop_price", "tp1_price", "tp2_price",
            "exit_timestamp", "exit_price", "quantity", "fees", "slippage",
            "gross_pnl", "net_pnl", "return_pct", "r_multiple", "duration_bars",
            "duration_ms", "max_favorable_excursion", "max_adverse_excursion", "tp1_hit",
        )}
        d["exit_reason"] = self.exit_reason.value
        return d
