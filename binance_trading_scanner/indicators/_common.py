"""Shared helpers for the indicators package.

Indicators operate on pandas Series so they compose cleanly and stay testable
in isolation. This module centralises input coercion and a couple of small
numeric utilities so every indicator handles the same edge cases the same way:
empty input, too-short series, NaNs and non-float dtypes.

Look-ahead policy: every function in this package is **causal**. A value at
index ``i`` is computed only from data at indices ``<= i`` (rolling/ewm
windows look backward). The one apparent exception — swing/structure detection —
is handled explicitly in ``structure.py`` by never marking an unconfirmed pivot.
"""
from __future__ import annotations

from typing import Iterable, Union

import numpy as np
import pandas as pd

ArrayLike = Union[pd.Series, np.ndarray, Iterable[float], "list[float]"]


def as_series(data: ArrayLike, name: str = "value") -> pd.Series:
    """Coerce array-like input to a float ``pd.Series`` with a clean index.

    - Preserves an existing Series' index (so callers can keep a time index).
    - Converts to ``float64``; non-numeric entries become NaN rather than
      raising, keeping indicators robust to messy inputs.
    """
    if isinstance(data, pd.Series):
        s = data.astype("float64")
        return s.rename(name) if s.name is None else s
    arr = np.asarray(list(data) if not isinstance(data, np.ndarray) else data, dtype="float64")
    return pd.Series(arr, name=name)


def rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (a.k.a. RMA / SMMA).

    Implemented as an EWM with ``alpha = 1/period`` and no bias correction,
    which is the standard causal formulation used by RSI/ATR/ADX.
    """
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def _validate_period(period: int) -> None:
    if not isinstance(period, int) or period < 1:
        raise ValueError(f"period must be a positive int, got {period!r}")
