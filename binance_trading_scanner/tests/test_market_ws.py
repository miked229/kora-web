"""Phase 7 tests: WebSocket closed-candle handling and the Testnet client.

Offline: the WS message logic is pure; the Testnet client is exercised through
an httpx MockTransport (no network, no real credentials).
"""
from __future__ import annotations

import httpx
import pytest

from binance.testnet_client import TESTNET_BASE, BinanceTestnetClient
from binance.websocket import KlineStreamHandler, kline_stream_names, parse_kline_message
from core.enums import Timeframe
from core.exceptions import ConfigurationError


def _kline_msg(open_time, closed, symbol="BTCUSDT", interval="15m"):
    return {"e": "kline", "E": open_time + 5, "s": symbol,
            "k": {"t": open_time, "T": open_time + 899_999, "s": symbol, "i": interval,
                  "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "q": "15", "n": 5, "x": closed}}


# ---- WebSocket handler ---------------------------------------------------

def test_stream_names():
    assert kline_stream_names(["BTCUSDT", "ETHUSDT"], Timeframe.M15) == \
        ["btcusdt@kline_15m", "ethusdt@kline_15m"]


def test_open_candle_is_ignored():
    h = KlineStreamHandler()
    assert h.handle(_kline_msg(1000, closed=False)) is None


def test_closed_candle_emitted_once():
    seen = []
    h = KlineStreamHandler(on_closed_candle=lambda s, i, c: seen.append((s, i, c.open_time)))
    c = h.handle(_kline_msg(1000, closed=True))
    assert c is not None and c.open_time == 1000 and c.is_closed
    assert seen == [("BTCUSDT", "15m", 1000)]
    # duplicate closed candle for the same open_time is suppressed
    assert h.handle(_kline_msg(1000, closed=True)) is None
    assert len(seen) == 1


def test_distinct_candles_and_combined_envelope():
    h = KlineStreamHandler()
    assert h.handle(_kline_msg(1000, True)) is not None
    assert h.handle(_kline_msg(900_000, True)) is not None
    # combined-stream envelope {stream, data}
    assert h.handle({"stream": "btcusdt@kline_15m", "data": _kline_msg(1_800_000, True)}) is not None


def test_parse_non_kline_returns_none():
    assert parse_kline_message({"e": "trade", "s": "BTCUSDT"}) is None


# ---- Testnet client ------------------------------------------------------

def test_testnet_client_refuses_mainnet_host():
    with pytest.raises(ConfigurationError):
        BinanceTestnetClient("k", "s", base_url="https://api.binance.com")


def test_testnet_client_requires_credentials():
    with pytest.raises(ConfigurationError):
        BinanceTestnetClient("", "", base_url=TESTNET_BASE)


def test_testnet_order_is_signed_and_routed():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["query"] = req.url.query.decode()
        captured["apikey_header"] = req.headers.get("X-MBX-APIKEY")
        if req.url.path == "/api/v3/order":
            return httpx.Response(200, json={"symbol": "BTCUSDT", "status": "FILLED",
                                             "executedQty": "0.001",
                                             "fills": [{"qty": "0.001", "price": "60000", "commission": "0.06"}]})
        return httpx.Response(404, json={"msg": "x"})

    tc = BinanceTestnetClient("KEY", "SECRET",
                              client=httpx.Client(transport=httpx.MockTransport(handler)))
    resp = tc.new_market_order("BTCUSDT", "BUY", 0.001, "cid-123")
    assert resp["status"] == "FILLED"
    assert "testnet.binance.vision" in captured["url"]      # testnet only
    assert "signature=" in captured["query"]                # signed
    assert captured["apikey_header"] == "KEY"
    # the secret is never placed in the URL/query
    assert "SECRET" not in captured["query"]
    assert tc.environment == "TESTNET"
