"""Phase 1 tests: REST client, market-data parsing/validation, exchange info.

Offline only — the client is driven by an httpx MockTransport.
"""
from __future__ import annotations

import httpx
import pytest

from binance.client import BinanceRESTClient
from binance.exchange_info import ExchangeInfoService
from binance.market_data import MarketDataService, candles_to_df
from core.enums import SymbolStatus, Timeframe
from core.exceptions import (
    BinanceAPIError,
    DataValidationError,
    InvalidSymbolError,
    RateLimitError,
)
from core.models import BookTicker, Candle, SymbolInfo, Ticker
from tests.conftest import make_kline


# ---- models --------------------------------------------------------------

def test_candle_from_kline_roundtrip():
    row = make_kline(1_700_000_000_000, 100, 101, 99, 100.5, 12, 60_000)
    c = Candle.from_binance_kline(row)
    assert c.open == 100 and c.close == 100.5
    assert c.high == 101 and c.low == 99
    assert c.is_closed is True
    assert c.open_dt.year == 2023


def test_candle_rejects_inconsistent_ohlc():
    # high below the max of open/close -> invalid
    bad = [1_700_000_000_000, "100", "100", "99", "105", "1",
           1_700_000_059_999, "0", 1, "0", "0", "0"]
    with pytest.raises(ValueError):
        Candle.from_binance_kline(bad)


def test_bookticker_spread():
    bt = BookTicker(symbol="BTCUSDT", bid_price=100.0, bid_qty=1,
                    ask_price=101.0, ask_qty=1)
    assert bt.spread == pytest.approx(1.0)
    assert bt.mid_price == pytest.approx(100.5)
    assert bt.spread_pct == pytest.approx(1 / 100.5 * 100)


def test_ticker_parsing():
    t = Ticker.from_binance_24hr({
        "symbol": "BTCUSDT", "lastPrice": "50000.0",
        "priceChangePercent": "2.5", "volume": "10", "quoteVolume": "500000",
        "highPrice": "51000", "lowPrice": "49000", "closeTime": 1_700_000_000_000,
    })
    assert t.symbol == "BTCUSDT"
    assert t.last_price == 50000.0
    assert t.price_change_pct == 2.5


# ---- client behaviour ----------------------------------------------------

def test_client_ping_and_klines(mock_client_factory, sample_klines):
    client = mock_client_factory({
        "/api/v3/ping": {},
        "/api/v3/klines": sample_klines,
    })
    assert client.ping() is True
    rows = client.klines("BTCUSDT", "1m", limit=20)
    assert len(rows) == 20


def test_client_raises_api_error_on_bad_symbol(mock_client_factory):
    # 404 route returns a Binance-style error body
    client = mock_client_factory({})
    with pytest.raises(BinanceAPIError) as ei:
        client.ticker_price("NOSUCH")
    assert ei.value.status_code == 404


def test_client_retries_then_raises_rate_limit():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"msg": "slow down"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = BinanceRESTClient("https://mock", client=http, max_retries=2)
    with pytest.raises(RateLimitError):
        client.ping()
    assert calls["n"] == 3  # initial + 2 retries


def test_client_retries_5xx_then_succeeds():
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] < 2:
            return httpx.Response(503, json={"msg": "unavailable"})
        return httpx.Response(200, json={"serverTime": 123})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = BinanceRESTClient("https://mock", client=http, max_retries=3)
    assert client.server_time() == 123
    assert state["n"] == 2


# ---- market data service -------------------------------------------------

def test_market_data_klines_validated(mock_client_factory, sample_klines):
    client = mock_client_factory({"/api/v3/klines": sample_klines})
    market = MarketDataService(client)
    candles = market.get_klines("BTCUSDT", Timeframe.M1, limit=20)
    assert len(candles) == 20
    assert all(isinstance(c, Candle) for c in candles)
    # strictly increasing open times
    assert all(candles[i].open_time < candles[i + 1].open_time for i in range(len(candles) - 1))


def test_market_data_detects_duplicate(mock_client_factory, sample_klines):
    dup = sample_klines + [sample_klines[-1]]  # repeat last row
    client = mock_client_factory({"/api/v3/klines": dup})
    market = MarketDataService(client)
    with pytest.raises(DataValidationError):
        market.get_klines("BTCUSDT", Timeframe.M1, limit=30)


def test_market_data_gap_is_warned_not_fatal(mock_client_factory, sample_klines, caplog):
    gapped = sample_klines[:5] + sample_klines[7:]  # drop two candles
    client = mock_client_factory({"/api/v3/klines": gapped})
    market = MarketDataService(client)
    candles = market.get_klines("BTCUSDT", Timeframe.M1, limit=30)
    assert len(candles) == len(gapped)  # gap tolerated
    assert any("gap" in r.message.lower() for r in caplog.records)


def test_empty_klines(mock_client_factory):
    client = mock_client_factory({"/api/v3/klines": []})
    market = MarketDataService(client)
    assert market.get_klines("BTCUSDT", Timeframe.M1) == []
    df = candles_to_df([])
    assert df.empty


def test_candles_to_df(mock_client_factory, sample_klines):
    client = mock_client_factory({"/api/v3/klines": sample_klines})
    market = MarketDataService(client)
    df = market.get_klines_df("BTCUSDT", Timeframe.M1, limit=20, closed_only=False)
    assert list(df.columns).count("close") == 1
    assert len(df) == 20
    assert df.index.tz is not None  # UTC-aware index


# ---- exchange info -------------------------------------------------------

def test_exchange_info_validation(mock_client_factory, sample_exchange_info):
    client = mock_client_factory({"/api/v3/exchangeInfo": sample_exchange_info})
    svc = ExchangeInfoService(client)
    svc.load(force=True)

    info = svc.require("BTCUSDT")
    assert isinstance(info, SymbolInfo)
    assert info.status == SymbolStatus.TRADING
    assert info.is_trading
    assert info.filters.tick_size == pytest.approx(0.01)
    assert info.filters.min_notional == pytest.approx(5.0)

    # FAKEUSDT exists but is on BREAK -> not valid for trading
    assert svc.is_valid("FAKEUSDT") is False
    valid, invalid = svc.validate_symbols(["BTCUSDT", "FAKEUSDT", "ZZZUSDT"])
    assert valid == ["BTCUSDT"]
    assert set(invalid) == {"FAKEUSDT", "ZZZUSDT"}

    with pytest.raises(InvalidSymbolError):
        svc.require("ZZZUSDT")


# ---- timeframe enum ------------------------------------------------------

def test_timeframe_milliseconds():
    assert Timeframe.M1.milliseconds == 60_000
    assert Timeframe.H1.milliseconds == 3_600_000
    assert Timeframe.D1.milliseconds == 86_400_000
    assert Timeframe.from_value("15m") is Timeframe.M15
