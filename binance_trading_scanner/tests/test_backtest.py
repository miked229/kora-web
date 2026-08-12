"""Phase 5 tests: backtest engine, sizing, portfolio, look-ahead & edge cases.

Deterministic and offline. The engine is driven by synthetic price paths from
conftest; results are never presented as evidence of profitability.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backtesting import (
    BacktestConfig,
    BacktestEngine,
    ExecutionConfig,
    Portfolio,
    RiskLimits,
    position_size,
)
from core.enums import ExitReason, SignalType, Timeframe
from core.models import SymbolFilters
from tests.conftest import (
    bt_bear,
    bt_bear_then_pump,
    bt_bull,
    bt_bull_then_crash,
    bt_flat_range,
)

TF = Timeframe.H1


@pytest.fixture
def engine():
    return BacktestEngine()


# =========================================================================
# Position sizing (spec 11, 33)
# =========================================================================

def test_position_size_basic():
    r = position_size(10_000, 0.01, entry=100, stop=95)
    assert r.ok
    assert r.risk_per_unit == pytest.approx(5.0)
    assert r.qty == pytest.approx(20.0)        # 100 risk / 5 stop distance
    assert r.notional == pytest.approx(2000.0)


@pytest.mark.parametrize("cap", [0, -100, float("nan"), float("inf")])
def test_position_size_invalid_capital(cap):
    assert not position_size(cap, 0.01, 100, 95).ok


@pytest.mark.parametrize("risk", [0, -0.1, 1.5])
def test_position_size_invalid_risk(risk):
    assert not position_size(10_000, risk, 100, 95).ok


def test_position_size_zero_stop_distance():
    r = position_size(10_000, 0.01, entry=100, stop=100)   # stop == entry
    assert not r.ok and "stop distance" in r.reason


def test_position_size_stop_above_entry_invalid():
    assert not position_size(10_000, 0.01, entry=100, stop=110).ok


def test_position_size_short_basic():
    # SHORT: stop ABOVE entry, risk-per-unit = stop - entry.
    r = position_size(10_000, 0.01, entry=100, stop=105, side="SHORT")
    assert r.ok
    assert r.risk_per_unit == pytest.approx(5.0)
    assert r.qty == pytest.approx(20.0)
    assert r.notional == pytest.approx(2000.0)


def test_position_size_short_stop_below_entry_invalid():
    # For a SHORT, a stop BELOW entry is a zero/negative risk distance.
    r = position_size(10_000, 0.01, entry=100, stop=95, side="SHORT")
    assert not r.ok and "stop distance" in r.reason


def test_position_size_exposure_and_cash_caps():
    capped = position_size(10_000, 0.5, entry=100, stop=99, max_exposure_value=1_000)
    assert capped.qty == pytest.approx(10.0)               # 1000 / 100
    cash_capped = position_size(10_000, 0.5, entry=100, stop=99, available_cash=500)
    assert cash_capped.qty == pytest.approx(5.0)


def test_position_size_respects_filters():
    filt = SymbolFilters(step_size=0.1, min_qty=1.0, min_notional=10.0)
    r = position_size(10_000, 0.01, entry=100, stop=95, filters=filt)
    assert r.ok
    assert abs((r.qty / 0.1) - round(r.qty / 0.1)) < 1e-9   # multiple of step
    tiny = position_size(100, 0.01, entry=100, stop=99.9, filters=SymbolFilters(min_notional=1e9))
    assert not tiny.ok and "notional" in tiny.reason


def test_position_size_never_negative():
    r = position_size(10_000, 0.01, entry=100, stop=95, available_cash=0)
    assert not r.ok
    assert r.qty >= 0


# =========================================================================
# Portfolio & risk limits (spec 12, 13)
# =========================================================================

def test_portfolio_rejects_invalid_capital():
    with pytest.raises(ValueError):
        Portfolio(0)
    with pytest.raises(ValueError):
        Portfolio(-100)


def test_can_open_limits():
    p = Portfolio(10_000, RiskLimits(max_open_positions=0))
    ok, why = p.can_open(100, 100, "2024-01-01")
    assert not ok and "max_open_positions" in why

    p2 = Portfolio(10_000, RiskLimits(max_open_positions=1, max_total_exposure=0.1))
    ok, why = p2.can_open(2_000, 100, "2024-01-01")   # 2000 > 10% of 10000
    assert not ok and "exposure" in why

    p3 = Portfolio(1_000, RiskLimits(max_total_exposure=10))
    ok, why = p3.can_open(5_000, 100, "2024-01-01")   # more than cash
    assert not ok and "cash" in why

    p4 = Portfolio(10_000, RiskLimits(max_daily_loss=0.01))
    p4._daily_realized["2024-01-01"] = -200            # already lost 2% > 1%
    ok, why = p4.can_open(100, 100, "2024-01-01")
    assert not ok and "daily_loss" in why


# =========================================================================
# Engine integration
# =========================================================================

def test_bull_generates_long_trades(engine):
    r = engine.run(bt_bull(320), "BTCUSDT", TF)
    assert len(r.trades) > 0
    assert all(t.direction == "LONG" for t in r.trades)
    assert len(r.equity_curve) >= 300


def test_bear_generates_short_trades(engine):
    r = engine.run(bt_bear(320), "BTCUSDT", TF)
    assert len(r.trades) > 0
    assert all(t.direction == "SHORT" for t in r.trades)
    # Critical SHORT invariants on every simulated trade.
    for t in r.trades:
        assert t.stop_price > t.entry_price
        if t.tp1_price is not None:
            assert t.tp1_price < t.entry_price
        if t.tp2_price is not None:
            assert t.tp2_price < t.tp1_price


def test_short_equity_accounting_is_consistent(engine):
    # Final equity moves by exactly the sum of realised net PnL (no leakage).
    r = engine.run(bt_bear(320), "BTCUSDT", TF)
    net = sum(t.net_pnl for t in r.trades)
    assert (r.final_equity - r.initial_capital) == pytest.approx(net, abs=1e-6)


def test_short_stop_out_scenario_has_losers(engine):
    # A bear leg that pumps hard must stop the short out at a loss.
    r = engine.run(bt_bear_then_pump(250, 30), "BTCUSDT", TF)
    stops = [t for t in r.trades if t.exit_reason is ExitReason.STOP_LOSS]
    assert stops, "expected at least one short stop-loss exit"
    assert all(t.direction == "SHORT" for t in stops)
    assert all(t.net_pnl < 0 for t in stops)


def test_short_zero_costs_net_equals_gross():
    eng = BacktestEngine(config=BacktestConfig(execution=ExecutionConfig(fee_rate=0.0, slippage_rate=0.0)))
    r = eng.run(bt_bear(320), "BTCUSDT", TF)
    assert r.trades and all(t.direction == "SHORT" for t in r.trades)
    for t in r.trades:
        assert t.net_pnl == pytest.approx(t.gross_pnl)


def test_entry_is_next_candle_open(engine):
    df = bt_bull(320)
    r = engine.run(df, "BTCUSDT", TF)
    t = r.trades[0]
    entry_row = df[df["open_time"] == t.entry_timestamp].iloc[0]
    slip = engine.config.execution.slippage_rate
    assert t.entry_price == pytest.approx(entry_row["open"] * (1 + slip))
    # the entry candle is exactly the one after the signal candle
    sig_pos = int(df.index[df["close_time"] == t.signal_timestamp][0])
    entry_pos = int(entry_row.name)
    assert entry_pos == sig_pos + 1


def test_fees_and_slippage_recorded(engine):
    r = engine.run(bt_bull(320), "BTCUSDT", TF)
    assert r.metrics.fees > 0
    assert r.metrics.slippage > 0


def test_zero_costs_net_equals_gross():
    eng = BacktestEngine(config=BacktestConfig(execution=ExecutionConfig(fee_rate=0.0, slippage_rate=0.0)))
    r = eng.run(bt_bull(320), "BTCUSDT", TF)
    assert r.metrics.fees == 0
    assert r.metrics.slippage == 0
    for t in r.trades:
        assert t.net_pnl == pytest.approx(t.gross_pnl)


def test_stop_loss_scenario_has_losers(engine):
    r = engine.run(bt_bull_then_crash(250, 30), "BTCUSDT", TF)
    stops = [t for t in r.trades if t.exit_reason is ExitReason.STOP_LOSS]
    assert stops, "expected at least one stop-loss exit"
    assert all(t.net_pnl < 0 for t in stops)


def test_tp1_then_tp2_scenario(engine):
    r = engine.run(bt_bull(320), "BTCUSDT", TF)
    tp2 = [t for t in r.trades if t.exit_reason is ExitReason.TP2 and t.tp1_hit]
    assert tp2, "expected a TP1->TP2 partial-then-final trade"
    assert len(tp2[0].legs) == 2                       # two fills: TP1 then TP2


def test_no_trades_on_range(engine):
    r = engine.run(bt_flat_range(300), "BTCUSDT", TF)
    assert r.trades == []
    assert any("No trades" in w for w in r.metrics.warnings)


def test_insufficient_data(engine):
    r = engine.run(bt_bull(60), "BTCUSDT", TF)           # < min_bars
    assert not r.data_quality["sufficient"]
    assert r.trades == []


def test_data_gaps_reported(engine):
    df = bt_bull(320)
    gapped = df.drop(index=range(150, 155)).reset_index(drop=True)  # remove 5 candles
    r = engine.run(gapped, "BTCUSDT", TF)
    assert r.data_quality["gap_count"] >= 1
    assert any("gap" in m.lower() for m in r.data_quality["messages"])


def test_duplicate_candles_reported_and_deduped(engine):
    df = bt_bull(320)
    dup = df.iloc[[100]].copy()
    doubled = pd.concat([df.iloc[:200], dup, df.iloc[200:]], ignore_index=True)
    r = engine.run(doubled, "BTCUSDT", TF)
    assert r.data_quality["duplicate_count"] >= 1


def test_risk_limit_blocks_entries():
    eng = BacktestEngine(config=BacktestConfig(limits=RiskLimits(max_daily_loss=0.0002)))
    r = eng.run(bt_bull_then_crash(250, 40), "BTCUSDT", TF)
    assert r.risk_blocked > 0                            # entries blocked after daily loss


# =========================================================================
# Signal log (spec 27, 28)
# =========================================================================

def test_signal_log_records_every_bar(engine):
    df = bt_bull(320)
    r = engine.run(df, "BTCUSDT", TF)
    assert len(r.signal_log) == len(df)
    dirs = {e["direction"] for e in r.signal_log}
    # NEUTRAL / NO_TRADE are logged too, not only executed trades
    assert dirs & {SignalType.NO_TRADE.value, SignalType.NEUTRAL.value}
    for e in r.signal_log:
        assert "raw_score" in e and "final_score" in e and "blocked_by" in e


# =========================================================================
# In-sample vs out-of-sample (spec 21)
# =========================================================================

def test_in_out_sample_separate(engine):
    df = bt_bull(600)
    in_res, out_res = engine.run_split(df, "BTCUSDT", TF, train_pct=0.7)
    assert in_res.label == "in_sample" and out_res.label == "out_of_sample"
    # periods do not overlap; out-of-sample is later
    assert in_res.period_end <= out_res.period_start
    # metrics are computed independently
    assert in_res.metrics is not out_res.metrics


# =========================================================================
# Multiple symbols run independently (spec 23)
# =========================================================================

def test_multiple_symbols_independent(engine):
    r_btc = engine.run(bt_bull(320, base=100), "BTCUSDT", TF)
    r_eth = engine.run(bt_flat_range(320), "ETHUSDT", TF)
    assert r_btc.symbol == "BTCUSDT" and r_eth.symbol == "ETHUSDT"
    assert len(r_btc.trades) > 0 and len(r_eth.trades) == 0


# =========================================================================
# LOOK-AHEAD VALIDATION (spec 31) — mandatory
# =========================================================================

def test_future_bars_do_not_change_past_trades(engine):
    full = bt_bull(400)
    short = full.iloc[:300].reset_index(drop=True)
    r_short = engine.run(short, "BTCUSDT", TF)
    r_full = engine.run(full, "BTCUSDT", TF)
    # Trades that closed naturally in the short run must be identical in the full run.
    natural = [t for t in r_short.trades if t.exit_reason is not ExitReason.END_OF_TEST]
    by_id = {t.id: t for t in r_full.trades}
    assert natural, "expected some naturally-closed trades to compare"
    for t in natural:
        f = by_id[t.id]
        assert (t.entry_timestamp, t.entry_price, t.stop_price, t.tp1_price, t.tp2_price) == \
               (f.entry_timestamp, f.entry_price, f.stop_price, f.tp1_price, f.tp2_price)
        assert t.net_pnl == pytest.approx(f.net_pnl)
        assert t.exit_reason == f.exit_reason


def test_mutating_future_candles_does_not_leak(engine):
    df = bt_bull(400)
    r1 = engine.run(df, "BTCUSDT", TF)
    first = r1.trades[0]
    # find a bar index safely after the first trade closed
    exit_pos = int(df.index[df["close_time"] == first.exit_timestamp][0])
    assert exit_pos < 380
    tampered = df.copy()
    cols = ["open", "high", "low", "close", "volume"]
    tampered.loc[tampered.index[exit_pos + 20:], cols] *= 3.0   # corrupt the future
    r2 = engine.run(tampered, "BTCUSDT", TF)
    f = {t.id: t for t in r2.trades}[first.id]
    assert (first.entry_price, first.stop_price, first.tp1_price, first.tp2_price) == \
           (f.entry_price, f.stop_price, f.tp1_price, f.tp2_price)
    assert first.net_pnl == pytest.approx(f.net_pnl)
    assert first.exit_reason == f.exit_reason


# =========================================================================
# Equity / drawdown & accounting sanity
# =========================================================================

def test_equity_and_drawdown_recorded(engine):
    r = engine.run(bt_bull_then_crash(250, 30), "BTCUSDT", TF)
    assert len(r.equity_curve) > 0
    assert r.metrics.max_drawdown >= 0
    assert r.metrics.max_drawdown_pct >= 0


def test_no_negative_cash_or_size(engine):
    r = engine.run(bt_bull_then_crash(250, 40), "BTCUSDT", TF)
    for t in r.trades:
        assert t.quantity > 0
    # equity never goes negative on a long-only spot backtest
    assert all(p.equity > 0 for p in r.equity_curve)
