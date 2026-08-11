"""Volatility indicators: ATR 14, Bollinger Bands, Bollinger Band Width.

Causal by construction. Warm-up periods are NaN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import ArrayLike, _validate_period, as_series, rma


def true_range(high: ArrayLike, low: ArrayLike, close: ArrayLike) -> pd.Series:
    """Wilder's True Range: max(H-L, |H-Cprev|, |L-Cprev|)."""
    h = as_series(high, "high")
    l = as_series(low, "low")
    c = as_series(close, "close")
    if h.empty:
        return h.rename("true_range")
    prev_close = c.shift(1)
    tr = pd.concat(
        [(h - l), (h - prev_close).abs(), (l - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rename("true_range")


def atr(
    high: ArrayLike, low: ArrayLike, close: ArrayLike, period: int = 14
) -> pd.Series:
    """Average True Range (Wilder smoothing of True Range)."""
    _validate_period(period)
    tr = true_range(high, low, close)
    if tr.empty:
        return tr.rename("atr")
    return rma(tr, period).rename("atr")


def bollinger_bands(
    data: ArrayLike, period: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    """Bollinger Bands: middle SMA with +/- ``num_std`` population std bands.

    Returns columns ``middle``, ``upper``, ``lower``.
    """
    _validate_period(period)
    if num_std <= 0:
        raise ValueError("num_std must be positive")
    s = as_series(data, "close")
    if s.empty:
        return pd.DataFrame(columns=["middle", "upper", "lower"])

    middle = s.rolling(window=period, min_periods=period).mean()
    # Population std (ddof=0) is the conventional Bollinger definition.
    std = s.rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return pd.DataFrame(
        {"middle": middle, "upper": upper, "lower": lower}, index=s.index
    )


def bollinger_band_width(
    data: ArrayLike, period: int = 20, num_std: float = 2.0
) -> pd.Series:
    """Bollinger Band Width = (upper - lower) / middle.

    A normalised measure of volatility; low values indicate a squeeze.
    """
    bb = bollinger_bands(data, period, num_std)
    if bb.empty:
        return pd.Series(dtype="float64", name="bb_width")
    width = (bb["upper"] - bb["lower"]) / bb["middle"].replace(0.0, np.nan)
    return width.rename("bb_width")
