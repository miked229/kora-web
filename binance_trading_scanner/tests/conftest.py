"""Shared test fixtures.

All fixtures are offline: no test in this suite touches the network. The Binance
REST client is exercised through an httpx ``MockTransport`` so parsing, retry
and validation logic can be verified deterministically.
"""
from __future__ import annotations

import time

import httpx
import numpy as np
import pandas as pd
import pytest

from binance.client import BinanceRESTClient


def make_kline(open_time: int, o, h, l, c, v, step_ms: int, *, trades: int = 100):
    """Build a raw Binance kline row (12 fields)."""
    close_time = open_time + step_ms - 1
    return [
        open_time, f"{o}", f"{h}", f"{l}", f"{c}", f"{v}",
        close_time, f"{float(v) * float(c):.8f}", trades,
        "0", "0", "0",
    ]


@pytest.fixture
def sample_klines():
    """20 consecutive 1m candles, well-formed and gap-free (all closed)."""
    step = 60_000
    start = 1_700_000_000_000  # fixed past epoch so is_closed is always True
    rows = []
    price = 100.0
    for i in range(20):
        o = price
        c = price + (0.5 if i % 2 == 0 else -0.3)
        h = max(o, c) + 0.4
        l = min(o, c) - 0.4
        rows.append(make_kline(start + i * step, o, h, l, c, 10 + i, step))
        price = c
    return rows


def _bt_ohlc(close, *, step=None, start=1_600_000_000_000, wick=0.003, vol_base=1000.0, vol=None):
    """Build a VALID-OHLC DataFrame for backtester tests (high>=open, low<=open).

    Wick is applied to close (not to max(open, close)) so swing pivots survive,
    but high/low still include the open so data-quality checks pass.
    """
    from core.enums import Timeframe
    step = step or Timeframe.H1.milliseconds
    close = np.asarray(close, dtype="float64")
    n = len(close)
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close * (1.0 + wick))
    low = np.minimum(open_, close * (1.0 - wick))
    if vol is None:
        vol = np.where(close >= open_, vol_base * 1.2, vol_base * 0.9)
    vol = np.asarray(vol, dtype="float64")
    ot = (start + np.arange(n) * step).astype("int64")
    ct = ot + step - 1
    return pd.DataFrame({
        "open_time": ot, "open": open_, "high": high, "low": low, "close": close,
        "volume": vol, "close_time": ct, "quote_volume": vol * close,
        "trades": np.maximum(vol / 10.0, 1).astype("int64"), "is_closed": True,
    })


def bt_bull(n=300, base=100.0, slope=0.55, amp=3.0, period=20, **kw):
    """Uptrend with swings -> reliably produces LONG signals."""
    i = np.arange(n, dtype="float64")
    return _bt_ohlc(base + slope * i + amp * np.sin(2 * np.pi * i / period), **kw)


def bt_bull_then_crash(n_bull=250, n_crash=25, base=100.0, drop=0.04, **kw):
    """Bull warmup that produces a LONG, then a sharp decline through any stop."""
    i = np.arange(n_bull, dtype="float64")
    bull = base + 0.55 * i + 3.0 * np.sin(2 * np.pi * i / 20)
    top = float(bull[-1])
    crash = top * (1.0 - drop) ** np.arange(1, n_crash + 1)
    return _bt_ohlc(np.concatenate([bull, crash]), **kw)


def bt_flat_range(n=300, base=100.0, amp=3.0, period=24, **kw):
    """Sideways oscillation -> no LONG setups -> no trades."""
    i = np.arange(n, dtype="float64")
    return _bt_ohlc(base + amp * np.sin(2 * np.pi * i / period), **kw)


def _handler_factory(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for prefix, response in routes.items():
            if path == prefix:
                body = response(request) if callable(response) else response
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={"code": -1121, "msg": "Not found"})
    return handler


@pytest.fixture
def mock_client_factory():
    """Return a factory that builds a BinanceRESTClient backed by mock routes."""
    def factory(routes: dict, **kwargs) -> BinanceRESTClient:
        transport = httpx.MockTransport(_handler_factory(routes))
        http = httpx.Client(transport=transport)
        return BinanceRESTClient("https://mock", client=http, max_retries=kwargs.get("max_retries", 2))
    return factory


# ==========================================================================
# Deterministic synthetic market scenarios (Phase 3 signal-engine tests)
# ==========================================================================

def _ohlc_df(close, *, vol=None, up_vol_boost=True, wick=0.004, start=1_600_000_000_000, step=3_600_000):
    """Build an OHLCV DataFrame from a close-price array.

    Opens follow the previous close; highs/lows add a small symmetric wick.
    Volume is constant unless ``vol`` given; up candles get a small boost.
    A ``close_time`` column gives the engine a deterministic timestamp.
    """
    close = np.asarray(close, dtype="float64")
    n = len(close)
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    # Wick is derived from CLOSE only. Deriving it from max(open, close) would
    # make high[i+1] tie high[i] one bar after every peak (because
    # open[i+1] == close[i]), which suppresses strict swing pivots.
    hi = close * (1.0 + wick)
    lo = close * (1.0 - wick)
    if vol is None:
        base = np.full(n, 1000.0)
        if up_vol_boost:
            base = np.where(close >= open_, 1400.0, 900.0)
        vol = base
    vol = np.asarray(vol, dtype="float64")
    open_time = np.arange(n) * step + start
    close_time = open_time + step - 1
    return pd.DataFrame({
        "open_time": open_time, "open": open_, "high": hi, "low": lo,
        "close": close, "volume": vol, "close_time": close_time,
    })


def scenario_strong_bull(n=260, slope=0.55, amp=3.0, period=20, base=100.0):
    """Rising trend with oscillation -> bullish structure (HH/HL)."""
    i = np.arange(n)
    close = base + slope * i + amp * np.sin(2 * np.pi * i / period)
    return _ohlc_df(close)


def scenario_strong_bear(n=260, slope=0.55, amp=3.0, period=20, base=250.0):
    """Falling trend with oscillation -> bearish structure (LH/LL)."""
    i = np.arange(n)
    close = base - slope * i + amp * np.sin(2 * np.pi * i / period)
    return _ohlc_df(close)


def scenario_range(n=260, amp=4.0, period=24, base=100.0):
    """Sideways oscillation -> range structure, neutral trend."""
    i = np.arange(n)
    close = base + amp * np.sin(2 * np.pi * i / period)
    return _ohlc_df(close)


def scenario_breakout(n=235, consol=230, amp=1.5, period=20, base=100.0, breakout_pct=0.08):
    """Long tight consolidation, then a short strong high-volume breakout.

    The breakout is only a few bars so the trailing volume baseline stays low
    and relative volume clears the confirmation threshold.
    """
    i = np.arange(consol)
    consol_close = base + amp * np.sin(2 * np.pi * i / period)
    top = float(np.max(consol_close))
    steps = n - consol
    breakout = np.linspace(top * 1.01, top * (1.0 + breakout_pct), steps)
    close = np.concatenate([consol_close, breakout])
    vol = np.concatenate([np.full(consol, 1000.0), np.full(steps, 3000.0)])
    return _ohlc_df(close, vol=vol)


def scenario_failed_breakout(n=245, consol=230, amp=1.5, period=20, base=100.0):
    """Consolidation with a spike that closes back inside the range."""
    i = np.arange(consol)
    consol_close = base + amp * np.sin(2 * np.pi * i / period)
    top = float(np.max(consol_close))
    steps = n - consol
    j = np.arange(steps - 1)
    tail = base + amp * np.sin(2 * np.pi * j / period)   # back inside the range
    close = np.concatenate([consol_close, [top * 1.09], tail])   # one spike bar, then inside
    vol = np.concatenate([np.full(consol, 1000.0), [2500.0], np.full(steps - 1, 1200.0)])
    return _ohlc_df(close, vol=vol)


def scenario_pullback(n=260, slope=0.35, amp=6.0, period=26, base=100.0):
    """Uptrend with deeper oscillations so price periodically pulls back into
    the EMA20. A PULLBACK setup occurs at bar index 256 (deterministic)."""
    i = np.arange(n)
    close = base + slope * i + amp * np.sin(2 * np.pi * i / period)
    return _ohlc_df(close)


PULLBACK_BAR = 256   # deterministic index where scenario_pullback shows PULLBACK


def scenario_extreme_volatility(n=260, base=100.0):
    """Bullish drift but with very wide bars (ATR% > extreme threshold)."""
    i = np.arange(n)
    close = base + 0.5 * i + 25.0 * np.sin(2 * np.pi * i / 10)
    return _ohlc_df(close, wick=0.06)


@pytest.fixture
def sample_exchange_info():
    return {
        "timezone": "UTC",
        "serverTime": int(time.time() * 1000),
        "symbols": [
            {
                "symbol": "BTCUSDT", "status": "TRADING",
                "baseAsset": "BTC", "quoteAsset": "USDT",
                "baseAssetPrecision": 8, "quoteAssetPrecision": 8,
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.00001000",
                     "minQty": "0.00001000", "maxQty": "9000.00000000"},
                    {"filterType": "NOTIONAL", "minNotional": "5.00000000"},
                ],
            },
            {
                "symbol": "FAKEUSDT", "status": "BREAK",
                "baseAsset": "FAKE", "quoteAsset": "USDT",
                "baseAssetPrecision": 8, "quoteAssetPrecision": 8,
                "filters": [],
            },
        ],
    }
