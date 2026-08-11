"""Phase 5 tests: in-sample / out-of-sample split and walk-forward windows."""
from __future__ import annotations

import numpy as np
import pytest

from backtesting.data_split import split_in_out, walk_forward_windows
from tests.conftest import _bt_ohlc


def _df(n):
    return _bt_ohlc(100 + np.arange(n, dtype="float64"))


def test_split_is_chronological_and_disjoint():
    df = _df(100)
    sp = split_in_out(df, 0.7)
    assert sp.sizes == (70, 30)
    # out-of-sample is strictly later than in-sample (a real hold-out)
    assert sp.train["open_time"].max() < sp.test["open_time"].min()
    # no overlap, full coverage
    assert len(sp.train) + len(sp.test) == len(df)


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5])
def test_split_invalid_pct_raises(bad):
    with pytest.raises(ValueError):
        split_in_out(_df(50), bad)


def test_walk_forward_windows_roll_forward():
    ws = walk_forward_windows(100, train_size=50, test_size=10, step=10)
    assert ws[0].train_start == 0 and ws[0].train_end == 50
    assert ws[0].test_start == 50 and ws[0].test_end == 60
    # test windows are contiguous and non-overlapping when step == test_size
    for a, b in zip(ws, ws[1:]):
        assert b.test_start == a.test_end
    # every window fits inside the data
    assert all(w.test_end <= 100 for w in ws)


def test_walk_forward_invalid_sizes():
    with pytest.raises(ValueError):
        walk_forward_windows(100, train_size=0, test_size=10)
    with pytest.raises(ValueError):
        walk_forward_windows(100, train_size=10, test_size=0)


def test_walk_forward_slices_shapes():
    df = _df(120)
    ws = walk_forward_windows(len(df), 60, 20, 20)
    train, test = ws[0].slices(df)
    assert len(train) == 60 and len(test) == 20
