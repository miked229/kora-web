"""Shared test fixtures.

All fixtures are offline: no test in this suite touches the network. The Binance
REST client is exercised through an httpx ``MockTransport`` so parsing, retry
and validation logic can be verified deterministically.
"""
from __future__ import annotations

import time

import httpx
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
