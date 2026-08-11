"""Signal Details page — the full explainable breakdown of one signal.

Shows RAW SCORE, FINAL SIGNAL, each block's score (Trend / Structure / Momentum
/ Volume / Volatility / Setup / Risk), and the WHY / WARNINGS / BLOCKED BY /
INVALIDATION lists. Everything is read straight from the Signal produced by the
engine.
"""
from __future__ import annotations

from typing import List

import streamlit as st

from core.enums import SignalType, Timeframe

from ._ui import fmt_price, signal_badge_html
from .service import DashboardService

_BLOCK_LABELS = [
    ("trend", "Trend"),
    ("structure", "Structure"),
    ("momentum", "Momentum"),
    ("volume", "Volume"),
    ("volatility", "Volatility"),
    ("setup", "Setup"),
    ("risk", "Risk"),
]


def render(service: DashboardService, symbols: List[str], timeframe: Timeframe,
           source: str, selected: str) -> None:
    st.subheader("Signal Details")
    symbol = st.selectbox("Symbol", symbols, index=_index_of(symbols, selected), key="details_symbol")
    a = service.get_analysis(symbol, timeframe, source)
    if not a.ok:
        st.error(a.error or "Unavailable")
        return
    s = a.signal

    top = st.columns(3)
    with top[0]:
        st.markdown("**FINAL SIGNAL**")
        st.markdown(signal_badge_html(s.direction.value), unsafe_allow_html=True)
        st.caption(f"Confidence: {s.confidence_label.value}")
    top[1].metric("SCORE", f"{s.score:.0f}/100")
    top[2].metric("RAW SCORE", f"{s.raw_score:.0f}/100")

    if s.direction is SignalType.LONG:
        plan = st.columns(4)
        plan[0].metric("Entry", fmt_price(s.entry))
        plan[1].metric("Stop", fmt_price(s.stop), help=f"method: {s.stop_method}")
        plan[2].metric("TP1", fmt_price(s.take_profit_1))
        plan[3].metric("TP2", fmt_price(s.take_profit_2))
        st.caption(f"R:R 1:{s.risk_reward} · setup: {s.setup_type.value} — hypothetical, no orders.")

    # Per-block scores
    st.markdown("#### Block scores")
    for key, label in _BLOCK_LABELS:
        pair = s.block_scores.get(key)
        if not pair:
            continue
        score, mx = pair
        st.progress(min(score / mx, 1.0) if mx else 0.0,
                    text=f"{label}: {score:.0f} / {mx:.0f}")

    # Explainability
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### WHY")
        if s.reasons:
            for r in s.reasons:
                st.markdown(f"- ✓ {r}")
        else:
            st.caption("No confirming reasons.")
    with c2:
        st.markdown("#### WARNINGS")
        if s.warnings:
            for w in s.warnings:
                st.markdown(f"- ⚠ {w}")
        else:
            st.caption("None.")

    if s.blocked_by:
        st.markdown("#### BLOCKED BY")
        st.error(", ".join(s.blocked_by))

    st.markdown("#### INVALIDATION")
    if s.invalidation_conditions:
        for c in s.invalidation_conditions:
            st.markdown(f"- {c}")
    else:
        st.caption("Not applicable (no active trade plan).")


def _index_of(symbols: List[str], selected: str) -> int:
    try:
        return symbols.index(selected)
    except (ValueError, AttributeError):
        return 0
