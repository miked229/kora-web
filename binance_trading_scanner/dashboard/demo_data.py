"""Deterministic synthetic market data for the dashboard's DEMO source.

Used only when live Binance data is unavailable (or the user picks the DEMO
source) so the interface can be exercised end-to-end without a network. The
output DataFrame has the same columns as the live pipeline
(``binance.market_data.candles_to_df`` / the REST kline layout), so the signal
engine and charts treat demo and live data identically — no separate code path.

The prices are built from normalised shapes (on a ~100 level) then scaled by the
symbol's base price. Because every indicator and the signal decision are
scale-invariant, scaling changes the numbers on screen but not the analysis, and
the result is fully deterministic (no RNG) so tests are stable.

This is clearly-labelled fake data. It is NOT a market simulation and must never
be presented as real prices.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.enums import Timeframe

# Anchor demo candles to a fixed epoch so output is fully deterministic.
_ANCHOR_MS = 1_704_067_200_000  # 2024-01-01T00:00:00Z

# Per-symbol: (base_price, regime, vol_base). Regimes give the UI a realistic
# spread of outcomes (a clean LONG, ranges, a downtrend, and choppy NO_TRADEs).
_PROFILES = {
    "BTCUSDT": (61000.0, "bull_strong", 1200.0),
    "ETHUSDT": (3000.0, "bull_soft", 9000.0),
    "SOLUSDT": (150.0, "range", 300000.0),
    "BNBUSDT": (560.0, "bear", 15000.0),
    "XRPUSDT": (0.52, "chop", 5_000000.0),
}
_DEFAULT_PROFILE = (100.0, "chop", 1000.0)


def _normalised(regime: str, n: int) -> np.ndarray:
    """Return an OHLC-agnostic price level (~100) for a regime."""
    i = np.arange(n, dtype="float64")
    two_pi = 2.0 * np.pi
    if regime == "bull_strong":
        return 100.0 + 0.55 * i + 3.0 * np.sin(two_pi * i / 20)
    if regime == "bull_soft":
        return 100.0 + 0.45 * i + 3.0 * np.sin(two_pi * i / 24)
    if regime == "range":
        return 100.0 + 4.0 * np.sin(two_pi * i / 24)
    if regime == "bear":
        return 250.0 - 0.5 * i + 3.0 * np.sin(two_pi * i / 20)
    # chop: mild drift with two oscillations (choppy, mostly NO_TRADE)
    return 100.0 + 0.15 * i + 5.0 * np.sin(two_pi * i / 26) + 1.2 * np.sin(two_pi * i / 7)


def demo_klines_df(symbol: str, timeframe: Timeframe, n: int = 300) -> pd.DataFrame:
    """Build a deterministic OHLCV DataFrame for ``symbol`` / ``timeframe``."""
    base, regime, vol_base = _PROFILES.get(symbol.upper(), _DEFAULT_PROFILE)
    norm = _normalised(regime, n)
    close = base / 100.0 * norm

    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]

    # Wick derived from CLOSE only: deriving it from max(open, close) would tie
    # high[i+1] to high[i] one bar after every peak and suppress swing pivots.
    high = close * 1.0025
    low = close * 0.9975

    change = np.abs(np.diff(close, prepend=close[0])) / np.maximum(close, 1e-9)
    vol = vol_base * (1.0 + 5.0 * change)
    vol = np.where(close >= open_, vol * 1.2, vol * 0.9)

    step = timeframe.milliseconds
    open_time = (_ANCHOR_MS + np.arange(n) * step).astype("int64")
    close_time = open_time + step - 1

    return pd.DataFrame({
        "open_time": open_time,
        "open": open_, "high": high, "low": low, "close": close,
        "volume": vol, "close_time": close_time,
        "quote_volume": vol * close,
        "trades": np.maximum(vol / 10.0, 1).astype("int64"),
        "is_closed": True,
    })
