"""Phase 8: targeted tests for report output, testnet endpoints, kill-switch
labels, session guards and the demo-trader guard. Real behaviour, not filler."""
from __future__ import annotations

import httpx
import pytest

from backtesting import BacktestConfig, BacktestEngine
from backtesting.report import (
    drawdown_curve,
    equity_curve,
    format_report,
    signal_stats,
    summary_dict,
    trade_distribution,
)
from binance.testnet_client import TESTNET_BASE, BinanceTestnetClient
from core.enums import Timeframe
from core.exceptions import LiveTradingDisabledError
from trading import KillSwitch, TradingState
from trading.kill_switch import mode_indicator
from tests.conftest import bt_bull
from tests.test_hardening import _session

TF = Timeframe.H1


# ---- report -------------------------------------------------------------

def test_report_outputs():
    res = BacktestEngine(config=BacktestConfig(capital=10_000)).run(bt_bull(260), "BTCUSDT", TF)
    text = format_report(res)
    assert "BACKTEST SUMMARY" in text and "not advice" in text
    assert "profitable" not in text.lower() and "guaranteed" not in text.lower()
    s = summary_dict(res)
    assert s["Symbol"] == "BTCUSDT" and "Net Return %" in s
    dist = trade_distribution(res.trades)
    assert "r" in dist and "exit_reasons" in dist
    assert len(equity_curve(res)) == len(res.equity_curve)
    assert len(drawdown_curve(res)) == len(res.equity_curve)
    ss = signal_stats(res)
    assert ss["total_signals"] == len(res.signal_log)


def test_report_distribution_empty():
    assert trade_distribution([])["wins"] == 0


# ---- kill switch labels & transitions -----------------------------------

def test_mode_indicator_all_labels():
    assert mode_indicator(data_source="demo", state=TradingState.DISABLED) == "🟢 DEMO"
    assert mode_indicator(data_source="live", state=TradingState.DISABLED) == "🔵 LIVE DATA — NO ORDERS"
    assert mode_indicator(data_source="demo", state=TradingState.TESTNET) == "🟡 TESTNET"
    assert mode_indicator(data_source="live", state=TradingState.LIVE, live_enabled=True) == "🔴 LIVE TRADING"
    # LIVE state but not enabled must NOT show LIVE TRADING
    assert mode_indicator(data_source="live", state=TradingState.LIVE, live_enabled=False) != "🔴 LIVE TRADING"


def test_kill_switch_resume_and_set_state():
    ks = KillSwitch()
    ks.set_state(TradingState.TESTNET)
    assert ks.state is TradingState.TESTNET and ks.allow_new_orders()
    ks.emergency_stop("x")
    assert not ks.allow_new_orders()
    ks.resume()
    assert ks.allow_new_orders()


# ---- testnet client endpoints -------------------------------------------

def _tc(handler):
    return BinanceTestnetClient("K", "S", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_testnet_client_endpoints():
    def handler(req):
        p = req.url.path
        if p == "/api/v3/ping":
            return httpx.Response(200, json={})
        if p == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1234})
        if p == "/api/v3/account":
            return httpx.Response(200, json={"canTrade": True, "balances": []})
        if p == "/api/v3/openOrders":
            return httpx.Response(200, json=[])
        if p == "/api/v3/order" and req.method == "DELETE":
            return httpx.Response(200, json={"status": "CANCELED"})
        if p == "/api/v3/openOrders" and req.method == "DELETE":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"msg": "x"})

    tc = _tc(handler)
    assert tc.ping() is True
    assert tc.server_time() == 1234
    assert tc.account()["canTrade"] is True
    assert tc.open_orders("BTCUSDT") == []
    assert tc.cancel_order("BTCUSDT", "cid")["status"] == "CANCELED"


def test_testnet_client_error_redacts_signature():
    from core.exceptions import BinanceAPIError

    def handler(req):
        return httpx.Response(400, json={"code": -1022, "msg": "Signature for this request is not valid"})

    with pytest.raises(BinanceAPIError) as ei:
        _tc(handler).account()
    assert "redacted" in ei.value.message.lower()      # signature error is redacted


def test_testnet_from_env():
    tc = BinanceTestnetClient.from_env(lambda: ("K", "S"), base_url=TESTNET_BASE,
                                       client=httpx.Client(transport=httpx.MockTransport(
                                           lambda r: httpx.Response(200, json={}))))
    assert tc.environment == "TESTNET"


# ---- testnet session guards & runner ------------------------------------

def test_session_disabled_is_noop():
    sess, fake, _ = _session()
    sess.enabled = False
    from signals import SignalEngine
    sig = SignalEngine().evaluate(bt_bull(260), "BTCUSDT", TF)
    assert sess.process_candle(100, 101, 99, 100, 1, 2, sig)["skipped"] == "session disabled"
    assert fake.orders == []


def test_session_run_wrapper():
    from trading import run_testnet_session
    sess, fake, _ = _session()
    out = run_testnet_session(sess, bt_bull(260))
    assert out["processed"] > 0


def test_session_not_testnet_state_is_noop():
    sess, fake, _ = _session()
    sess.executor.kill.state = TradingState.DISABLED
    from signals import SignalEngine
    sig = SignalEngine().evaluate(bt_bull(260), "BTCUSDT", TF)
    assert "skipped" in sess.process_candle(100, 101, 99, 100, 1, 2, sig)


# ---- demo trader guard (never sends orders) -----------------------------

def test_demo_trader_refuses_orders():
    from binance.demo_trader import DemoTrader
    with pytest.raises(LiveTradingDisabledError):
        DemoTrader().place_order("BTCUSDT", "BUY", 1)
