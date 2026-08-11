"""Phase 7 tests: kill switch, live guard, safety, executor gating & recovery.

Offline and deterministic. Uses a small fake testnet client so no network or
credentials are needed. The headline is the CRITICAL mode-gating test (spec 21).
"""
from __future__ import annotations

import pytest

from core.exceptions import BinanceAPIError, LiveTradingDisabledError
from core.models import SymbolFilters
from trading import (
    KillSwitch,
    LiveOrderStore,
    OrderIntent,
    PortfolioState,
    SafeExecutor,
    SafetyConfig,
    TradingState,
    check_order,
    client_order_id,
    enable_live_trading,
)


# ---- fakes / helpers -----------------------------------------------------

class FakeTestnet:
    environment = "TESTNET"

    def __init__(self, order_resp=None, get_resp=None, raise_on_order=None):
        self.orders = []
        self.cancelled = []
        self.order_resp = order_resp
        self.get_resp = get_resp
        self.raise_on_order = raise_on_order

    def new_market_order(self, symbol, side, qty, cid):
        if self.raise_on_order is not None:
            raise self.raise_on_order
        self.orders.append((symbol, side, qty, cid))
        return self.order_resp or {
            "symbol": symbol, "status": "FILLED", "executedQty": str(qty),
            "fills": [{"qty": str(qty), "price": "60000", "commission": "0.01"}]}

    def get_order(self, symbol, cid):
        return self.get_resp or {
            "symbol": symbol, "status": "FILLED", "executedQty": "0.001",
            "fills": [{"qty": "0.001", "price": "60000", "commission": "0.01"}]}

    def cancel_all_open_orders(self, symbol):
        self.cancelled.append(symbol)
        return [{"symbol": symbol, "status": "CANCELED"}]


FILT = SymbolFilters(tick_size=0.01, step_size=0.001, min_qty=0.001, min_notional=5.0)


def _intent(side="BUY", symbol="BTCUSDT", qty=0.001, price=60_000.0, ts=1_700_000_000_000):
    return OrderIntent("confluence", symbol, "1h", ts, side, qty, price)


def _state(**kw):
    d = dict(equity=10_000, available_balance=10_000, open_positions=0,
             day_realized_pnl=0.0, initial_capital=10_000)
    d.update(kw)
    return PortfolioState(**d)


def _cfg():
    return SafetyConfig(whitelist={"BTCUSDT", "ETHUSDT"}, max_order_notional=1_000)


# ---- kill switch & live guard -------------------------------------------

def test_kill_switch_default_disabled():
    ks = KillSwitch()
    assert ks.state is TradingState.DISABLED
    assert ks.allow_new_orders() is False


def test_kill_switch_testnet_allows():
    ks = KillSwitch(state=TradingState.TESTNET)
    assert ks.allow_new_orders() is True
    ks.emergency_stop("panic")
    assert ks.allow_new_orders() is False        # emergency stop blocks


def test_set_state_live_requires_guard(monkeypatch):
    ks = KillSwitch()
    monkeypatch.delenv("TRADING_LIVE", raising=False)
    monkeypatch.delenv("ENABLE_LIVE_CONFIRMATION", raising=False)
    with pytest.raises(PermissionError):
        ks.set_state(TradingState.LIVE, live_confirmation=True)


def test_enable_live_trading_needs_everything(monkeypatch):
    monkeypatch.delenv("TRADING_LIVE", raising=False)
    monkeypatch.delenv("ENABLE_LIVE_CONFIRMATION", raising=False)
    assert enable_live_trading(True) is False
    monkeypatch.setenv("TRADING_LIVE", "true")
    assert enable_live_trading(True) is False    # confirmation env still missing
    monkeypatch.setenv("ENABLE_LIVE_CONFIRMATION", "true")
    assert enable_live_trading(False) is False   # manual confirmation missing
    assert enable_live_trading(True) is True      # all three present


# ---- safety checks -------------------------------------------------------

def test_client_order_id_unique_by_side_and_fits():
    b = client_order_id(_intent("BUY"))
    s = client_order_id(_intent("SELL"))
    assert b != s and len(b) <= 36 and len(s) <= 36


def test_whitelist_blocks_non_whitelisted():
    r = check_order(_intent(symbol="DOGEUSDT"), FILT, _state(), _cfg(), [])
    assert not r.ok and "whitelist" in r.reason


def test_step_size_and_min_qty():
    bad_step = check_order(_intent(qty=0.0015), FILT, _state(), _cfg(), [])  # not multiple of 0.001? 0.0015 is 1.5x
    assert not bad_step.ok and "step" in bad_step.reason
    below_min = check_order(_intent(qty=0.0005), FILT, _state(), _cfg(), [])
    assert not below_min.ok and "min_qty" in below_min.reason


def test_tick_size_and_min_notional():
    bad_tick = check_order(_intent(price=60_000.005), FILT, _state(), _cfg(), [])
    assert not bad_tick.ok and "tick" in bad_tick.reason
    tiny = check_order(_intent(qty=0.001, price=1.0), FILT, _state(), _cfg(), [])  # notional 0.001 < 5
    assert not tiny.ok and "notional" in tiny.reason


def test_insufficient_balance():
    r = check_order(_intent(qty=0.01, price=60_000), FILT, _state(available_balance=100),
                    SafetyConfig(max_order_notional=1e9), [])
    assert not r.ok and "available" in r.reason


def test_max_order_notional_cap():
    r = check_order(_intent(qty=0.01, price=60_000), FILT, _state(),
                    SafetyConfig(max_order_notional=100), [])
    assert not r.ok and "notional" in r.reason


def test_daily_loss_and_positions():
    loss = check_order(_intent(), FILT, _state(day_realized_pnl=-600), _cfg(), [])
    assert not loss.ok and "daily_loss" in loss.reason
    maxpos = check_order(_intent(), FILT, _state(open_positions=1),
                         SafetyConfig(max_open_positions=1, max_order_notional=1e9), [])
    assert not maxpos.ok and "open_positions" in maxpos.reason


def test_duplicate_order_blocked():
    intent = _intent()
    existing = [client_order_id(intent)]
    r = check_order(intent, FILT, _state(), _cfg(), existing)
    assert not r.ok and "duplicate" in r.reason


def test_valid_order_passes():
    r = check_order(_intent(), FILT, _state(), _cfg(), [])
    assert r.ok and all(r.checks.values())


# ---- CRITICAL: mode gating (spec 21) -------------------------------------

def test_critical_mode_gating(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADING_LIVE", raising=False)
    monkeypatch.delenv("ENABLE_LIVE_CONFIRMATION", raising=False)
    intent, state, cfg = _intent(), _state(), _cfg()

    # TRADING_DISABLED -> zero orders
    s1 = LiveOrderStore(":memory:")
    e1 = SafeExecutor(KillSwitch(TradingState.DISABLED), cfg, s1, testnet_client=FakeTestnet())
    r1 = e1.submit(intent, FILT, state)
    assert r1.status == "BLOCKED" and not s1.all_orders()

    # TESTNET -> exactly one testnet order
    s2 = LiveOrderStore(":memory:")
    fake = FakeTestnet()
    e2 = SafeExecutor(KillSwitch(TradingState.TESTNET), cfg, s2, testnet_client=fake)
    r2 = e2.submit(intent, FILT, state)
    assert r2.status == "SUBMITTED" and len(fake.orders) == 1
    assert s2.all_orders()[0]["environment"] == "TESTNET"

    # LIVE with guard OFF -> zero orders, blocked
    s3 = LiveOrderStore(":memory:")
    fake3 = FakeTestnet()
    e3 = SafeExecutor(KillSwitch(TradingState.LIVE), cfg, s3, testnet_client=fake3)
    r3 = e3.submit(intent, FILT, state)
    assert r3.status == "BLOCKED" and len(fake3.orders) == 0

    # LIVE with ALL confirmations -> still no real order (no mainnet client exists)
    monkeypatch.setenv("TRADING_LIVE", "true")
    monkeypatch.setenv("ENABLE_LIVE_CONFIRMATION", "true")
    s4 = LiveOrderStore(":memory:")
    fake4 = FakeTestnet()
    e4 = SafeExecutor(KillSwitch(TradingState.LIVE), cfg, s4, testnet_client=fake4,
                      live_confirmation=True)
    with pytest.raises(LiveTradingDisabledError):
        e4.submit(intent, FILT, state)
    assert len(fake4.orders) == 0                 # zero real orders even fully confirmed


# ---- executor: routing, duplicate, reconciliation ------------------------

def test_testnet_submit_reconciles_not_assumes(tmp_path):
    # new_order returns NEW; get_order authoritative says PARTIALLY_FILLED.
    fake = FakeTestnet(
        order_resp={"symbol": "BTCUSDT", "status": "NEW", "executedQty": "0", "fills": []},
        get_resp={"symbol": "BTCUSDT", "status": "PARTIALLY_FILLED", "executedQty": "0.0005",
                  "fills": [{"qty": "0.0005", "price": "60000", "commission": "0.03"}]})
    store = LiveOrderStore(":memory:")
    ex = SafeExecutor(KillSwitch(TradingState.TESTNET), _cfg(), store, testnet_client=fake)
    r = ex.submit(_intent(), FILT, _state())
    assert r.reconciled.status == "PARTIALLY_FILLED"      # not assumed FILLED
    assert r.reconciled.executed_qty == pytest.approx(0.0005)


def test_duplicate_order_not_resent(tmp_path):
    store = LiveOrderStore(str(tmp_path / "o.db"))
    fake = FakeTestnet()
    ex = SafeExecutor(KillSwitch(TradingState.TESTNET), _cfg(), store, testnet_client=fake)
    ex.submit(_intent(), FILT, _state())
    r2 = ex.submit(_intent(), FILT, _state())             # same logical order
    assert r2.status == "DUPLICATE"
    assert len(fake.orders) == 1                           # only sent once


def test_order_rejection_recorded():
    fake = FakeTestnet(raise_on_order=BinanceAPIError(400, -2010, "insufficient balance"))
    store = LiveOrderStore(":memory:")
    ex = SafeExecutor(KillSwitch(TradingState.TESTNET), _cfg(), store, testnet_client=fake)
    r = ex.submit(_intent(), FILT, _state())
    assert r.status == "REJECTED" and not r.submitted
    assert store.get(r.client_order_id)["status"] == "REJECTED"


# ---- emergency stop & cancel --------------------------------------------

def test_emergency_stop_blocks_and_cancels():
    fake = FakeTestnet()
    store = LiveOrderStore(":memory:")
    ex = SafeExecutor(KillSwitch(TradingState.TESTNET), _cfg(), store, testnet_client=fake)
    ex.emergency_stop("manual panic", cancel_open=True, symbol="BTCUSDT")
    assert ex.kill.emergency_stopped and fake.cancelled == ["BTCUSDT"]
    r = ex.submit(_intent(), FILT, _state())               # further orders blocked
    assert r.status == "BLOCKED" and "emergency" in r.blocked_reason
    assert any(e["kind"] == "EMERGENCY_STOP" for e in store.events())


def test_cancel_open_orders_action():
    fake = FakeTestnet()
    store = LiveOrderStore(":memory:")
    ex = SafeExecutor(KillSwitch(TradingState.TESTNET), _cfg(), store, testnet_client=fake)
    ex.cancel_open_orders("BTCUSDT")
    assert fake.cancelled == ["BTCUSDT"]
    assert not ex.kill.emergency_stopped                   # cancel != stop


# ---- crash recovery ------------------------------------------------------

def test_crash_recovery_reconciles_without_duplicating(tmp_path):
    db = str(tmp_path / "orders.db")
    intent = _intent()
    cid = client_order_id(intent)

    # Session 1: record a submitted (non-terminal) order, then "crash".
    s1 = LiveOrderStore(db)
    s1.record_submitted(cid, "TESTNET", "BTCUSDT", "BUY", 0.001, intent.signal_timestamp, status="NEW")
    s1.close()

    # Session 2: restart -> recover reconciles with the exchange (FILLED).
    fake = FakeTestnet()
    s2 = LiveOrderStore(db)
    ex = SafeExecutor(KillSwitch(TradingState.TESTNET), _cfg(), s2, testnet_client=fake)
    recs = ex.recover()
    assert len(recs) == 1 and recs[0].status == "FILLED"
    assert s2.get(cid)["status"] == "FILLED"

    # Re-submitting the same signal must NOT create a second order.
    r = ex.submit(intent, FILT, _state())
    assert r.status == "DUPLICATE" and len(fake.orders) == 0
    s2.close()
