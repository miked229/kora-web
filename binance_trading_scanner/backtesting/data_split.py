"""In-sample / out-of-sample splitting and walk-forward window preparation.

Splitting is strictly chronological — the out-of-sample segment is always later
than the in-sample one, never shuffled — so out-of-sample results are a genuine
hold-out. Walk-forward windows are *prepared* here (spec 22) but no parameter
optimisation is performed in this phase.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List

import pandas as pd


@dataclass
class Split:
    train: pd.DataFrame     # in-sample (earlier)
    test: pd.DataFrame      # out-of-sample (later)
    train_pct: float

    @property
    def sizes(self) -> tuple[int, int]:
        return len(self.train), len(self.test)


def split_in_out(df: pd.DataFrame, train_pct: float = 0.70) -> Split:
    """Chronologically split ``df`` into in-sample / out-of-sample segments."""
    if not (0.0 < train_pct < 1.0):
        raise ValueError("train_pct must be within (0, 1)")
    n = len(df)
    cut = int(n * train_pct)
    return Split(train=df.iloc[:cut].copy(), test=df.iloc[cut:].copy(), train_pct=train_pct)


@dataclass
class WalkForwardWindow:
    index: int
    train_start: int
    train_end: int     # exclusive
    test_start: int
    test_end: int      # exclusive

    def slices(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        return df.iloc[self.train_start:self.train_end], df.iloc[self.test_start:self.test_end]


def walk_forward_windows(
    n: int, train_size: int, test_size: int, step: int | None = None
) -> List[WalkForwardWindow]:
    """Build rolling (train, test) windows. Optimisation is intentionally NOT
    done here — this only prepares the schedule for a later phase."""
    if train_size <= 0 or test_size <= 0:
        raise ValueError("train_size and test_size must be positive")
    step = step or test_size
    windows: List[WalkForwardWindow] = []
    start = 0
    idx = 0
    while start + train_size + test_size <= n:
        windows.append(WalkForwardWindow(
            index=idx,
            train_start=start,
            train_end=start + train_size,
            test_start=start + train_size,
            test_end=start + train_size + test_size,
        ))
        start += step
        idx += 1
    return windows


def iter_walk_forward(
    df: pd.DataFrame, train_size: int, test_size: int, step: int | None = None
) -> Iterator[tuple[pd.DataFrame, pd.DataFrame]]:
    for w in walk_forward_windows(len(df), train_size, test_size, step):
        yield w.slices(df)
