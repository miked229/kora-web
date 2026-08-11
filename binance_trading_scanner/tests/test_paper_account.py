"""Phase 6 tests: paper account state, views and reset safety."""
from __future__ import annotations

import pytest

from backtesting import BacktestConfig
from backtesting.portfolio import Portfolio
from backtesting.trade import Position
from core.enums import Timeframe
from paper_trading import PaperEngine, RESET_TOKEN
from paper_trading.account import build_account_view, unrealized_pnl
from signals import SignalEngine
from tests.conftest import bt_bull

TF = Timeframe.H1


def _pos(entry=100.0, stop=95.0, qty=10.0):
    return Position(
        symbol="X", timeframe="1h", signal_time=0, entry_time=0,
        entry_raw=entry, entry_eff=entry, stop=stop, tp1=105.0, tp2=110.0,
        original_qty=qty, remaining_qty=qty, tp1_alloc=0.5, tp2_alloc=0.5,
    )


def test_account_created_with_initial_balance(tmp_path):
    pe = PaperEngine(SignalEngine(), BacktestConfig(), str(tmp_path / "p.db"),
                     "BTCUSDT", TF, initial_balance=10_000)
    view = pe.account_view(price=None)
    assert view.initial_balance == 10_000
    assert view.cash == 10_000
    assert view.equity == 10_000
    assert view.realized_pnl == 0
    assert view.open_positions == 0
    pe.close()


def test_unrealized_pnl_only_when_open():
    pos = _pos(entry=100, qty=10)
    assert unrealized_pnl(None, 110) == 0.0
    assert unrealized_pnl(pos, None) == 0.0
    assert unrealized_pnl(pos, 110) == pytest.approx(100.0)   # (110-100)*10


def test_account_view_reflects_open_position():
    p = Portfolio(10_000)
    pos = _pos(entry=100, qty=10)
    p.cash = 10_000 - 1000            # spent 1000 on the position notionally
    p.positions = [pos]
    view = build_account_view(p, pos, price=105, initial_balance=10_000)
    assert view.equity == pytest.approx(9000 + 10 * 105)      # cash + position value
    assert view.unrealized_pnl == pytest.approx(50.0)
    assert view.available_balance == pytest.approx(9000)      # only free cash


def test_reset_requires_confirmation(tmp_path):
    pe = PaperEngine(SignalEngine(), BacktestConfig(), str(tmp_path / "p.db"),
                     "BTCUSDT", TF, initial_balance=10_000)
    pe.process_new_candles(bt_bull(320))
    assert len(pe.store.trades(1000)) > 0
    with pytest.raises(ValueError):
        pe.reset(confirm="yes")          # wrong token -> refused
    pe.reset(confirm=RESET_TOKEN)         # explicit token -> wiped
    assert pe.store.trades(1000) == []
    assert pe.account_view(None).equity == 10_000
    pe.close()
