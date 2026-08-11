"""Market Overview page — a card per symbol.

Shows, for each symbol: Price, 24h change, Trend, Structure, RSI, ADX, Relative
Volume, Score, Raw Score, Final Signal and Setup. All values come from the
DashboardService (existing indicators + signal engine); nothing is recomputed
here.
"""
from __future__ import annotations

from typing import List

import streamlit as st

from core.enums import Timeframe

from ._ui import fmt_num, fmt_pct, fmt_price, signal_badge_html
from .service import DashboardService


def render(service: DashboardService, symbols: List[str], timeframe: Timeframe, source: str) -> None:
    st.subheader("Market Overview")
    st.caption(
        f"{len(symbols)} symbols · {timeframe.value} · source: **{source.upper()}** — "
        "scores reflect confluence strength, not win probability."
    )

    analyses = service.scan(symbols, timeframe, source)
    cols = st.columns(min(len(analyses), 5) or 1)
    for col, a in zip(_cycle_columns(cols, len(analyses)), analyses):
        with col:
            _card(service, a)


def _cycle_columns(cols, n):
    for i in range(n):
        yield cols[i % len(cols)]


def _card(service: DashboardService, a) -> None:
    with st.container(border=True):
        if not a.ok:
            st.markdown(f"### {a.symbol}")
            st.error(a.error or "Unavailable")
            return

        m = service.metrics_row(a)
        st.markdown(f"### {a.symbol}")
        st.metric("Price", fmt_price(m["Price"]), fmt_pct(m["24h %"]))
        st.markdown(signal_badge_html(m["Signal"]), unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        c1.metric("Score", fmt_num(m["Score"]))
        c2.metric("Raw Score", fmt_num(m["Raw Score"]))

        st.write(
            {
                "Trend": m["Trend"],
                "Structure": m["Structure"],
                "Setup": m["Setup"],
                "RSI": fmt_num(m["RSI"], 0),
                "ADX": fmt_num(m["ADX"], 0),
                "RVOL": fmt_num(m["RVOL"], 2),
            }
        )
