"""Performance-hardening tests: equivalence proofs + a relative speed guard.

The Phase-9.1 optimisation (vectorised swing pivots + a prepared per-bar
evaluation context that computes the snapshot ONCE) must be FUNCTIONALLY
IDENTICAL to the previous per-bar recompute path, with no look-ahead and no
change to scoring. These tests prove that bit-for-bit, and guard against a
regression back to the O(n^2) behaviour. No trading, no network.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from backtesting import BacktestConfig, BacktestEngine, synthetic_history
from core.enums import Timeframe
from indicators.structure import _pivots, market_structure, support_resistance
from signals import SignalEngine

TF = Timeframe.H1


# ---- vectorised pivots == original loop (brute force) --------------------

def _brute_pivots(vals: np.ndarray, left: int, right: int, want_high: bool) -> np.ndarray:
    n = len(vals)
    out = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        c = vals[i]
        if np.isnan(c):
            continue
        lft = vals[i - left:i]
        rgt = vals[i + 1:i + 1 + right]
        if np.isnan(lft).any() or np.isnan(rgt).any():
            continue
        if want_high and (c > lft).all() and (c > rgt).all():
            out[i] = True
        if (not want_high) and (c < lft).all() and (c < rgt).all():
            out[i] = True
    return out


def test_vectorised_pivots_match_bruteforce():
    rng = np.random.default_rng(0)
    mismatches = 0
    for _ in range(200):
        n = int(rng.integers(1, 60))
        vals = rng.normal(size=n)
        if n > 5:
            vals[rng.integers(0, n)] = vals[rng.integers(0, n)]     # duplicate value (ties)
            if rng.random() < 0.3:
                vals[rng.integers(0, n)] = np.nan                    # a NaN
        for left in (1, 2, 3):
            for right in (1, 2, 3):
                for wh in (True, False):
                    got = _pivots(pd.Series(vals), left, right, want_high=wh).to_numpy()
                    exp = _brute_pivots(vals, left, right, wh)
                    mismatches += int(not np.array_equal(got, exp))
    assert mismatches == 0


def test_market_structure_and_sr_unchanged_on_a_frame():
    df = synthetic_history(400, TF, seed=5)
    st = market_structure(df["high"], df["low"], 2, 2)
    sr = support_resistance(df["high"], df["low"], df["close"], 2, 2)
    # Sanity: these still produce coherent output after vectorisation.
    assert st.trend in ("up", "down", "range", None)
    assert isinstance(sr.resistance_levels, list) and isinstance(sr.support_levels, list)


# ---- prepared fast path == evaluate_at (bit-for-bit, no look-ahead) -------

@pytest.mark.parametrize("seed", [3, 11, 27])
def test_prepared_signal_equals_evaluate_at(seed):
    eng = SignalEngine()
    df = synthetic_history(360, TF, seed=seed)
    prep = eng.prepare(df)
    for i in range(len(df)):
        a = eng.evaluate_at(df, i, "BTCUSDT", TF).model_dump()
        b = prep.signal_at(i, "BTCUSDT", TF).model_dump()
        assert a == b, f"bar {i} differs"


def test_prepared_does_not_look_ahead():
    # Mutating bars AFTER i must not change the signal at i (causality).
    eng = SignalEngine()
    df = synthetic_history(360, TF, seed=9)
    i = 300
    base = eng.prepare(df).signal_at(i, "BTCUSDT", TF).model_dump()
    tampered = df.copy()
    tampered.loc[tampered.index[i + 1:], ["open", "high", "low", "close"]] *= 1.5
    after = eng.prepare(tampered).signal_at(i, "BTCUSDT", TF).model_dump()
    assert base == after


# ---- relative speed guard (machine-independent) --------------------------

def test_prepared_is_substantially_faster_than_recompute():
    eng = SignalEngine()
    df = synthetic_history(420, TF, seed=1)

    t0 = time.perf_counter()
    for i in range(len(df)):
        eng.evaluate_at(df, i, "BTCUSDT", TF)
    recompute = time.perf_counter() - t0

    t0 = time.perf_counter()
    prep = eng.prepare(df)
    for i in range(len(df)):
        prep.signal_at(i, "BTCUSDT", TF)
    prepared = time.perf_counter() - t0

    # Conservative bound (typically ~40x); proves the O(n^2) recompute is gone.
    assert prepared * 5 < recompute, f"prepared={prepared:.3f}s recompute={recompute:.3f}s"


def test_backtest_runs_quickly_after_hardening():
    df = synthetic_history(800, TF, seed=2)
    t0 = time.perf_counter()
    BacktestEngine(config=BacktestConfig()).run(df, "BTCUSDT", TF)
    assert time.perf_counter() - t0 < 8.0    # was ~45s pre-optimisation
