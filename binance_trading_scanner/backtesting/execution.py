"""Execution model: entry timing, fees, slippage and intrabar resolution.

Design choices are deliberately conservative (spec sections 3, 4, 7, 34):

* ENTRY TIMING — a signal is produced at a candle's CLOSE and executed at the
  NEXT candle's OPEN. Nothing is filled using data that would not yet have been
  available. (``EntryTiming.NEXT_OPEN``, the default.)

* OHLC EXECUTION — exits are checked against the following candles' High/Low.
  Fills use the trigger level (stop / TP), adjusted for slippage; gaps are
  respected by the engine, which fills entries at the actual open.

* INTRABAR AMBIGUITY — if a single candle's High reaches a TP and its Low
  reaches the stop, OHLC alone cannot tell which came first. We never pick the
  favourable one by default. ``AmbiguityPolicy``:
    - CONSERVATIVE (default): assume the STOP filled first (worst case).
    - OPTIMISTIC: assume the TP(s) filled first.
    - SKIP: ignore the intrabar extremes on that candle and settle at its CLOSE.

Direction-aware (LONG/SHORT). All functions here are pure and deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple

from core.enums import ExitReason

from .trade import Position


class EntryTiming(str, Enum):
    NEXT_OPEN = "NEXT_OPEN"   # default: fill at the next candle's open
    CLOSE = "CLOSE"           # fill at the signal candle's close (not recommended)


class AmbiguityPolicy(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    OPTIMISTIC = "OPTIMISTIC"
    SKIP = "SKIP"


@dataclass
class ExecutionConfig:
    entry_timing: EntryTiming = EntryTiming.NEXT_OPEN
    fee_rate: float = 0.001            # 0.10% per side (Binance Spot taker default)
    slippage_rate: float = 0.0005      # 0.05% per side
    ambiguity: AmbiguityPolicy = AmbiguityPolicy.CONSERVATIVE
    tp1_alloc: float = 0.5             # fraction of position closed at TP1
    tp2_alloc: float = 0.5             # remainder closed at TP2
    move_stop_to_breakeven_after_tp1: bool = False  # only if strategy allows

    def __post_init__(self) -> None:
        if self.fee_rate < 0 or self.slippage_rate < 0:
            raise ValueError("fee_rate and slippage_rate must be non-negative")
        if not (0.0 < self.tp1_alloc <= 1.0) or not (0.0 <= self.tp2_alloc <= 1.0):
            raise ValueError("tp allocations must be within (0,1]")
        if abs((self.tp1_alloc + self.tp2_alloc) - 1.0) > 1e-9:
            raise ValueError("tp1_alloc + tp2_alloc must equal 1.0")


# -- price adjustments ------------------------------------------------------

def buy_fill_price(raw: float, cfg: ExecutionConfig) -> float:
    """Effective price paid when BUYING (entry): slippage moves it up."""
    return raw * (1.0 + cfg.slippage_rate)


def sell_fill_price(raw: float, cfg: ExecutionConfig) -> float:
    """Effective price received when SELLING (exit): slippage moves it down."""
    return raw * (1.0 - cfg.slippage_rate)


def fee_on(notional: float, cfg: ExecutionConfig) -> float:
    return abs(notional) * cfg.fee_rate


# -- intrabar exit resolution ----------------------------------------------

@dataclass
class ExitEvent:
    """A resolved exit for (a fraction of) the original position."""

    fraction: float           # fraction of the ORIGINAL quantity
    price: float              # trigger price (pre-slippage)
    reason: ExitReason


def resolve_candle(
    pos: Position, open_: float, high: float, low: float, close: float, cfg: ExecutionConfig
) -> List[ExitEvent]:
    """Return the exit events triggered by one candle (direction-aware).

    Handles partial TP1 -> TP2, stop-outs, and the same-candle SL/TP ambiguity
    according to ``cfg.ambiguity``. Returns an empty list when nothing triggers.

    Gap realism (spec 4): if a candle gaps THROUGH the stop (a LONG gap-down
    below the stop, or a SHORT gap-up above the stop), the stop fills at the open,
    never at the unreachable stop level — we never assume an impossible fill.
    """
    stop, tp1, tp2 = pos.stop, pos.tp1, pos.tp2
    remaining = pos.remaining_fraction

    if pos.is_short:
        # SHORT: stop is ABOVE entry (hit by highs), TPs BELOW entry (hit by lows).
        stop_fill = max(stop, open_)   # gap-up through the stop fills at the open
        sl_touch = high >= stop
        tp1_touch = (not pos.tp1_done) and tp1 is not None and low <= tp1
        tp2_touch = tp2 is not None and low <= tp2
    else:
        stop_fill = min(stop, open_)   # gap-down through the stop fills at the open
        sl_touch = low <= stop
        tp1_touch = (not pos.tp1_done) and tp1 is not None and high >= tp1
        tp2_touch = tp2 is not None and high >= tp2

    if not (sl_touch or tp1_touch or tp2_touch):
        return []

    ambiguous = sl_touch and (tp1_touch or tp2_touch)
    if ambiguous:
        if cfg.ambiguity is AmbiguityPolicy.CONSERVATIVE:
            # Worst case: assume the stop filled first — close everything at stop.
            return [ExitEvent(remaining, stop_fill, ExitReason.STOP_LOSS)]
        if cfg.ambiguity is AmbiguityPolicy.SKIP:
            return [_settle_at_close(pos, close)]
        # OPTIMISTIC: assume TP(s) came first; ignore the stop this candle.
        sl_touch = False

    events: List[ExitEvent] = []
    if not pos.tp1_done:
        if tp2_touch:
            # TP1 and TP2 both reached in one candle -> both fill.
            events.append(ExitEvent(pos.tp1_alloc, tp1, ExitReason.TP1))
            events.append(ExitEvent(pos.tp2_alloc, tp2, ExitReason.TP2))
            return events
        if tp1_touch:
            events.append(ExitEvent(pos.tp1_alloc, tp1, ExitReason.TP1))
            return events   # remainder stays open
        if sl_touch:
            return [ExitEvent(remaining, stop_fill, ExitReason.STOP_LOSS)]
    else:
        if tp2_touch:
            return [ExitEvent(remaining, tp2, ExitReason.TP2)]
        if sl_touch:
            return [ExitEvent(remaining, stop_fill, ExitReason.STOP_LOSS)]
    return events


def _settle_at_close(pos: Position, close: float) -> ExitEvent:
    """SKIP policy: ignore intrabar extremes, settle the remainder at the close."""
    if pos.is_short:
        if close >= pos.stop:
            reason = ExitReason.STOP_LOSS
        elif pos.tp2 is not None and close <= pos.tp2:
            reason = ExitReason.TP2
        elif (not pos.tp1_done) and pos.tp1 is not None and close <= pos.tp1:
            reason = ExitReason.TP1
        else:
            reason = ExitReason.INVALIDATION
    else:
        if close <= pos.stop:
            reason = ExitReason.STOP_LOSS
        elif pos.tp2 is not None and close >= pos.tp2:
            reason = ExitReason.TP2
        elif (not pos.tp1_done) and pos.tp1 is not None and close >= pos.tp1:
            reason = ExitReason.TP1
        else:
            reason = ExitReason.INVALIDATION   # indeterminate intrabar -> close-based
    return ExitEvent(pos.remaining_fraction, close, reason)


def leg_pnl(
    pos: Position, event: ExitEvent, cfg: ExecutionConfig
) -> Tuple[float, float, float, float, float, float]:
    """Compute (qty, exit_eff, gross, exit_fee, exit_slip, leg_net) for one exit.

    Direction-aware: a LONG exit SELLS (slippage down, profit when price rises); a
    SHORT exit BUYS to cover (slippage up, profit when price falls). Only exit-side
    costs are attributed here; the one-off entry fee/slippage are subtracted once at
    the trade level, so summing legs never double-counts them. Slippage is surfaced
    separately and never hidden inside PnL.
    """
    qty = pos.original_qty * event.fraction
    if pos.is_short:
        exit_eff = buy_fill_price(event.price, cfg)     # cover = buy back, pays more
        gross = qty * (pos.entry_raw - event.price)     # short profits as price falls
    else:
        exit_eff = sell_fill_price(event.price, cfg)
        gross = qty * (event.price - pos.entry_raw)     # raw price move, no costs
    exit_fee = fee_on(qty * exit_eff, cfg)
    exit_slip = qty * event.price * cfg.slippage_rate
    leg_net = gross - exit_fee - exit_slip          # exit-only net (entry costs added later)
    return qty, exit_eff, gross, exit_fee, exit_slip, leg_net
