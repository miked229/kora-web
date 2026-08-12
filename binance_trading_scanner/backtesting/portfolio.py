"""Position sizing, portfolio accounting, risk limits and the equity curve.

Sizing is risk-based (spec 11): ``risk_amount = capital * risk% `` and
``qty = risk_amount / stop_distance``, then capped by available cash (Spot has no
leverage), max exposure, and exchange lot filters. Every guard against the
section-33 edge cases (zero/negative capital, invalid risk %, zero stop distance,
below-minimum size) returns a reason instead of producing an impossible fill.

The portfolio records equity after every candle so drawdown can be measured.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from core.models import SymbolFilters

from .trade import Position


# --------------------------------------------------------------------------
# Position sizing
# --------------------------------------------------------------------------

@dataclass
class SizingResult:
    ok: bool
    qty: float = 0.0
    notional: float = 0.0
    risk_amount: float = 0.0
    risk_per_unit: float = 0.0
    reason: str = ""


def _round_step(qty: float, step: float) -> float:
    if step and step > 0:
        return math.floor(qty / step) * step
    return qty


def position_size(
    capital: float,
    risk_pct: float,
    entry: float,
    stop: float,
    *,
    filters: Optional[SymbolFilters] = None,
    max_exposure_value: Optional[float] = None,
    available_cash: Optional[float] = None,
) -> SizingResult:
    """Risk-based position size for a LONG, with validation and caps.

    ``risk_pct`` is a fraction (0.01 == 1%). Never returns a negative size and
    never divides by zero.
    """
    if capital is None or capital <= 0 or not math.isfinite(capital):
        return SizingResult(False, reason="invalid capital (must be > 0)")
    if not (0.0 < risk_pct <= 1.0) or not math.isfinite(risk_pct):
        return SizingResult(False, reason="invalid risk percentage (0 < risk <= 1)")
    if entry is None or entry <= 0 or not math.isfinite(entry):
        return SizingResult(False, reason="invalid entry price")
    if stop is None or stop <= 0 or not math.isfinite(stop):
        return SizingResult(False, reason="invalid stop price")

    risk_per_unit = entry - stop
    if risk_per_unit <= 0:
        return SizingResult(False, risk_per_unit=risk_per_unit,
                            reason="zero/negative stop distance (stop not below entry)")

    risk_amount = capital * risk_pct
    qty = risk_amount / risk_per_unit
    notional = qty * entry

    # Cap by max exposure value.
    if max_exposure_value is not None and notional > max_exposure_value > 0:
        qty = max_exposure_value / entry
        notional = qty * entry
    # Cap by available cash (Spot: cannot spend more than we hold).
    if available_cash is not None and notional > available_cash:
        if available_cash <= 0:
            return SizingResult(False, reason="no available cash")
        qty = available_cash / entry
        notional = qty * entry

    # Exchange lot filters.
    if filters is not None:
        qty = _round_step(qty, filters.step_size)
        notional = qty * entry
        if filters.min_qty and qty < filters.min_qty:
            return SizingResult(False, qty=qty, notional=notional, risk_amount=risk_amount,
                                risk_per_unit=risk_per_unit,
                                reason=f"size {qty} below min qty {filters.min_qty}")
        if filters.min_notional and notional < filters.min_notional:
            return SizingResult(False, qty=qty, notional=notional, risk_amount=risk_amount,
                                risk_per_unit=risk_per_unit,
                                reason=f"notional {notional:.4f} below min notional {filters.min_notional}")

    if qty <= 0:
        return SizingResult(False, reason="computed size is zero")

    return SizingResult(True, qty=qty, notional=notional, risk_amount=risk_amount,
                        risk_per_unit=risk_per_unit)


# --------------------------------------------------------------------------
# Risk limits & portfolio
# --------------------------------------------------------------------------

@dataclass
class RiskLimits:
    risk_per_trade: float = 0.01
    max_open_positions: int = 1        # single-symbol sequential default
    max_daily_loss: float = 0.05       # fraction of initial capital
    max_total_exposure: float = 0.50   # fraction of current equity


@dataclass
class EquityPoint:
    timestamp: int
    cash: float
    equity: float
    peak: float
    drawdown: float
    drawdown_pct: float


class Portfolio:
    """Cash/asset accounting with risk gates and an equity curve."""

    def __init__(self, initial_capital: float, limits: Optional[RiskLimits] = None) -> None:
        if initial_capital is None or initial_capital <= 0 or not math.isfinite(initial_capital):
            raise ValueError("initial_capital must be a positive finite number")
        self.initial_capital = float(initial_capital)
        self.limits = limits or RiskLimits()
        self.cash = float(initial_capital)
        self.positions: List[Position] = []
        self.realized_pnl = 0.0
        self.fees_total = 0.0
        self.slippage_total = 0.0
        self.risk_blocked = 0
        self.peak_equity = float(initial_capital)
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
        self.equity_curve: List[EquityPoint] = []
        self._daily_realized: Dict[str, float] = {}

    # -- valuation ----------------------------------------------------------

    def exposure(self, price: float) -> float:
        return sum(p.remaining_qty * price for p in self.positions)

    def equity(self, price: float) -> float:
        return self.cash + self.exposure(price)

    # -- risk gate ----------------------------------------------------------

    def can_open(self, notional: float, price: float, day_key: str) -> Tuple[bool, str]:
        if len(self.positions) >= self.limits.max_open_positions:
            return False, "max_open_positions reached"
        day_loss = self._daily_realized.get(day_key, 0.0)
        if day_loss <= -abs(self.limits.max_daily_loss) * self.initial_capital:
            return False, "max_daily_loss reached"
        equity = self.equity(price)
        if (self.exposure(price) + notional) > self.limits.max_total_exposure * equity + 1e-9:
            return False, "max_total_exposure reached"
        if notional > self.cash + 1e-9:
            return False, "insufficient cash"
        return True, ""

    # -- lifecycle ----------------------------------------------------------

    def open_position(self, pos: Position) -> None:
        self.cash -= pos.original_qty * pos.entry_eff + pos.entry_fee
        self.fees_total += pos.entry_fee
        self.slippage_total += pos.entry_slippage
        self.positions.append(pos)

    def apply_exit_leg(self, pos: Position, qty: float, exit_eff: float,
                       exit_fee: float, exit_slip: float, leg_net: float, day_key: str) -> None:
        self.cash += qty * exit_eff - exit_fee
        self.fees_total += exit_fee
        self.slippage_total += exit_slip
        pos.remaining_qty -= qty
        # Realised PnL of this leg = raw move minus exit costs. Entry costs are
        # realised proportionally as the position is closed out.
        entry_cost_share = (pos.entry_fee + pos.entry_slippage) * (qty / pos.original_qty)
        realised = leg_net - entry_cost_share
        self.realized_pnl += realised
        self._daily_realized[day_key] = self._daily_realized.get(day_key, 0.0) + realised
        if not pos.is_open:
            self.positions = [p for p in self.positions if p is not pos]

    # -- equity curve -------------------------------------------------------

    def record_equity(self, timestamp: int, price: float) -> EquityPoint:
        eq = self.equity(price)
        self.peak_equity = max(self.peak_equity, eq)
        dd = self.peak_equity - eq
        dd_pct = (dd / self.peak_equity * 100.0) if self.peak_equity > 0 else 0.0
        self.max_drawdown = max(self.max_drawdown, dd)
        self.max_drawdown_pct = max(self.max_drawdown_pct, dd_pct)
        pt = EquityPoint(timestamp, self.cash, eq, self.peak_equity, dd, dd_pct)
        self.equity_curve.append(pt)
        return pt


def day_key_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
