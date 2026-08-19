"""Market structure: swing points, HH/HL/LH/LL, breakout, support/resistance.

Look-ahead policy (important): a swing pivot at bar ``i`` is only *confirmed*
``right`` bars later. Every function here therefore leaves the most recent
``right`` bars unmarked — a pivot is reported only once it is genuinely
confirmed by already-closed candles. This mirrors how a trader can only know a
pivot formed after price has moved away from it, and keeps structure analysis
free of forward-looking bias.

Structure describes price geometry only. It does NOT emit LONG/SHORT signals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from ._common import ArrayLike, as_series


# --------------------------------------------------------------------------
# Swing detection
# --------------------------------------------------------------------------

def swing_highs(high: ArrayLike, left: int = 2, right: int = 2) -> pd.Series:
    """Boolean Series: True at confirmed swing-high pivots.

    A bar is a swing high if its value is strictly greater than the ``left``
    bars before it and the ``right`` bars after it. The final ``right`` bars are
    never marked (unconfirmed).
    """
    return _pivots(as_series(high, "high"), left, right, want_high=True)


def swing_lows(low: ArrayLike, left: int = 2, right: int = 2) -> pd.Series:
    """Boolean Series: True at confirmed swing-low pivots (strict)."""
    return _pivots(as_series(low, "low"), left, right, want_high=False)


def _pivots(s: pd.Series, left: int, right: int, *, want_high: bool) -> pd.Series:
    """Vectorised strict swing-pivot detection.

    Functionally identical to the original per-bar loop: a bar is a pivot when it
    is strictly above (high) / below (low) each of the ``left`` preceding and
    ``right`` following bars, the final ``right`` and first ``left`` bars are
    never marked, and any NaN in the centre or a neighbour disqualifies the bar.

    NaN comparisons in NumPy evaluate to ``False``, which reproduces the old
    "skip if NaN" rule exactly, so the boolean output is bit-for-bit the same —
    but this runs in a handful of vectorised passes instead of an O(n·window)
    Python loop (see tests/test_perf.py for the equivalence proof).
    """
    if left < 1 or right < 1:
        raise ValueError("left and right must be >= 1")
    name = "swing_high" if want_high else "swing_low"
    vals = s.to_numpy(dtype="float64")
    n = len(vals)
    if n == 0:
        return pd.Series(np.zeros(0, dtype=bool), index=s.index, name=name)

    cond = np.ones(n, dtype=bool)
    for k in range(1, left + 1):                 # neighbour at i-k
        nb = np.full(n, np.nan)
        nb[k:] = vals[:-k]
        cond &= (vals > nb) if want_high else (vals < nb)
    for k in range(1, right + 1):                # neighbour at i+k
        nb = np.full(n, np.nan)
        nb[:-k] = vals[k:]
        cond &= (vals > nb) if want_high else (vals < nb)
    # The first `left` and last `right` bars can never be confirmed pivots.
    cond[:left] = False
    cond[max(n - right, 0):] = False
    return pd.Series(cond, index=s.index, name=name)


# --------------------------------------------------------------------------
# Structure classification (HH / HL / LH / LL)
# --------------------------------------------------------------------------

@dataclass
class StructureState:
    """Summary of the most recent confirmed structure."""

    higher_high: bool = False
    higher_low: bool = False
    lower_high: bool = False
    lower_low: bool = False
    last_swing_high: Optional[float] = None
    prev_swing_high: Optional[float] = None
    last_swing_low: Optional[float] = None
    prev_swing_low: Optional[float] = None
    # "up" (HH & HL), "down" (LH & LL), or "range"/None otherwise.
    trend: Optional[str] = None


def market_structure(
    high: ArrayLike, low: ArrayLike, left: int = 2, right: int = 2
) -> StructureState:
    """Classify recent structure from the last two confirmed swings each side."""
    h = as_series(high, "high")
    l = as_series(low, "low")
    sh = _pivots(h, left, right, want_high=True)
    sl = _pivots(l, left, right, want_high=False)

    high_vals = h[sh].to_list()
    low_vals = l[sl].to_list()

    state = StructureState()
    if len(high_vals) >= 1:
        state.last_swing_high = high_vals[-1]
    if len(high_vals) >= 2:
        state.prev_swing_high = high_vals[-2]
        state.higher_high = high_vals[-1] > high_vals[-2]
        state.lower_high = high_vals[-1] < high_vals[-2]
    if len(low_vals) >= 1:
        state.last_swing_low = low_vals[-1]
    if len(low_vals) >= 2:
        state.prev_swing_low = low_vals[-2]
        state.higher_low = low_vals[-1] > low_vals[-2]
        state.lower_low = low_vals[-1] < low_vals[-2]

    if state.higher_high and state.higher_low:
        state.trend = "up"
    elif state.lower_high and state.lower_low:
        state.trend = "down"
    elif state.last_swing_high is not None and state.last_swing_low is not None:
        state.trend = "range"
    return state


# --------------------------------------------------------------------------
# Breakout detection
# --------------------------------------------------------------------------

def breakout_detection(
    high: ArrayLike, low: ArrayLike, close: ArrayLike, lookback: int = 20
) -> pd.DataFrame:
    """Detect closes breaking the prior ``lookback``-bar range.

    ``breakout_up``: close exceeds the highest high of the previous ``lookback``
    bars (the current bar is excluded via a shift, so this is causal).
    ``breakout_down``: close falls below the lowest low of that window.
    Also returns the ``prior_high`` / ``prior_low`` reference levels.
    """
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    h = as_series(high, "high")
    l = as_series(low, "low")
    c = as_series(close, "close")
    if c.empty:
        return pd.DataFrame(columns=["breakout_up", "breakout_down", "prior_high", "prior_low"])

    prior_high = h.shift(1).rolling(window=lookback, min_periods=lookback).max()
    prior_low = l.shift(1).rolling(window=lookback, min_periods=lookback).min()
    breakout_up = c > prior_high
    breakout_down = c < prior_low
    # Keep breakout flags NaN-safe: where reference is NaN, flag is False.
    breakout_up = breakout_up.where(prior_high.notna(), False)
    breakout_down = breakout_down.where(prior_low.notna(), False)
    return pd.DataFrame(
        {
            "breakout_up": breakout_up,
            "breakout_down": breakout_down,
            "prior_high": prior_high,
            "prior_low": prior_low,
        },
        index=c.index,
    )


# --------------------------------------------------------------------------
# Support / resistance
# --------------------------------------------------------------------------

@dataclass
class SupportResistance:
    """Nearest support/resistance plus all confirmed pivot levels."""

    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)


def support_resistance(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    left: int = 2,
    right: int = 2,
    max_levels: int = 5,
) -> SupportResistance:
    """Derive support/resistance from confirmed swing lows/highs.

    Resistance levels come from confirmed swing highs, support from confirmed
    swing lows. ``nearest_*`` are relative to the last close.
    """
    h = as_series(high, "high")
    l = as_series(low, "low")
    c = as_series(close, "close")
    sr = SupportResistance()
    if c.empty:
        return sr

    sh = _pivots(h, left, right, want_high=True)
    sl = _pivots(l, left, right, want_high=False)
    res_levels = h[sh].to_list()
    sup_levels = l[sl].to_list()

    # Keep the most recent distinct levels.
    sr.resistance_levels = res_levels[-max_levels:]
    sr.support_levels = sup_levels[-max_levels:]

    last_close = c.dropna()
    if last_close.empty:
        return sr
    price = float(last_close.iloc[-1])

    res_above = [lv for lv in res_levels if lv >= price]
    sup_below = [lv for lv in sup_levels if lv <= price]
    sr.nearest_resistance = min(res_above) if res_above else None
    sr.nearest_support = max(sup_below) if sup_below else None
    return sr
