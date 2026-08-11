"""Phase 4 tests: dashboard service, page logic, and a headless app smoke.

The service/page logic tests are fully offline (demo source needs no network;
the live path is exercised through an httpx MockTransport). The AppTest smoke
runs the real Streamlit script and asserts every page renders without raising.
"""
from __future__ import annotations

import os

import httpx
import pytest

from binance.client import BinanceRESTClient
from core.enums import SignalType, Timeframe
from dashboard.chart import build_chart
from dashboard.demo_data import demo_klines_df
from dashboard.scanner import build_scanner_table
from dashboard.service import DEMO, LIVE, LIVE_UNAVAILABLE, Analysis, DashboardService

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
TF = Timeframe.H1


@pytest.fixture
def service():
    return DashboardService()


# ---- demo data -----------------------------------------------------------

def test_demo_scan_all_ok_and_varied(service):
    res = service.scan(SYMS, TF, DEMO)
    assert len(res) == 5
    assert all(a.ok for a in res)                       # nothing errors on demo
    dirs = {a.symbol: a.signal.direction for a in res}
    assert dirs["BTCUSDT"] is SignalType.LONG           # a clean LONG to demo the plan
    assert any(d is not SignalType.LONG for d in dirs.values())  # and variety


def test_demo_is_deterministic():
    a = DashboardService().get_analysis("BTCUSDT", TF, DEMO)
    b = DashboardService().get_analysis("BTCUSDT", TF, DEMO)
    assert a.signal.raw_score == b.signal.raw_score
    assert a.price == b.price


def test_demo_df_has_pipeline_columns():
    df = demo_klines_df("BTCUSDT", TF, n=260)
    for col in ("open", "high", "low", "close", "volume", "close_time"):
        assert col in df.columns
    assert len(df) == 260
    assert (df["high"] >= df["close"]).all()
    assert (df["low"] <= df["close"]).all()


# ---- metrics / scanner ---------------------------------------------------

def test_metrics_row_has_all_required_fields(service):
    a = service.get_analysis("BTCUSDT", TF, DEMO)
    m = service.metrics_row(a)
    for k in ["Symbol", "Price", "24h %", "Trend", "Structure", "RSI", "ADX",
              "RVOL", "Score", "Raw Score", "Signal", "Setup", "Entry", "Stop",
              "TP1", "TP2", "R:R"]:
        assert k in m


def test_scanner_table_sorted_by_score_desc(service):
    df = build_scanner_table(service, SYMS, TF, DEMO)
    assert list(df.columns)[0] == "Symbol"
    scores = [s for s in df["Score"].tolist() if s is not None]
    assert scores == sorted(scores, reverse=True)
    assert len(df) == len(SYMS)


# ---- error isolation (one symbol must not break the scan) ----------------

def test_scan_isolates_symbol_errors(monkeypatch, service):
    orig = service._load_df

    def boom(symbol, tf, source, limit):
        if symbol == "BOOM":
            raise RuntimeError("kaboom")
        return orig(symbol, tf, source, limit)

    monkeypatch.setattr(service, "_load_df", boom)
    res = service.scan(["BTCUSDT", "BOOM", "ETHUSDT"], TF, DEMO)
    assert res[0].ok and res[2].ok
    assert not res[1].ok and "kaboom" in res[1].error


# ---- live availability ---------------------------------------------------

def _mock_client(handler, max_retries=0):
    return BinanceRESTClient("https://mock",
                             client=httpx.Client(transport=httpx.MockTransport(handler)),
                             max_retries=max_retries)


def test_live_unavailable_is_reported():
    def handler(req):
        raise httpx.ConnectError("blocked")
    svc = DashboardService(client=_mock_client(handler))
    assert svc.probe_live() is False
    a = svc.get_analysis("BTCUSDT", TF, LIVE)
    assert a.error == LIVE_UNAVAILABLE
    assert not a.ok


def test_live_path_with_mock_client():
    rows = _klines_rows("BTCUSDT", 260)

    def handler(req):
        p = req.url.path
        if p == "/api/v3/ping":
            return httpx.Response(200, json={})
        if p == "/api/v3/klines":
            return httpx.Response(200, json=rows)
        if p == "/api/v3/ticker/24hr":
            return httpx.Response(200, json={
                "symbol": "BTCUSDT", "lastPrice": "123.4", "priceChangePercent": "1.5",
                "volume": "10", "quoteVolume": "1000", "highPrice": "130",
                "lowPrice": "120", "closeTime": rows[-1][6],
            })
        return httpx.Response(404, json={"msg": "not found"})

    svc = DashboardService(client=_mock_client(handler))
    assert svc.probe_live() is True
    a = svc.get_analysis("BTCUSDT", TF, LIVE)
    assert a.ok and a.source == LIVE
    assert a.signal is not None
    assert a.price == pytest.approx(123.4)


def _klines_rows(symbol, n):
    df = demo_klines_df(symbol, TF, n)
    rows = []
    for _, r in df.iterrows():
        rows.append([
            int(r["open_time"]), f"{r['open']}", f"{r['high']}", f"{r['low']}",
            f"{r['close']}", f"{r['volume']}", int(r["close_time"]),
            f"{r['quote_volume']}", int(r["trades"]), "0", "0", "0",
        ])
    return rows


# ---- chart ---------------------------------------------------------------

def test_build_chart_has_overlays(service):
    a = service.get_analysis("BTCUSDT", TF, DEMO)   # BTC is LONG -> plan lines
    fig = build_chart(a)
    names = [t.name for t in fig.data]
    assert "Price" in names
    for ma in ("EMA20", "EMA50", "EMA200", "VWAP"):
        assert ma in names
    assert len(fig.layout.shapes) >= 3   # support/resistance + entry/stop/tp hlines


def test_build_chart_handles_empty_analysis():
    a = Analysis("BTCUSDT", TF, DEMO, df=None, snapshot=None, signal=None)
    fig = build_chart(a)
    assert len(fig.data) == 0            # empty figure, no crash


# ---- headless Streamlit app smoke ---------------------------------------

def _app():
    from streamlit.testing.v1 import AppTest
    app_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")
    return AppTest.from_file(app_path, default_timeout=60)


def test_app_renders_overview():
    at = _app().run()
    assert not at.exception
    assert at.title
    assert "Binance Trading Scanner" in at.title[0].value


def test_app_all_pages_render():
    at = _app().run()
    assert not at.exception
    for page in ["Scanner", "Chart", "Signal Details", "Settings", "Overview"]:
        at.radio(key="page_radio").set_value(page).run()
        assert not at.exception, f"exception rendering page {page}"
