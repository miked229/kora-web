"""Phase 8 tests: final hardening, cross-module parity, security guarantee.

Offline and deterministic. Uses a stateful fake Testnet client so the full
LIVE-data -> signal -> risk -> testnet order -> fill -> position -> exit ->
journal -> reconciliation pipeline can be exercised without any network.
"""
from __future__ import annotations

import pathlib

import httpx
import pytest

from backtesting import BacktestConfig, BacktestEngine
from backtesting.execution import ExecutionConfig
from binance.testnet_client import BinanceTestnetClient
from core.enums import Timeframe
from core.exceptions import LiveTradingDisabledError
from core.models import SymbolFilters
from signals import SignalEngine
from trading import (
    KillSwitch,
    LiveOrderStore,
    OrderIntent,
    PortfolioState,
    SafeExecutor,
    SafetyConfig,
    TestnetSession,
    TradingState,
    check_order,
    conform_to_filters,
)
from trading.reconciliation import reconcile_order
from tests.conftest import bt_bull, bt_bull_then_crash

TF = Timeframe.H1
FILT = SymbolFilters(tick_size=0.01, step_size=0.00001, min_qty=0.00001, min_notional=1.0)


class FakeTestnet:
    """Stateful fake: remembers each order so get_order returns the real fill."""

    environment = "TESTNET"

    def __init__(self):
        self.mark = 100.0
        self.orders = []
        self._by_cid = {}

    def new_market_order(self, symbol, side, qty, cid):
        qty = float(qty)
        px = self.mark
        self.orders.append((side, qty, cid))
        rec = {"symbol": symbol, "status": "FILLED", "executedQty": str(qty),
               "cummulativeQuoteQty": str(qty * px),
               "fills": [{"qty": str(qty), "price": str(px), "commission": str(qty * px * 0.001)}]}
        self._by_cid[cid] = rec
        return rec

    def get_order(self, symbol, cid):
        return self._by_cid.get(cid, {"status": "NEW", "executedQty": "0"})

    def cancel_all_open_orders(self, symbol):
        return []


def _session(store=None):
    store = store or LiveOrderStore(":memory:")
    fake = FakeTestnet()
    ex = SafeExecutor(KillSwitch(TradingState.TESTNET),
                      SafetyConfig(whitelist={"BTCUSDT"}, max_order_notional=1e9),
                      store, testnet_client=fake)
    cfg = BacktestConfig(capital=10_000, risk_per_trade=0.01, execution=ExecutionConfig())
    sess = TestnetSession(SignalEngine(), cfg, ex, "BTCUSDT", TF, filters=FILT,
                          initial_balance=10_000, enabled=True)
    return sess, fake, store


def _drive(sess, fake, df):
    eng = SignalEngine()
    o = df["open"].to_numpy(); h = df["high"].to_numpy(); l = df["low"].to_numpy()
    c = df["close"].to_numpy(); ot = df["open_time"].to_numpy(); ct = df["close_time"].to_numpy()
    for i in range(len(df)):
        fake.mark = float(o[i])
        sess.process_candle(float(o[i]), float(h[i]), float(l[i]), float(c[i]),
                            int(ot[i]), int(ct[i]), eng.evaluate_at(df, i, "BTCUSDT", TF))


# =========================================================================
# FINAL end-to-end testnet flow (spec 20)
# =========================================================================

def test_full_testnet_pipeline():
    sess, fake, store = _session()
    _drive(sess, fake, bt_bull(320))
    events = [e["event"] for e in sess.journal]
    assert "SIGNAL" in events and "POSITION_OPEN" in events and "EXIT" in events
    sides = {s for s, _, _ in fake.orders}
    assert sides == {"BUY", "SELL"}                       # entries and exits routed to testnet
    exits = {e["detail"].split()[0] for e in sess.journal if e["event"] == "EXIT"}
    assert exits & {"TP1", "TP2"}
    # every testnet order is recorded and reconciled in the store
    assert len(store.all_orders()) == len(fake.orders)


def test_testnet_pipeline_handles_stops():
    sess, fake, store = _session()
    _drive(sess, fake, bt_bull_then_crash(250, 30))
    exits = {e["detail"].split()[0] for e in sess.journal if e["event"] == "EXIT"}
    assert "STOP_LOSS" in exits


# =========================================================================
# Cross-module PARITY: backtest & testnet use the SAME signal levels (spec 2)
# =========================================================================

def test_signal_levels_shared_across_modules():
    df = bt_bull(320)
    eng = SignalEngine()
    # map signal close_time -> (stop, tp1, tp2) as the single source of truth
    levels = {}
    for i in range(len(df)):
        s = eng.evaluate_at(df, i, "BTCUSDT", TF)
        if s.take_profits:
            levels[int(df["close_time"].iloc[i])] = (
                s.stop, s.take_profits[0], s.take_profits[1] if len(s.take_profits) > 1 else s.take_profits[0])

    # Backtester trades derive stop/TP from the signal
    bt = BacktestEngine(SignalEngine(), BacktestConfig(capital=10_000)).run(df, "BTCUSDT", TF)
    for t in bt.trades:
        if t.signal_timestamp in levels:
            assert (t.stop_price, t.tp1_price, t.tp2_price) == pytest.approx(levels[t.signal_timestamp])

    # Testnet session positions derive the SAME stop/TP from the same signal
    sess, fake, _ = _session()
    _drive(sess, fake, df)
    opens = [e for e in sess.journal if e["event"] == "POSITION_OPEN"]
    assert opens
    for e in opens:
        assert (e["stop"], e["tp1"], e["tp2"]) == pytest.approx(levels[e["signal_time"]])


# =========================================================================
# FINAL SECURITY GUARANTEE: no path from LIVE DATA to a MAINNET order (spec 21)
# =========================================================================

def test_no_mainnet_order_client_exists():
    # The only order-placing client is testnet-only and refuses mainnet hosts.
    with pytest.raises(Exception):
        BinanceTestnetClient("k", "s", base_url="https://api.binance.com")
    # There is no module/class that POSTs orders to a mainnet base.
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for py in root.rglob("*.py"):
        if "test" in py.name:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "/api/v3/order" in text and "api.binance.com" in text:
            offenders.append(py.name)
    assert offenders == [], f"a mainnet order path exists in: {offenders}"


def test_live_state_blocks_even_fully_confirmed(monkeypatch):
    monkeypatch.setenv("TRADING_LIVE", "true")
    monkeypatch.setenv("ENABLE_LIVE_CONFIRMATION", "true")
    store = LiveOrderStore(":memory:")
    ex = SafeExecutor(KillSwitch(TradingState.LIVE), SafetyConfig(whitelist={"BTCUSDT"}),
                      store, testnet_client=FakeTestnet(), live_confirmation=True)
    intent = OrderIntent("s", "BTCUSDT", "1h", 1, "BUY", 0.001, 60_000.0)  # notional 60
    with pytest.raises(LiveTradingDisabledError):
        ex.submit(intent, FILT, PortfolioState(1e6, 1e6, 0, 0, 1e6))
    assert store.all_orders() == []                       # zero orders, ever


# =========================================================================
# Risk engine edge cases (spec 7)
# =========================================================================

@pytest.mark.parametrize("bad", [0, -1, float("nan"), None])
def test_risk_rejects_bad_quantity(bad):
    intent = OrderIntent("s", "BTCUSDT", "1h", 1, "BUY", bad if bad is not None else 0.0, 100.0)
    r = check_order(intent, FILT, PortfolioState(1e4, 1e4, 0, 0, 1e4),
                    SafetyConfig(whitelist={"BTCUSDT"}), [])
    assert not r.ok


def test_risk_limits_extremes_never_allow_violation():
    huge = OrderIntent("s", "BTCUSDT", "1h", 1, "BUY", 1e9, 60_000.0)
    r = check_order(huge, FILT, PortfolioState(1e4, 1e4, 0, 0, 1e4),
                    SafetyConfig(whitelist={"BTCUSDT"}, max_order_notional=1_000), [])
    assert not r.ok


# =========================================================================
# Symbol filters (spec 8)
# =========================================================================

def test_conform_to_filters_grids():
    q, p = conform_to_filters(0.123456789, 60_000.017, FILT)
    assert abs((q / FILT.step_size) - round(q / FILT.step_size)) < 1e-6
    assert abs((p / FILT.tick_size) - round(p / FILT.tick_size)) < 1e-6
    assert q <= 0.123456789 and p <= 60_000.017    # rounded down, never up


# =========================================================================
# Reconciliation: local != exchange gets corrected (spec 5)
# =========================================================================

def test_reconciliation_corrects_divergence():
    fake = FakeTestnet()
    store = LiveOrderStore(":memory:")
    cid = "BBTCUSDT-divergence"
    # local believes NEW / qty 0; exchange says FILLED 0.002 @ 60000
    store.record_submitted(cid, "TESTNET", "BTCUSDT", "BUY", 0.002, 1, status="NEW")
    fake._by_cid[cid] = {"status": "FILLED", "executedQty": "0.002",
                         "cummulativeQuoteQty": "120.0", "fills": []}
    rec = reconcile_order(fake, store, "BTCUSDT", cid)
    assert rec.status == "FILLED" and rec.executed_qty == pytest.approx(0.002)
    assert rec.avg_price == pytest.approx(60_000.0)
    assert store.get(cid)["status"] == "FILLED"


# =========================================================================
# Kill-switch persistence across restart (spec 9)
# =========================================================================

def test_emergency_stop_persists_across_restart(tmp_path):
    db = str(tmp_path / "orders.db")
    s1 = LiveOrderStore(db)
    ex1 = SafeExecutor(KillSwitch(TradingState.TESTNET), SafetyConfig(), s1,
                       testnet_client=FakeTestnet())
    ex1.emergency_stop("panic")
    s1.close()

    s2 = LiveOrderStore(db)
    ex2 = SafeExecutor(KillSwitch(TradingState.TESTNET), SafetyConfig(), s2,
                       testnet_client=FakeTestnet())
    ex2.restore_kill_state()
    assert ex2.kill.emergency_stopped is True
    r = ex2.submit(OrderIntent("s", "BTCUSDT", "1h", 1, "BUY", 0.001, 100.0), FILT,
                   PortfolioState(1e4, 1e4, 0, 0, 1e4))
    assert r.status == "BLOCKED"
    s2.close()


# =========================================================================
# Database integrity at scale (spec 13)
# =========================================================================

def test_db_integrity_many_orders(tmp_path):
    db = str(tmp_path / "big.db")
    store = LiveOrderStore(db)
    for i in range(1200):
        store.record_submitted(f"cid-{i}", "TESTNET", "BTCUSDT", "BUY", 0.001, i, status="NEW")
    store.close()
    reopened = LiveOrderStore(db)                          # survives restart
    assert len(reopened.all_orders()) == 1200
    # idempotent: re-recording the same client ids does not duplicate
    for i in range(1200):
        reopened.record_submitted(f"cid-{i}", "TESTNET", "BTCUSDT", "BUY", 0.001, i, status="NEW")
    assert len(reopened.all_orders()) == 1200
    reopened.close()


# =========================================================================
# Network resilience: order requests are NOT auto-retried (no dup) (spec 11)
# =========================================================================

def test_testnet_order_not_retried_on_5xx():
    calls = {"n": 0}

    def handler(req):
        if req.url.path == "/api/v3/order":
            calls["n"] += 1
            return httpx.Response(503, json={"code": -1001, "msg": "unavailable"})
        return httpx.Response(200, json={})

    tc = BinanceTestnetClient("K", "S", client=httpx.Client(transport=httpx.MockTransport(handler)))
    from core.exceptions import BinanceAPIError
    with pytest.raises(BinanceAPIError):
        tc.new_market_order("BTCUSDT", "BUY", 0.001, "cid-x")
    assert calls["n"] == 1                                 # exactly one attempt — no ambiguous retry


# =========================================================================
# Readiness-check CLIs (spec 15)
# =========================================================================

def test_live_check_always_disabled(capsys):
    import app
    rc = app.run_live_check()
    out = capsys.readouterr().out
    assert rc == 0
    assert "LIVE TRADING DISABLED" in out


def test_testnet_check_runs_without_orders(capsys, monkeypatch):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    import app
    rc = app.run_testnet_check()
    out = capsys.readouterr().out
    assert "NO ORDERS PLACED" in out
    assert rc in (0, 1)


# =========================================================================
# System health snapshot (spec 14)
# =========================================================================

def test_system_health_components():
    from dashboard.execution import system_health
    from dashboard.service import DashboardService
    svc = DashboardService()
    h = system_health(svc, "TRADING_DISABLED", emergency_stopped=False)
    for key in ("Market Data", "WebSocket", "Database", "Signal Engine",
                "Paper Trader", "Testnet", "Kill Switch"):
        assert key in h
    assert h["Kill Switch"] == "TRADING_DISABLED"
    svc.close()
