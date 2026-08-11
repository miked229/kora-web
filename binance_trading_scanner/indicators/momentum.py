"""Momentum indicators: RSI 14, MACD, Stochastic RSI.

Causal by construction. Warm-up periods are NaN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import ArrayLike, _validate_period, as_series, rma
from .trend import ema


def rsi(data: ArrayLike, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder smoothing), range 0..100.

    Convention: a flat series (no moves) yields NaN then neutral; an all-up
    series approaches 100, an all-down series approaches 0.
    """
    _validate_period(period)
    s = as_series(data, "close")
    if s.empty:
        return s.rename("rsi")

    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = rma(gain, period)
    avg_loss = rma(loss, period)

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # When average loss is zero (pure uptrend), RSI is defined as 100.
    out = out.where(avg_loss != 0.0, 100.0)
    # When both are zero (flat), leave as NaN (undefined momentum).
    out = out.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), np.nan)
    return out.rename("rsi")


def macd(
    data: ArrayLike, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """Moving Average Convergence Divergence.

    Returns columns ``macd`` (fast EMA - slow EMA), ``signal`` (EMA of macd)
    and ``hist`` (macd - signal).
    """
    _validate_period(fast)
    _validate_period(slow)
    _validate_period(signal)
    if fast >= slow:
        raise ValueError("fast period must be < slow period")
    s = as_series(data, "close")
    if s.empty:
        return pd.DataFrame(columns=["macd", "signal", "hist"])

    macd_line = ema(s, fast) - ema(s, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": hist}, index=s.index
    )


def stoch_rsi(
    data: ArrayLike, period: int = 14, k: int = 3, d: int = 3
) -> pd.DataFrame:
    """Stochastic RSI, range 0..100.

    Applies the stochastic oscillator formula to the RSI series, then smooths
    into %K and %D lines. Returns columns ``stoch_rsi``, ``k``, ``d``.
    """
    _validate_period(period)
    _validate_period(k)
    _validate_period(d)
    s = as_series(data, "close")
    if s.empty:
        return pd.DataFrame(columns=["stoch_rsi", "k", "d"])

    r = rsi(s, period)
    lowest = r.rolling(window=period, min_periods=period).min()
    highest = r.rolling(window=period, min_periods=period).max()
    rng = (highest - lowest).replace(0.0, np.nan)
    stoch = 100.0 * (r - lowest) / rng
    k_line = stoch.rolling(window=k, min_periods=k).mean()
    d_line = k_line.rolling(window=d, min_periods=d).mean()
    return pd.DataFrame(
        {"stoch_rsi": stoch, "k": k_line, "d": d_line}, index=s.index
    )
