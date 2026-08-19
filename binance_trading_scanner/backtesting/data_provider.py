"""Validation data provider: REAL Binance history when reachable, else SYNTHETIC.

The validation pipeline (Phase 9) must run on **real historical Binance data when
available** and fall back to **clearly-labelled synthetic data** only when the
network is unreachable. This module never evades a network block: it *attempts*
the real public REST endpoint and, on any failure, returns deterministic
synthetic candles with ``source="SYNTHETIC"`` so every downstream report can say
exactly what it was computed on.

Public market data needs no credentials. Nothing here places an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from core.enums import Timeframe
from core.logger import get_logger

logger = get_logger("backtesting.data_provider")

_MAX_PER_REQUEST = 1000


class RealDataUnavailable(RuntimeError):
    """Raised in REAL STRICT mode when real Binance history cannot be obtained.

    In strict mode there is NO synthetic fallback: the caller must stop and report
    ``REAL DATA VALIDATION FAILED`` rather than present synthetic data as real.
    """


@dataclass
class MarketDataResult:
    df: pd.DataFrame
    source: str                 # "BINANCE" | "SYNTHETIC"
    symbol: str
    timeframe: Timeframe
    note: str = ""

    @property
    def is_real(self) -> bool:
        return self.source == "BINANCE"


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def load_history(
    symbol: str,
    timeframe: Timeframe,
    bars: int,
    *,
    prefer_real: bool = True,
    market=None,
    seed: Optional[int] = None,
) -> MarketDataResult:
    """Return ``bars`` closed candles for (symbol, timeframe).

    Tries REAL Binance public klines first (when ``prefer_real``); on ANY failure
    — including a network block — falls back to deterministic synthetic candles
    and records why in ``note``. The synthetic path is seeded from the symbol so
    each symbol gets a distinct but reproducible multi-regime path.
    """
    note = ""
    if prefer_real:
        try:
            df = _fetch_real(symbol, timeframe, bars, market)
            if len(df) >= max(bars // 2, 50):
                return MarketDataResult(df, "BINANCE", symbol, timeframe,
                                        note=f"{len(df)} real closed candles")
            note = f"only {len(df)} real candles returned; using synthetic"
        except Exception as exc:   # network block, timeout, validation, ...
            note = f"real data unavailable ({type(exc).__name__}: {exc}); using synthetic"
            logger.warning("real data unavailable for %s %s: %s", symbol, timeframe.value, exc)

    if seed is None:
        seed = abs(hash((symbol, timeframe.value))) % (2**32)
    df = synthetic_history(bars, timeframe, seed=seed)
    return MarketDataResult(df, "SYNTHETIC", symbol, timeframe,
                            note=note or "synthetic (prefer_real disabled)")


def load_real_history(
    symbol: str,
    timeframe: Timeframe,
    bars: int,
    *,
    market=None,
    min_bars: Optional[int] = None,
) -> MarketDataResult:
    """REAL STRICT loader — real Binance history or ``RealDataUnavailable``.

    There is NO synthetic fallback here. If the public endpoint is unreachable
    (e.g. blocked by egress policy → 403) or returns fewer than ``min_bars``
    closed candles, this raises ``RealDataUnavailable`` so the caller stops and
    reports ``REAL DATA VALIDATION FAILED`` instead of presenting synthetic data.
    """
    need = min_bars if min_bars is not None else max(bars // 2, 600)
    try:
        df = _fetch_real(symbol, timeframe, bars, market)
    except Exception as exc:   # connection block, timeout, validation, ...
        raise RealDataUnavailable(
            f"{symbol} {timeframe.value}: could not reach Binance "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    if len(df) < need:
        raise RealDataUnavailable(
            f"{symbol} {timeframe.value}: only {len(df)} real closed candles "
            f"returned (need >= {need})"
        )
    return MarketDataResult(df, "BINANCE", symbol, timeframe,
                            note=f"{len(df)} real closed candles from Binance")


# --------------------------------------------------------------------------
# Real Binance history (paginated backwards)
# --------------------------------------------------------------------------

def _fetch_real(symbol: str, timeframe: Timeframe, bars: int, market=None) -> pd.DataFrame:
    """Fetch ``bars`` closed candles from the public REST API, paging backwards.

    Raises on any connectivity/validation problem so the caller can fall back.
    """
    if market is None:
        from binance.client import BinanceRESTClient
        from binance.market_data import MarketDataService
        market = MarketDataService(BinanceRESTClient())

    from binance.market_data import candles_to_df

    collected: List = []
    end_time: Optional[int] = None
    guard = 0
    need = bars + 5   # a few extra so we can drop any unclosed tail
    while len(collected) < need and guard < 50:
        guard += 1
        batch = market.get_klines(symbol, timeframe, limit=_MAX_PER_REQUEST, end_time=end_time)
        if not batch:
            break
        collected = list(batch) + collected
        end_time = int(batch[0].open_time) - 1
        if len(batch) < _MAX_PER_REQUEST:
            break

    closed = [c for c in collected if c.is_closed]
    # de-duplicate by open_time, keep chronological order
    seen = set()
    uniq = []
    for c in sorted(closed, key=lambda x: x.open_time):
        if c.open_time not in seen:
            seen.add(c.open_time)
            uniq.append(c)
    df = candles_to_df(uniq).reset_index(drop=True)
    return df.tail(bars).reset_index(drop=True)


# --------------------------------------------------------------------------
# Synthetic multi-regime history (deterministic)
# --------------------------------------------------------------------------

def _ohlc_from_close(close: np.ndarray, timeframe: Timeframe, *, wick: float,
                     vol: np.ndarray, start: int = 1_500_000_000_000) -> pd.DataFrame:
    """Build a VALID-OHLC DataFrame from a close path (high>=open/close, etc.)."""
    step = timeframe.milliseconds
    n = len(close)
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    # Wick is derived from CLOSE (not max(open,close)); otherwise high[i+1] ties
    # high[i] one bar after every peak (open[i+1]==close[i]) and swing pivots are
    # suppressed. We still include the open so OHLC stays valid.
    high = np.maximum(open_, close * (1.0 + wick))
    low = np.minimum(open_, close * (1.0 - wick))
    ot = (start + np.arange(n) * step).astype("int64")
    ct = ot + step - 1
    return pd.DataFrame({
        "open_time": ot, "open": open_, "high": high, "low": low, "close": close,
        "volume": vol, "close_time": ct, "quote_volume": vol * close,
        "trades": np.maximum(vol / 10.0, 1).astype("int64"), "is_closed": True,
    })


def synthetic_history(bars: int, timeframe: Timeframe, *, seed: int = 7,
                      base: float = 100.0) -> pd.DataFrame:
    """Deterministic multi-regime price path: uptrend → range → downtrend →
    volatile recovery, with swings + gaussian noise.

    Deliberately NOT a one-directional ramp: it gives both LONG and SHORT genuine
    opportunities AND losing stretches, so validation is not trivially positive.
    """
    rng = np.random.default_rng(seed)
    segs = max(bars // 4, 30)
    i = np.arange(segs, dtype="float64")

    up = base + 0.45 * i + 3.0 * np.sin(2 * np.pi * i / 20)
    top = float(up[-1])
    rng_seg = top + 4.0 * np.sin(2 * np.pi * i / 16)          # sideways
    down = top - 0.5 * i + 3.0 * np.sin(2 * np.pi * i / 20)   # downtrend
    bottom = float(down[-1])
    recover = bottom + 0.35 * i + 6.0 * np.sin(2 * np.pi * i / 12)  # choppy recovery

    path = np.concatenate([up, rng_seg, down, recover])[:bars]
    if len(path) < bars:   # pad if rounding left us short
        path = np.concatenate([path, np.full(bars - len(path), path[-1])])
    # Multiplicative noise keeps prices positive and adds realistic wobble.
    noise = rng.normal(0.0, 0.004, size=bars)
    close = path * (1.0 + noise)
    close = np.maximum(close, 1e-6)

    vol = rng.normal(1000.0, 120.0, size=bars)
    vol = np.clip(vol, 100.0, None)
    return _ohlc_from_close(close, timeframe, wick=0.004, vol=vol)
