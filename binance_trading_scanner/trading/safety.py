"""Pre-trade safety checks, symbol whitelist and logical order identity.

Every order must pass ALL checks before it can be sent (spec 7). A failing check
returns a BLOCKED result with the exact reason and NO order is created. These
checks reuse the exchange filters (:class:`SymbolFilters`) and the portfolio/risk
rules from the backtester — no duplicated logic.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Set

from core.models import SymbolFilters

DEFAULT_WHITELIST: Set[str] = {"BTCUSDT", "ETHUSDT"}
_STEP_EPS = 1e-9


@dataclass
class SafetyConfig:
    whitelist: Set[str] = field(default_factory=lambda: set(DEFAULT_WHITELIST))
    max_order_notional: float = 1_000.0     # per-order cap
    max_open_positions: int = 1
    max_total_exposure: float = 0.50        # fraction of equity
    max_daily_loss: float = 0.05            # fraction of capital
    # LIVE-only caps (documented; enforced when/if live is ever enabled)
    max_live_capital: float = 0.0
    max_risk_per_trade: float = 0.01


@dataclass
class OrderIntent:
    strategy: str
    symbol: str
    timeframe: str
    signal_timestamp: int
    side: str                     # BUY / SELL
    quantity: float
    reference_price: float        # for notional / validation only
    tag: str = ""                 # distinguishes legs (e.g. TP1/TP2/STOP) of one signal


@dataclass
class PortfolioState:
    equity: float
    available_balance: float
    open_positions: int
    day_realized_pnl: float
    initial_capital: float


@dataclass
class SafetyResult:
    ok: bool
    reason: str = ""
    checks: Dict[str, bool] = field(default_factory=dict)


def client_order_id(intent: OrderIntent) -> str:
    """Deterministic logical id (spec 13) so a signal is never sent twice.

    Binance ``newClientOrderId`` allows ``[A-Za-z0-9-_]`` up to 36 chars. To stay
    within the limit while remaining collision-free across strategy/symbol/
    timeframe/signal-time/side, we use a readable prefix (side initial + symbol)
    plus a hash of the FULL logical key — so BUY and SELL never collide.
    """
    raw = (f"{intent.strategy}|{intent.symbol}|{intent.timeframe}|"
           f"{intent.signal_timestamp}|{intent.side}|{intent.tag}")
    digest = hashlib.sha1(raw.encode()).hexdigest()[:22]
    prefix = re.sub(r"[^A-Za-z0-9]", "", f"{intent.side[:1]}{intent.symbol}")[:12]
    return f"{prefix}-{digest}"


def conform_to_filters(quantity: float, price: float,
                       filters: Optional[SymbolFilters]) -> tuple[float, float]:
    """Round quantity down to step size and price to tick size (exchange-safe).

    Returns ``(qty, price)`` that satisfy the LOT_SIZE / PRICE_FILTER grids so a
    value derived from a signal can never be rejected for precision.
    """
    if filters is None:
        return quantity, price
    q = quantity
    if filters.step_size and filters.step_size > 0:
        q = (int(q / filters.step_size)) * filters.step_size
    p = price
    if filters.tick_size and filters.tick_size > 0:
        p = (int(p / filters.tick_size)) * filters.tick_size
    return q, p


def _is_multiple(value: float, step: float) -> bool:
    if not step or step <= 0:
        return True
    ratio = value / step
    return abs(ratio - round(ratio)) < 1e-6


def check_order(
    intent: OrderIntent,
    filters: Optional[SymbolFilters],
    state: PortfolioState,
    cfg: SafetyConfig,
    existing_client_ids: Iterable[str],
) -> SafetyResult:
    """Run every pre-trade check. Returns ok=False with the exact failing reason."""
    checks: Dict[str, bool] = {}

    def fail(name: str, reason: str) -> SafetyResult:
        checks[name] = False
        # Prefix with the check key so callers can match on a stable identifier.
        return SafetyResult(False, f"{name}: {reason}", checks)

    # symbol whitelist
    checks["symbol_whitelisted"] = intent.symbol in cfg.whitelist
    if not checks["symbol_whitelisted"]:
        return fail("symbol_whitelisted", f"{intent.symbol} not in whitelist {sorted(cfg.whitelist)}")

    # basic validity — reject None, non-finite (NaN/inf) and non-positive values.
    if intent.quantity is None or not math.isfinite(intent.quantity) or intent.quantity <= 0:
        return fail("quantity_positive", "quantity must be a positive finite number")
    checks["quantity_positive"] = True
    if intent.reference_price is None or not math.isfinite(intent.reference_price) or intent.reference_price <= 0:
        return fail("price_positive", "reference price must be a positive finite number")
    checks["price_positive"] = True

    notional = intent.quantity * intent.reference_price

    # exchange filters
    if filters is not None:
        if filters.min_qty and intent.quantity < filters.min_qty:
            return fail("min_qty", f"qty {intent.quantity} < min_qty {filters.min_qty}")
        checks["min_qty"] = True
        if not _is_multiple(intent.quantity, filters.step_size):
            return fail("step_size", f"qty {intent.quantity} not a multiple of step {filters.step_size}")
        checks["step_size"] = True
        if not _is_multiple(intent.reference_price, filters.tick_size):
            return fail("tick_size", f"price {intent.reference_price} not a multiple of tick {filters.tick_size}")
        checks["tick_size"] = True
        if filters.min_notional and notional < filters.min_notional:
            return fail("min_notional", f"notional {notional:.4f} < min_notional {filters.min_notional}")
        checks["min_notional"] = True

    # per-order notional cap
    if cfg.max_order_notional and notional > cfg.max_order_notional:
        return fail("max_order_notional", f"notional {notional:.2f} > cap {cfg.max_order_notional}")
    checks["max_order_notional"] = True

    # balance (only meaningful for BUYs)
    if intent.side == "BUY" and notional > state.available_balance + _STEP_EPS:
        return fail("sufficient_balance",
                    f"notional {notional:.2f} > available {state.available_balance:.2f}")
    checks["sufficient_balance"] = True

    # exposure / positions / daily loss
    if intent.side == "BUY":
        if state.open_positions >= cfg.max_open_positions:
            return fail("max_open_positions", "max open positions reached")
        checks["max_open_positions"] = True
        if notional > cfg.max_total_exposure * state.equity + _STEP_EPS:
            return fail("max_total_exposure", "would exceed max total exposure")
        checks["max_total_exposure"] = True
    if state.day_realized_pnl <= -abs(cfg.max_daily_loss) * state.initial_capital:
        return fail("max_daily_loss", "max daily loss reached")
    checks["max_daily_loss"] = True

    # duplicate signal / order protection
    if client_order_id(intent) in set(existing_client_ids):
        return fail("duplicate_order", f"duplicate client_order_id {client_order_id(intent)}")
    checks["duplicate_order"] = True

    return SafetyResult(True, "", checks)
