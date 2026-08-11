"""Volume indicators: Volume SMA, Relative Volume, OBV, VWAP.

Causal by construction. Warm-up periods are NaN.

Note on VWAP: a true VWAP is anchored to a trading session. Working from a
rolling window of candles (not a session), this module offers a **cumulative**
VWAP (anchored to the first candle of the provided series) and a **rolling**
VWAP over a fixed window. Callers should use whichever matches their context and
must not treat these as an exchange session VWAP.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import ArrayLike, _validate_period, as_series


def volume_sma(volume: ArrayLike, period: int = 20) -> pd.Series:
    """Simple moving average of volume."""
    _validate_period(period)
    v = as_series(volume, "volume")
    if v.empty:
        return v.rename("volume_sma")
    return v.rolling(window=period, min_periods=period).mean().rename("volume_sma")


def relative_volume(volume: ArrayLike, period: int = 20) -> pd.Series:
    """Relative volume = current volume / average volume over ``period``.

    ~1.0 means average; >1.0 means above-average participation. The average
    excludes the current bar (shifted) so a spike is measured against its
    baseline, not diluted by itself.
    """
    _validate_period(period)
    v = as_series(volume, "volume")
    if v.empty:
        return v.rename("relative_volume")
    baseline = v.shift(1).rolling(window=period, min_periods=period).mean()
    rvol = v / baseline.replace(0.0, np.nan)
    return rvol.rename("relative_volume")


def obv(close: ArrayLike, volume: ArrayLike) -> pd.Series:
    """On-Balance Volume.

    Adds volume on up-closes, subtracts on down-closes, unchanged on flat.
    Starts at 0 on the first bar.
    """
    c = as_series(close, "close")
    v = as_series(volume, "volume")
    if c.empty:
        return c.rename("obv")
    direction = np.sign(c.diff().fillna(0.0))
    signed = (direction * v).fillna(0.0)
    return signed.cumsum().rename("obv")


def vwap(
    high: ArrayLike, low: ArrayLike, close: ArrayLike, volume: ArrayLike
) -> pd.Series:
    """Cumulative VWAP anchored to the first candle of the series.

    Uses the typical price (H+L+C)/3 weighted by volume.
    """
    h = as_series(high, "high")
    l = as_series(low, "low")
    c = as_series(close, "close")
    v = as_series(volume, "volume")
    if c.empty:
        return c.rename("vwap")
    typical = (h + l + c) / 3.0
    cum_vol = v.cumsum().replace(0.0, np.nan)
    return (typical * v).cumsum().div(cum_vol).rename("vwap")


def rolling_vwap(
    high: ArrayLike, low: ArrayLike, close: ArrayLike, volume: ArrayLike, period: int = 20
) -> pd.Series:
    """VWAP over a trailing window of ``period`` candles."""
    _validate_period(period)
    h = as_series(high, "high")
    l = as_series(low, "low")
    c = as_series(close, "close")
    v = as_series(volume, "volume")
    if c.empty:
        return c.rename("rolling_vwap")
    typical = (h + l + c) / 3.0
    pv = (typical * v).rolling(window=period, min_periods=period).sum()
    vol = v.rolling(window=period, min_periods=period).sum().replace(0.0, np.nan)
    return (pv / vol).rename("rolling_vwap")
