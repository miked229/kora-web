"""Scanner page — one sortable table across all symbols.

Columns: Symbol, Price, Trend, Structure, RSI, ADX, Volume (RVOL), Score,
Signal, Entry, Stop, TP1, TP2, R:R. Sorted by Score (descending) by default;
the Streamlit table is also interactively sortable by any column.
"""
from __future__ import annotations

from typing import List

import pandas as pd
import streamlit as st

from core.enums import Timeframe

from .service import DashboardService


_COLUMNS = [
    "Symbol", "Price", "Trend", "Structure", "RSI", "ADX", "RVOL",
    "Score", "Raw Score", "Signal", "Setup", "Entry", "Stop", "TP1", "TP2", "R:R",
]


def build_scanner_table(service: DashboardService, symbols: List[str],
                        timeframe: Timeframe, source: str) -> pd.DataFrame:
    """Return the scanner rows as a DataFrame sorted by score (desc).

    Pure/testable: no Streamlit calls, so it can be unit-tested directly.
    """
    analyses = service.scan(symbols, timeframe, source)
    rows = []
    for a in analyses:
        if a.ok:
            rows.append(service.metrics_row(a))
        else:
            rows.append({"Symbol": a.symbol, "Signal": "ERROR", "Score": -1,
                         "Setup": a.error})
    df = pd.DataFrame(rows)
    for c in _COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[_COLUMNS]
    if "Score" in df.columns:
        df = df.sort_values("Score", ascending=False, na_position="last").reset_index(drop=True)
    return df


def render(service: DashboardService, symbols: List[str], timeframe: Timeframe, source: str) -> None:
    st.subheader("Scanner")
    st.caption(f"{timeframe.value} · source: **{source.upper()}** · sorted by score")

    df = build_scanner_table(service, symbols, timeframe, source)
    if df.empty:
        st.info("No symbols to scan.")
        return

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Price": st.column_config.NumberColumn(format="%.4f"),
            "Entry": st.column_config.NumberColumn(format="%.4f"),
            "Stop": st.column_config.NumberColumn(format="%.4f"),
            "TP1": st.column_config.NumberColumn(format="%.4f"),
            "TP2": st.column_config.NumberColumn(format="%.4f"),
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "RSI": st.column_config.NumberColumn(format="%.0f"),
            "ADX": st.column_config.NumberColumn(format="%.0f"),
            "RVOL": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.caption(
        "R:R and levels are hypothetical planning values from the signal engine "
        "— not predictions, and no orders are placed."
    )
