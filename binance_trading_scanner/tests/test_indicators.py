"""Phase 2 tests: technical indicators.

Fully offline and deterministic. Covers correctness on constructed inputs plus
the required edge cases: insufficient data, NaNs, zero volume, short/duplicate
series and invalid parameters. No look-ahead: several tests assert causality
explicitly (a later bar cannot change an earlier indicator value).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.momentum import macd, rsi, stoch_rsi
from indicators.structure import (
    breakout_detection,
    market_structure,
    support_resistance,
    swing_highs,
    swing_lows,
)
from indicators.trend import adx, ema, ema_200, sma, sma_200
from indicators.volatility import (
    atr,
    bollinger_band_width,
    bollinger_bands,
    true_range,
)
from indicators.volume import obv, relative_volume, rolling_vwap, volume_sma, vwap


# ---- helpers -------------------------------------------------------------

def const_series(value, n):
    return pd.Series([float(value)] * n)


def linspace(start, stop, n):
    return pd.Series(np.linspace(start, stop, n))


# =========================================================================
# TREND
# =========================================================================

def test_sma_constant_and_warmup():
    s = const_series(10, 30)
    out = sma(s, 5)
    assert out.iloc[:4].isna().all()          # warm-up NaN
    assert out.iloc[4:].eq(10.0).all()        # SMA of constant == constant


def test_ema_constant_and_first_value():
    s = const_series(7, 10)
    out = ema(s, 4)
    # adjust=False -> first EMA value equals the first sample.
    assert out.iloc[0] == pytest.approx(7.0)
    assert out.iloc[-1] == pytest.approx(7.0)


def test_ema_reacts_to_trend_monotonic():
    s = linspace(1, 100, 100)
    out = ema(s, 10)
    assert out.is_monotonic_increasing


def test_sma_200_short_series_all_nan():
    out = sma_200(const_series(5, 50))     # fewer than 200 points
    assert out.isna().all()


def test_ema_200_length_matches():
    s = linspace(1, 2, 300)
    assert len(ema_200(s)) == len(s)


def test_adx_uptrend_direction_and_bounds():
    # Strong, steady uptrend: +DI should dominate -DI, ADX finite in 0..100.
    n = 120
    close = linspace(100, 200, n)
    high = close + 0.5
    low = close - 0.5
    res = adx(high, low, close, period=14)
    last = res.dropna().iloc[-1]
    assert last["plus_di"] > last["minus_di"]
    # ADX is bounded to [0, 100]; allow float epsilon on a perfect trend.
    assert -1e-6 <= last["adx"] <= 100 + 1e-6
    assert res["adx"].dropna().iloc[-1] > 20  # a clear trend registers strength


def test_adx_downtrend_direction():
    n = 120
    close = linspace(200, 100, n)
    high = close + 0.5
    low = close - 0.5
    res = adx(high, low, close, period=14).dropna().iloc[-1]
    assert res["minus_di"] > res["plus_di"]


# =========================================================================
# MOMENTUM
# =========================================================================

def test_rsi_bounds():
    rng = np.random.default_rng(0)
    s = pd.Series(100 + rng.standard_normal(200).cumsum())
    r = rsi(s, 14).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_rsi_pure_uptrend_is_100():
    s = linspace(1, 100, 60)      # strictly increasing
    r = rsi(s, 14).dropna()
    assert r.iloc[-1] == pytest.approx(100.0)


def test_rsi_pure_downtrend_is_0():
    s = linspace(100, 1, 60)      # strictly decreasing
    r = rsi(s, 14).dropna()
    assert r.iloc[-1] == pytest.approx(0.0)


def test_macd_hist_equals_macd_minus_signal():
    s = pd.Series(100 + np.sin(np.linspace(0, 20, 200)) * 5)
    m = macd(s)
    diff = (m["hist"] - (m["macd"] - m["signal"])).dropna()
    assert diff.abs().max() < 1e-9


def test_macd_requires_fast_lt_slow():
    with pytest.raises(ValueError):
        macd(const_series(1, 50), fast=26, slow=12)


def test_stoch_rsi_bounds():
    rng = np.random.default_rng(1)
    s = pd.Series(50 + rng.standard_normal(300).cumsum())
    out = stoch_rsi(s, 14, 3, 3)
    k = out["k"].dropna()
    assert ((k >= 0) & (k <= 100)).all()


# =========================================================================
# VOLATILITY
# =========================================================================

def test_true_range_first_bar_is_high_low():
    high = pd.Series([10.0, 11.0])
    low = pd.Series([9.0, 10.0])
    close = pd.Series([9.5, 10.5])
    tr = true_range(high, low, close)
    assert tr.iloc[0] == pytest.approx(1.0)  # no prev close -> H-L


def test_atr_constant_range_converges():
    # Every candle spans exactly 2.0 with no gaps -> ATR -> 2.0
    n = 100
    close = const_series(100, n)
    high = close + 1.0
    low = close - 1.0
    a = atr(high, low, close, 14).iloc[-1]
    assert a == pytest.approx(2.0, abs=1e-6)


def test_bollinger_constant_series_zero_width():
    s = const_series(50, 40)
    bb = bollinger_bands(s, 20, 2)
    tail = bb.dropna()
    assert tail["upper"].eq(50.0).all()
    assert tail["lower"].eq(50.0).all()
    assert bollinger_band_width(s, 20, 2).dropna().eq(0.0).all()


def test_bollinger_band_width_nonnegative():
    rng = np.random.default_rng(2)
    s = pd.Series(100 + rng.standard_normal(200).cumsum())
    w = bollinger_band_width(s, 20, 2).dropna()
    assert (w >= 0).all()


# =========================================================================
# VOLUME
# =========================================================================

def test_volume_sma_constant():
    v = const_series(1000, 30)
    assert volume_sma(v, 10).dropna().eq(1000.0).all()


def test_relative_volume_constant_is_one():
    v = const_series(500, 40)
    rv = relative_volume(v, 20).dropna()
    assert rv.eq(1.0).all()


def test_relative_volume_spike():
    v = const_series(100, 30).copy()
    v.iloc[-1] = 300.0
    rv = relative_volume(v, 20)
    assert rv.iloc[-1] == pytest.approx(3.0)


def test_obv_accumulates_direction():
    close = pd.Series([10, 11, 10, 12])   # up, down, up
    vol = pd.Series([5, 5, 5, 5])
    o = obv(close, vol)
    # start 0; +5 (up), -5 (down) ->0; +5 (up) ->5
    assert list(o) == [0.0, 5.0, 0.0, 5.0]


def test_vwap_constant_typical_price():
    # H,L,C chosen so typical price is constant 100 regardless of volume.
    n = 20
    close = const_series(100, n)
    high = const_series(101, n)
    low = const_series(99, n)
    vol = pd.Series(np.arange(1, n + 1, dtype=float))
    vw = vwap(high, low, close, vol)
    assert vw.iloc[-1] == pytest.approx(100.0)


def test_rolling_vwap_length():
    n = 50
    s = linspace(1, 2, n)
    out = rolling_vwap(s + 1, s - 0.1, s, const_series(10, n), period=20)
    assert len(out) == n


# =========================================================================
# STRUCTURE
# =========================================================================

def test_swing_high_detected_and_unconfirmed_tail():
    # Peak at index 3; with right=2 the last 2 bars can never be pivots.
    high = pd.Series([1, 2, 3, 5, 3, 2, 1.5])
    sh = swing_highs(high, left=2, right=2)
    assert bool(sh.iloc[3]) is True
    assert sh.iloc[-2:].eq(False).all()   # tail unconfirmed -> not marked


def test_swing_low_detected():
    low = pd.Series([5, 4, 3, 1, 3, 4, 5])
    sl = swing_lows(low, left=2, right=2)
    assert bool(sl.iloc[3]) is True


def test_swing_causality_no_lookahead():
    # Truncating future bars must not change already-confirmed pivots.
    high = pd.Series([1, 2, 3, 5, 3, 2, 1.5, 4, 6, 4, 3, 2])
    full = swing_highs(high, left=2, right=2)
    truncated = swing_highs(high.iloc[:7], left=2, right=2)
    # Overlapping region (indices valid in both) must agree.
    assert full.iloc[:5].tolist() == truncated.iloc[:5].tolist()


def test_market_structure_uptrend():
    # Rising peaks and rising troughs -> HH & HL -> trend "up".
    high = pd.Series([2, 5, 3, 7, 4, 9, 5, 11, 6])
    low = pd.Series([1, 3, 2, 4, 3, 6, 4, 8, 5])
    st = market_structure(high, low, left=1, right=1)
    assert st.higher_high is True
    assert st.higher_low is True
    assert st.trend == "up"


def test_breakout_up_is_causal():
    # Flat range then a breakout close on the last bar.
    high = pd.Series([10] * 25 + [10])
    low = pd.Series([9] * 25 + [9])
    close = pd.Series([9.5] * 25 + [12.0])
    bd = breakout_detection(high, low, close, lookback=20)
    assert bool(bd["breakout_up"].iloc[-1]) is True
    # prior_high excludes the current bar (causal): equals the range high 10.
    assert bd["prior_high"].iloc[-1] == pytest.approx(10.0)
    assert bd["breakout_up"].iloc[:-1].eq(False).all()


def test_support_resistance_relative_to_price():
    high = pd.Series([2, 5, 3, 8, 4, 6, 3])
    low = pd.Series([1, 3, 1.5, 4, 2, 3, 2])
    close = pd.Series([2, 4, 2.5, 6, 3, 5, 4])
    sr = support_resistance(high, low, close, left=1, right=1)
    if sr.nearest_resistance is not None:
        assert sr.nearest_resistance >= close.iloc[-1]
    if sr.nearest_support is not None:
        assert sr.nearest_support <= close.iloc[-1]


# =========================================================================
# EDGE CASES
# =========================================================================

def test_empty_inputs_do_not_crash():
    empty = pd.Series([], dtype="float64")
    assert ema(empty, 10).empty
    assert sma(empty, 10).empty
    assert rsi(empty, 14).empty
    assert atr(empty, empty, empty, 14).empty
    assert macd(empty).empty
    assert bollinger_bands(empty).empty
    assert obv(empty, empty).empty
    assert vwap(empty, empty, empty, empty).empty
    assert swing_highs(empty).empty
    assert breakout_detection(empty, empty, empty).empty


def test_series_shorter_than_period_all_nan():
    s = const_series(10, 3)
    assert sma(s, 20).isna().all()
    assert rsi(s, 14).isna().all() or rsi(s, 14).dropna().empty
    assert bollinger_bands(s, 20).dropna().empty


def test_nan_inputs_handled():
    s = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0, 6.0, 7.0, 8.0])
    # Must not raise; produces NaNs where undefined.
    r = rsi(s, 3)
    assert isinstance(r, pd.Series)
    a = atr(s + 1, s - 1, s, 3)
    assert isinstance(a, pd.Series)


def test_zero_volume_handled():
    n = 30
    close = linspace(1, 2, n)
    zero_vol = const_series(0, n)
    # relative volume: baseline 0 -> NaN, not a crash / not inf
    rv = relative_volume(zero_vol, 10)
    assert not np.isinf(rv.to_numpy(dtype="float64")).any()
    # vwap with zero cumulative volume -> NaN, no ZeroDivision
    vw = vwap(close + 1, close - 1, close, zero_vol)
    assert vw.isna().all()
    # OBV with zero volume stays flat at 0
    assert obv(close, zero_vol).eq(0.0).all()


def test_duplicate_rows_do_not_crash():
    base = pd.Series([1.0, 2.0, 3.0])
    dup = pd.concat([base, base, base], ignore_index=True)
    assert len(ema(dup, 3)) == len(dup)
    assert len(rsi(dup, 3)) == len(dup)
    assert len(swing_highs(dup)) == len(dup)


@pytest.mark.parametrize("bad", [0, -1, -5])
def test_invalid_period_raises(bad):
    s = const_series(1, 10)
    with pytest.raises(ValueError):
        ema(s, bad)
    with pytest.raises(ValueError):
        sma(s, bad)
    with pytest.raises(ValueError):
        rsi(s, bad)


def test_indicators_accept_plain_lists():
    # as_series coercion: lists / numpy arrays are valid inputs.
    assert ema([1, 2, 3, 4, 5], 3).iloc[-1] > 0
    assert sma(np.array([1.0, 2.0, 3.0, 4.0]), 2).iloc[-1] == pytest.approx(3.5)
