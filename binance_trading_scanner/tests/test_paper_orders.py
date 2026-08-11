"""Phase 6 tests: order/fill records and the order status lifecycle."""
from __future__ import annotations

from backtesting import BacktestConfig
from core.enums import Timeframe
from paper_trading import PaperEngine
from paper_trading.orders import Order, OrderSide, OrderStatus, OrderType
from signals import SignalEngine
from tests.conftest import bt_bull, bt_bull_then_crash

TF = Timeframe.H1


def test_order_enums():
    assert {s.value for s in OrderStatus} == {
        "PENDING", "FILLED", "PARTIALLY_FILLED", "CANCELLED", "REJECTED"}
    assert {t.value for t in OrderType} == {"MARKET", "LIMIT", "STOP"}


def test_order_to_row_roundtrip():
    o = Order(id=1, symbol="X", side=OrderSide.BUY, type=OrderType.MARKET, quantity=2.0,
              requested_price=100.0, filled_price=100.1, status=OrderStatus.FILLED,
              created_at=1, filled_at=2, fees=0.2, slippage=0.1, reason="entry")
    row = o.to_row()
    assert row["side"] == "BUY" and row["status"] == "FILLED" and row["type"] == "MARKET"


def test_entry_order_lifecycle_pending_then_filled(tmp_path):
    pe = PaperEngine(SignalEngine(), BacktestConfig(), str(tmp_path / "p.db"),
                     "BTCUSDT", TF, initial_balance=10_000)
    pe.process_new_candles(bt_bull(320))
    orders = pe.store.orders(1000)
    buys = [o for o in orders if o["side"] == "BUY"]
    sells = [o for o in orders if o["side"] == "SELL"]
    assert buys and sells
    # every BUY order ended up FILLED (a pending entry that filled next candle)
    assert all(o["status"] == "FILLED" for o in buys)
    # filled buys record a filled price and a fee
    assert all(o["filled_price"] and o["fees"] >= 0 for o in buys)
    # SELL orders carry the exit reason (TP1/TP2/STOP_LOSS/...)
    assert all(o["reason"] for o in sells)
    pe.close()


def test_exit_orders_have_fills(tmp_path):
    pe = PaperEngine(SignalEngine(), BacktestConfig(), str(tmp_path / "p.db"),
                     "BTCUSDT", TF, initial_balance=10_000)
    pe.process_new_candles(bt_bull_then_crash(250, 30))
    orders = pe.store.orders(2000)
    reasons = {o["reason"] for o in orders if o["side"] == "SELL"}
    assert reasons & {"TP1", "TP2", "STOP_LOSS"}
    pe.close()
