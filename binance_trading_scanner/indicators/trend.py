"""Trend indicators: EMA 20/50/200, SMA 200, ADX.

All functions are causal (no future data). They return Series aligned to the
input index; the warm-up period is filled with NaN, which downstream code must
treat as "not enough data yet".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import ArrayLike, _validate_period, as_series, rma


def ema(data: ArrayLike, period: int) -> pd.Series:
    """Exponential moving average (``adjust=False`` -> classic recursive EMA)."""
    _validate_period(period)
    s = as_series(data, "ema")
    if s.empty:
        return s
    return s.ewm(span=period, adjust=False).mean().rename(f"ema_{period}")


def sma(data: ArrayLike, period: int) -> pd.Series:
    """Simple moving average."""
    _validate_period(period)
    s = as_series(data, "sma")
    if s.empty:
        return s
    return s.rolling(window=period, min_periods=period).mean().rename(f"sma_{period}")


def ema_20(data: ArrayLike) -> pd.Series:
    return ema(data, 20)


def ema_50(data: ArrayLike) -> pd.Series:
    return ema(data, 50)


def ema_200(data: ArrayLike) -> pd.Series:
    return ema(data, 200)


def sma_200(data: ArrayLike) -> pd.Series:
    return sma(data, 200)


def adx(
    high: ArrayLike, low: ArrayLike, close: ArrayLike, period: int = 14
) -> pd.DataFrame:
    """Average Directional Index with +DI / -DI (Wilder).

    Returns a DataFrame with columns ``adx``, ``plus_di``, ``minus_di``.
    ADX measures trend *strength* (not direction); +DI vs -DI gives direction.
    """
    _validate_period(period)
    h = as_series(high, "high")
    l = as_series(low, "low")
    c = as_series(close, "close")
    idx = h.index
    if len(h) == 0:
        return pd.DataFrame(columns=["adx", "plus_di", "minus_di"])

    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=idx)
    minus_dm = pd.Series(minus_dm, index=idx)

    prev_close = c.shift(1)
    tr = pd.concat(
        [(h - l), (h - prev_close).abs(), (l - prev_close).abs()], axis=1
    ).max(axis=1)

    atr = rma(tr, period)
    plus_di = 100.0 * rma(plus_dm, period) / atr.replace(0.0, np.nan)
    minus_di = 100.0 * rma(minus_dm, period) / atr.replace(0.0, np.nan)

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx_line = rma(dx, period)

    return pd.DataFrame(
        {"adx": adx_line, "plus_di": plus_di, "minus_di": minus_di}, index=idx
    )
