"""Phase 5 tests: execution model (entry timing, fees, slippage, intrabar).

Deterministic unit tests of the resolution logic in isolation — no engine, no
network. Covers partial TP1->TP2, stop-outs, and every ambiguity policy.
"""
from __future__ import annotations

import pytest

from core.enums import ExitReason
from backtesting.execution import (
    AmbiguityPolicy,
    ExecutionConfig,
    buy_fill_price,
    fee_on,
    leg_pnl,
    resolve_candle,
    sell_fill_price,
)
from backtesting.trade import Position


def mk_pos(entry=100.0, stop=95.0, tp1=105.0, tp2=110.0, qty=10.0,
           tp1_alloc=0.5, tp1_done=False) -> Position:
    p = Position(
        symbol="X", timeframe="1h", signal_time=0, entry_time=0,
        entry_raw=entry, entry_eff=entry, stop=stop, tp1=tp1, tp2=tp2,
        original_qty=qty, remaining_qty=qty if not tp1_done else qty * (1 - tp1_alloc),
        tp1_alloc=tp1_alloc, tp2_alloc=1 - tp1_alloc, tp1_done=tp1_done,
    )
    return p


def cfg(policy=AmbiguityPolicy.CONSERVATIVE, fee=0.001, slip=0.0005):
    return ExecutionConfig(ambiguity=policy, fee_rate=fee, slippage_rate=slip)


# ---- price adjustments ---------------------------------------------------

def test_slippage_direction():
    c = cfg(slip=0.001)
    assert buy_fill_price(100.0, c) == pytest.approx(100.1)   # buy pays more
    assert sell_fill_price(100.0, c) == pytest.approx(99.9)   # sell gets less


def test_fee_on():
    assert fee_on(1000.0, cfg(fee=0.001)) == pytest.approx(1.0)


def test_execution_config_validation():
    with pytest.raises(ValueError):
        ExecutionConfig(tp1_alloc=0.6, tp2_alloc=0.6)     # sum != 1
    with pytest.raises(ValueError):
        ExecutionConfig(fee_rate=-0.001)


# ---- exit resolution -----------------------------------------------------

def test_tp1_only_partial():
    ev = resolve_candle(mk_pos(), open_=100, high=106, low=99, close=104, cfg=cfg())
    assert len(ev) == 1
    assert ev[0].reason is ExitReason.TP1
    assert ev[0].fraction == pytest.approx(0.5)


def test_tp1_then_tp2_same_candle():
    ev = resolve_candle(mk_pos(), open_=100, high=111, low=99, close=110, cfg=cfg())
    assert [e.reason for e in ev] == [ExitReason.TP1, ExitReason.TP2]


def test_stop_only_full():
    ev = resolve_candle(mk_pos(), open_=100, high=104, low=94, close=96, cfg=cfg())
    assert len(ev) == 1 and ev[0].reason is ExitReason.STOP_LOSS
    assert ev[0].fraction == pytest.approx(1.0)
    assert ev[0].price == pytest.approx(95.0)      # filled at the stop (no gap)


def test_stop_gap_down_fills_at_open():
    # Candle gaps down THROUGH the stop -> fill at the open, not the stop.
    ev = resolve_candle(mk_pos(), open_=90, high=91, low=88, close=89, cfg=cfg())
    assert ev[0].reason is ExitReason.STOP_LOSS
    assert ev[0].price == pytest.approx(90.0)      # never the unreachable 95


def test_no_touch_returns_empty():
    assert resolve_candle(mk_pos(), open_=100, high=104, low=99, close=101, cfg=cfg()) == []


def test_ambiguity_conservative_is_stop():
    # High hits TP1 and Low hits stop in one candle -> worst case = stop.
    ev = resolve_candle(mk_pos(), open_=100, high=106, low=94, close=100, cfg=cfg(AmbiguityPolicy.CONSERVATIVE))
    assert len(ev) == 1 and ev[0].reason is ExitReason.STOP_LOSS


def test_ambiguity_optimistic_takes_tp():
    ev = resolve_candle(mk_pos(), open_=100, high=106, low=94, close=100, cfg=cfg(AmbiguityPolicy.OPTIMISTIC))
    assert ev[0].reason is ExitReason.TP1        # stop ignored this candle


def test_ambiguity_skip_settles_at_close():
    # Ambiguous candle; SKIP ignores extremes and settles at close (108 -> TP1 zone).
    ev = resolve_candle(mk_pos(), open_=100, high=111, low=94, close=108, cfg=cfg(AmbiguityPolicy.SKIP))
    assert len(ev) == 1
    assert ev[0].price == pytest.approx(108)
    assert ev[0].reason is ExitReason.TP1
    # Ambiguous candle closing below stop -> STOP_LOSS at close.
    ev2 = resolve_candle(mk_pos(), open_=100, high=111, low=94, close=93, cfg=cfg(AmbiguityPolicy.SKIP))
    assert ev2[0].reason is ExitReason.STOP_LOSS


def test_tp2_after_tp1_done():
    pos = mk_pos(tp1_done=True)
    ev = resolve_candle(pos, open_=100, high=111, low=99, close=110, cfg=cfg())
    assert len(ev) == 1 and ev[0].reason is ExitReason.TP2
    assert ev[0].fraction == pytest.approx(0.5)   # remaining half


def test_stop_after_tp1_done():
    pos = mk_pos(tp1_done=True)
    ev = resolve_candle(pos, open_=100, high=104, low=94, close=96, cfg=cfg())
    assert ev[0].reason is ExitReason.STOP_LOSS


# ---- leg PnL -------------------------------------------------------------

def test_leg_pnl_winner_costs_reduce_net():
    pos = mk_pos()
    from backtesting.execution import ExitEvent
    ev = ExitEvent(fraction=0.5, price=105.0, reason=ExitReason.TP1)
    qty, exit_eff, gross, exit_fee, exit_slip, leg_net = leg_pnl(pos, ev, cfg())
    assert qty == pytest.approx(5.0)
    assert gross == pytest.approx(5 * (105 - 100))     # 25, raw move
    assert exit_fee > 0 and exit_slip > 0
    assert leg_net < gross                              # costs reduce the net


def test_leg_pnl_zero_costs():
    pos = mk_pos()
    from backtesting.execution import ExitEvent
    ev = ExitEvent(fraction=1.0, price=110.0, reason=ExitReason.TP2)
    _, _, gross, fee, slip, net = leg_pnl(pos, ev, cfg(fee=0.0, slip=0.0))
    assert fee == 0 and slip == 0
    assert net == pytest.approx(gross)
