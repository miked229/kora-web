"""Phase 3 tests: confluence signal engine + scoring + filters.

Deterministic and offline. Uses the synthetic scenarios in conftest. Covers the
full spec checklist: trend/structure/momentum regimes, breakout vs failed
breakout, pullback, conflicting timeframe, insufficient data, low volume,
extreme volatility, bad risk/reward, score boundaries, filter blocking,
NO_TRADE frequency, explainability, and — mandatory — causality / no future
data leakage.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.enums import (
    ScoreClass,
    SetupType,
    SignalType,
    StructureClass,
    Timeframe,
    TrendClass,
)
from signals import BlockWeights, EngineConfig, SignalEngine, compute_snapshot, format_signal
from signals.scoring import BlockResult
from tests.conftest import (
    PULLBACK_BAR,
    scenario_breakout,
    scenario_extreme_volatility,
    scenario_failed_breakout,
    scenario_pullback,
    scenario_range,
    scenario_strong_bear,
    scenario_strong_bull,
)

TF = Timeframe.H1


@pytest.fixture
def engine():
    return SignalEngine()


def _eval(engine, df, **kw):
    return engine.evaluate(df, "BTCUSDT", TF, **kw)


# =========================================================================
# Regimes
# =========================================================================

def test_strong_bullish_trend_is_long(engine):
    s = _eval(engine, scenario_strong_bull())
    assert s.direction is SignalType.LONG
    assert s.trend_class in (TrendClass.BULLISH, TrendClass.STRONG_BULLISH)
    assert s.structure_class is StructureClass.BULLISH_STRUCTURE
    assert s.raw_score >= 60
    assert s.entry is not None and s.stop is not None


def test_strong_bearish_is_not_long(engine):
    s = _eval(engine, scenario_strong_bear())
    assert s.direction is not SignalType.LONG
    assert s.entry is None                       # no trade plan for a non-LONG
    assert s.trend_class in (TrendClass.BEARISH, TrendClass.STRONG_BEARISH)


def test_neutral_ranging_market(engine):
    s = _eval(engine, scenario_range())
    assert s.direction is SignalType.NEUTRAL
    assert s.structure_class is StructureClass.RANGE
    assert s.setup_type is SetupType.NONE


def test_bullish_breakout_is_long(engine):
    s = _eval(engine, scenario_breakout())
    assert s.direction is SignalType.LONG
    assert s.setup_type is SetupType.RANGE_BREAKOUT
    assert "no_volume_confirmation" not in s.blocked_by   # volume confirmed


def test_failed_breakout_is_not_long(engine):
    s = _eval(engine, scenario_failed_breakout())
    assert s.direction is not SignalType.LONG


def test_pullback_setup_is_long(engine):
    df = scenario_pullback()
    s = engine.evaluate_at(df, PULLBACK_BAR, "BTCUSDT", TF)
    assert s.setup_type is SetupType.PULLBACK
    assert s.direction is SignalType.LONG
    assert s.entry_reason and "pullback" in s.entry_reason.lower()


# =========================================================================
# Filters (each can veto a LONG regardless of raw score)
# =========================================================================

def test_conflicting_higher_timeframe_blocks(engine):
    s = _eval(engine, scenario_strong_bull(), htf_df=scenario_strong_bear())
    assert s.direction is SignalType.NO_TRADE
    assert "conflicting_higher_timeframe" in s.blocked_by
    assert s.raw_score >= 60                     # strong raw score, still vetoed


def test_insufficient_data_no_trade(engine):
    s = _eval(engine, scenario_strong_bull(n=50))
    assert s.direction is SignalType.NO_TRADE
    assert s.blocked_by == ["insufficient_data"]
    assert s.raw_score == 0.0


def test_low_volume_blocks(engine):
    df = scenario_strong_bull()
    df["volume"] = 0.0                           # no liquidity
    s = _eval(engine, df)
    assert s.direction is SignalType.NO_TRADE
    assert "low_liquidity" in s.blocked_by


def test_extreme_volatility_blocks(engine):
    s = _eval(engine, scenario_extreme_volatility())
    assert s.direction is SignalType.NO_TRADE
    assert "extreme_volatility" in s.blocked_by


def test_bad_risk_reward_blocks():
    # A very high min R:R makes the (normal 1:2) plan fail the RR filter.
    engine = SignalEngine(EngineConfig(min_rr=10.0))
    s = engine.evaluate(scenario_strong_bull(), "BTCUSDT", TF)
    assert s.direction is SignalType.NO_TRADE
    assert "poor_risk_reward" in s.blocked_by


# =========================================================================
# Score vs signal separation (spec section 15)
# =========================================================================

def test_raw_score_preserved_when_filtered(engine):
    s = _eval(engine, scenario_strong_bull(), htf_df=scenario_strong_bear())
    assert s.direction is SignalType.NO_TRADE
    assert s.raw_score == s.score                # raw score is retained
    assert s.raw_score >= 60
    assert s.blocked_by                          # and we can see WHY it was dropped


def test_score_within_bounds_all_scenarios(engine):
    for df in (scenario_strong_bull(), scenario_strong_bear(), scenario_range(),
               scenario_breakout(), scenario_failed_breakout()):
        s = _eval(engine, df)
        assert 0.0 <= s.raw_score <= 100.0
        assert s.confidence_label is ScoreClass.from_score(s.score)


def test_score_boundaries_labels():
    assert ScoreClass.from_score(39) is ScoreClass.NO_TRADE
    assert ScoreClass.from_score(40) is ScoreClass.WEAK
    assert ScoreClass.from_score(74) is ScoreClass.MODERATE
    assert ScoreClass.from_score(75) is ScoreClass.STRONG
    assert ScoreClass.from_score(85) is ScoreClass.VERY_STRONG


# =========================================================================
# NO_TRADE must be a real, common outcome
# =========================================================================

def test_no_trade_is_common_on_range(engine):
    df = scenario_range()
    longs = 0
    total = 0
    for i in range(210, len(df)):
        total += 1
        if engine.evaluate_at(df, i, "BTCUSDT", TF).direction is SignalType.LONG:
            longs += 1
    assert longs == 0                            # a ranging market yields no longs


# =========================================================================
# Trade plan integrity
# =========================================================================

def test_long_plan_is_coherent(engine):
    s = _eval(engine, scenario_strong_bull())
    assert s.direction is SignalType.LONG
    assert s.entry > s.stop                       # stop below entry
    assert s.stop_method in ("swing", "atr")
    assert len(s.take_profits) == 2
    tp1, tp2 = s.take_profits
    risk = s.entry - s.stop
    assert tp1 == pytest.approx(s.entry + risk)   # TP1 = 1R
    assert tp2 == pytest.approx(s.entry + 2 * risk)  # TP2 = 2R
    assert s.risk_reward is not None
    assert s.invalidation_conditions              # at least one invalidation


def test_non_long_has_no_plan(engine):
    for df in (scenario_strong_bear(), scenario_range()):
        s = _eval(engine, df)
        assert s.entry is None and s.stop is None
        assert s.take_profits == []
        assert s.risk_reward is None


# =========================================================================
# Block structure
# =========================================================================

def test_blocks_sum_to_raw_score(engine):
    s = _eval(engine, scenario_strong_bull())
    total = sum(v[0] for v in s.block_scores.values())
    assert total == pytest.approx(s.raw_score)
    for name, (score, mx) in s.block_scores.items():
        assert 0 <= score <= mx


def test_weights_total_100():
    assert BlockWeights().total == 100


def test_block_result_clamp():
    br = BlockResult("x", 999, 25, "s").clamp()
    assert br.score == 25
    assert br.pct == 1.0
    br2 = BlockResult("y", -5, 10, "s").clamp()
    assert br2.score == 0.0


# =========================================================================
# Momentum context (no naive RSI<30=BUY)
# =========================================================================

def test_low_rsi_in_downtrend_is_not_long(engine):
    # Strong bear: RSI is often low, but that must NOT produce a LONG.
    s = _eval(engine, scenario_strong_bear())
    assert s.direction is not SignalType.LONG
    # momentum should have flagged the bearish context, not rewarded it
    assert any("bearish" in w.lower() or "downtrend" in w.lower() for w in s.warnings)


# =========================================================================
# Explainability
# =========================================================================

def test_reasons_are_specific_and_real(engine):
    s = _eval(engine, scenario_strong_bull())
    assert "Price above EMA200" in s.reasons
    assert any("Bullish structure" in r for r in s.reasons)
    text = format_signal(s)
    assert "SIGNAL: LONG" in text
    assert "✓" in text and "INVALIDATION" in text
    # no empty/generic placeholders
    assert all(r.strip() for r in s.reasons)


def test_no_trade_reports_block_reason(engine):
    s = _eval(engine, scenario_strong_bull(), htf_df=scenario_strong_bear())
    text = format_signal(s)
    assert "BLOCKED BY: conflicting_higher_timeframe" in text
    assert any("higher timeframe" in w.lower() for w in s.warnings)


# =========================================================================
# CAUSALITY / NO FUTURE DATA LEAKAGE  (mandatory)
# =========================================================================

def test_evaluate_at_equals_slice(engine):
    df = scenario_strong_bull()
    a = engine.evaluate_at(df, 240, "BTCUSDT", TF)
    b = engine.evaluate(df.iloc[:241], "BTCUSDT", TF)
    assert a.model_dump() == b.model_dump()


def test_adding_future_bars_does_not_change_past_signal(engine):
    df = scenario_strong_bull(n=260)
    k = 240
    early = engine.evaluate_at(df.iloc[:k + 1], k, "BTCUSDT", TF)
    with_future = engine.evaluate_at(df, k, "BTCUSDT", TF)   # extra bars appended
    assert early.model_dump() == with_future.model_dump()


def test_mutating_future_bars_does_not_leak(engine):
    df = scenario_strong_bull(n=260)
    k = 235
    base = engine.evaluate_at(df, k, "BTCUSDT", TF)
    tampered = df.copy()
    # Violently corrupt every FUTURE bar; the signal at k must be identical.
    tampered.loc[tampered.index[k + 1:], ["open", "high", "low", "close", "volume"]] *= 7.3
    after = engine.evaluate_at(tampered, k, "BTCUSDT", TF)
    assert base.direction == after.direction
    assert base.raw_score == after.raw_score
    assert base.reasons == after.reasons
    assert base.entry == after.entry and base.stop == after.stop


def test_snapshot_last_row_causality(engine):
    # Indicator snapshot for a bar must not depend on later bars.
    df = scenario_strong_bull()
    cfg = EngineConfig()
    snap_full = compute_snapshot(df.iloc[:241], cfg)
    snap_more = compute_snapshot(df.iloc[:260], cfg)
    # EMA200 at bar 240 identical whether or not bars 241..259 exist.
    assert snap_full.ema200.iloc[240] == pytest.approx(snap_more.ema200.iloc[240])
    assert snap_full.rsi.iloc[240] == pytest.approx(snap_more.rsi.iloc[240], nan_ok=True)


def test_timestamp_is_from_candle_not_wallclock(engine):
    df = scenario_strong_bull()
    s = _eval(engine, df)
    expected_ms = int(df["close_time"].iloc[-1])
    assert int(s.timestamp.timestamp() * 1000) == expected_ms
