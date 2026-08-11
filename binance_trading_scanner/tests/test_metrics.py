"""Phase 5 tests: metrics honesty (None/NaN where undefined, no fake infinity)."""
from __future__ import annotations

import pytest

from core.enums import ExitReason, Timeframe
from backtesting.metrics import compute_metrics
from backtesting.portfolio import EquityPoint
from backtesting.trade import Trade

TF = Timeframe.H1


def mk_trade(net, r, *, gross=None, fees=0.0, slippage=0.0, dur=1, tid=0) -> Trade:
    gross = net if gross is None else gross
    return Trade(
        id=tid, symbol="X", timeframe="1h", direction="LONG",
        signal_timestamp=0, entry_timestamp=0, entry_price=100.0, stop_price=95.0,
        tp1_price=105.0, tp2_price=110.0, exit_timestamp=dur * 3_600_000, exit_price=105.0,
        quantity=1.0, fees=fees, slippage=slippage, gross_pnl=gross, net_pnl=net,
        return_pct=net, r_multiple=r, exit_reason=ExitReason.TP2,
        duration_bars=dur, duration_ms=dur * 3_600_000,
        max_favorable_excursion=r, max_adverse_excursion=0.0, tp1_hit=True,
    )


def equity(vals):
    pts, peak = [], vals[0]
    for i, v in enumerate(vals):
        peak = max(peak, v)
        dd = peak - v
        pts.append(EquityPoint(i, v, v, peak, dd, dd / peak * 100 if peak else 0.0))
    return pts


def test_no_trades_metrics_are_none():
    m = compute_metrics([], [], 10_000, TF, 10_000)
    assert m.total_trades == 0
    assert m.win_rate is None
    assert m.profit_factor is None
    assert any("No trades" in w for w in m.warnings)


def test_profit_factor_no_losses_is_none_not_inf():
    trades = [mk_trade(10, 1.0, tid=0), mk_trade(20, 2.0, tid=1)]
    m = compute_metrics(trades, equity([10_000, 10_010, 10_030]), 10_000, TF, 10_030)
    assert m.profit_factor is None                       # NOT infinity
    assert any("no losing trades" in w.lower() for w in m.warnings)
    assert m.win_rate == pytest.approx(100.0)


def test_profit_factor_mixed():
    trades = [mk_trade(30, 1.5, tid=0), mk_trade(-10, -1.0, tid=1), mk_trade(-5, -0.5, tid=2)]
    m = compute_metrics(trades, equity([10_000, 10_030, 10_020, 10_015]), 10_000, TF, 10_015)
    assert m.profit_factor == pytest.approx(30 / 15)     # 30 profit / 15 loss
    assert m.winning_trades == 1 and m.losing_trades == 2
    assert m.win_rate == pytest.approx(1 / 3 * 100)


def test_all_losers_profit_factor_zero():
    trades = [mk_trade(-10, -1.0, tid=0), mk_trade(-5, -0.5, tid=1)]
    m = compute_metrics(trades, equity([10_000, 9_990, 9_985]), 10_000, TF, 9_985)
    assert m.profit_factor == pytest.approx(0.0)         # profits 0 / losses>0
    assert m.average_win is None
    assert m.average_loss == pytest.approx(-7.5)


def test_expectancy_units():
    trades = [mk_trade(10, 1.0, tid=0), mk_trade(-5, -0.5, tid=1)]
    m = compute_metrics(trades, equity([10_000, 10_010, 10_005]), 10_000, TF, 10_005)
    assert m.expectancy_usdt == pytest.approx(2.5)       # quote/trade
    assert m.expectancy_r == pytest.approx(0.25)         # R/trade
    assert m.average_r == pytest.approx(0.25)


def test_consecutive_streaks():
    seq = [10, 20, -5, 15, -1, -2, -3]   # W W L W L L L
    trades = [mk_trade(v, v / 10, tid=i) for i, v in enumerate(seq)]
    m = compute_metrics(trades, equity([10_000] * 8), 10_000, TF, 10_000)
    assert m.consecutive_wins == 2
    assert m.consecutive_losses == 3


def test_largest_win_and_loss():
    trades = [mk_trade(5, 0.5, tid=0), mk_trade(-20, -2.0, tid=1), mk_trade(30, 3.0, tid=2)]
    m = compute_metrics(trades, equity([10_000, 10_005, 9_985, 10_015]), 10_000, TF, 10_015)
    assert m.largest_win == 30
    assert m.largest_loss == -20


def test_drawdown_from_equity():
    m = compute_metrics([], equity([100, 120, 90, 110]), 100, TF, 110)
    # peak 120 -> trough 90 => 30 abs, 25%
    assert m.max_drawdown == pytest.approx(30)
    assert m.max_drawdown_pct == pytest.approx(25.0)


def test_sharpe_none_when_flat_equity():
    m = compute_metrics([mk_trade(0, 0.0)], equity([10_000] * 10), 10_000, TF, 10_000)
    assert m.sharpe is None
    assert any("volatility" in w.lower() for w in m.warnings)


def test_annualization_documented():
    m = compute_metrics([], equity([10_000, 10_000]), 10_000, TF, 10_000)
    assert m.return_frequency is not None
    assert m.annualization_bars_per_year == pytest.approx(365.25 * 24)
