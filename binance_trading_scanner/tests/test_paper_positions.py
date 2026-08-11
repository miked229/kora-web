"""Phase 6 tests: position projection for display."""
from __future__ import annotations

import pytest

from backtesting.trade import Position
from paper_trading.positions import build_position_view


def _pos(entry=100.0, stop=95.0, qty=10.0, entry_time=1_000):
    return Position(
        symbol="BTCUSDT", timeframe="1h", signal_time=0, entry_time=entry_time,
        entry_raw=entry, entry_eff=entry, stop=stop, tp1=105.0, tp2=110.0,
        original_qty=qty, remaining_qty=qty, tp1_alloc=0.5, tp2_alloc=0.5,
    )


def test_position_view_fields():
    pos = _pos(entry=100, stop=95, qty=10, entry_time=1_000)
    v = build_position_view(pos, price=104, now_ms=1_000 + 3_600_000)
    assert v.symbol == "BTCUSDT" and v.side == "LONG"
    assert v.quantity == 10
    assert v.average_entry == 100
    assert v.current_price == 104
    assert v.unrealized_pnl == pytest.approx(40.0)      # (104-100)*10
    assert v.stop_loss == 95 and v.take_profit_1 == 105 and v.take_profit_2 == 110
    assert v.duration_ms == 3_600_000


def test_position_view_r_multiple():
    # risk_per_unit = 100-95 = 5; initial_risk = 5*10 = 50; unreal @110 = 100 -> R = 2.0
    pos = _pos(entry=100, stop=95, qty=10)
    v = build_position_view(pos, price=110, now_ms=pos.entry_time)
    assert v.r_multiple == pytest.approx(2.0)
