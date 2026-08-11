"""Settings page — configure the app at runtime (no code edits).

Everything here writes to ``st.session_state`` so other pages pick it up on the
next rerun. Only presentation/configuration lives here; there is no trading and
no API-key entry (public data / demo only in this phase).
"""
from __future__ import annotations

import streamlit as st

from core.enums import Timeframe

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def init_state(settings) -> None:
    """Seed session_state defaults once."""
    ss = st.session_state
    ss.setdefault("symbols", list(DEFAULT_SYMBOLS))
    ss.setdefault("timeframe", settings.default_timeframe.value)
    ss.setdefault("source", "demo")           # resolved against live availability in app
    ss.setdefault("capital", float(settings.capital))
    ss.setdefault("risk_pct", settings.risk_per_trade * 100)
    ss.setdefault("min_rr", 1.5)
    ss.setdefault("min_score_long", 40.0)
    ss.setdefault("limit", 300)
    ss.setdefault("page", "Overview")
    ss.setdefault("selected_symbol", ss["symbols"][0])


def render(settings) -> None:
    ss = st.session_state
    st.subheader("Settings")
    st.caption("Changes apply immediately. No API keys, no trading in this phase.")

    with st.form("settings_form"):
        st.markdown("#### Market universe")
        symbols_text = st.text_area(
            "Symbols (one per line or comma-separated)",
            value="\n".join(ss["symbols"]),
            height=120,
        )
        tf = st.selectbox(
            "Default timeframe", [t.value for t in Timeframe],
            index=[t.value for t in Timeframe].index(ss["timeframe"]),
        )
        limit = st.number_input("Candles to load", min_value=210, max_value=1000,
                                value=int(ss["limit"]), step=10)

        st.markdown("#### Account / risk (planning only)")
        c1, c2 = st.columns(2)
        capital = c1.number_input("Capital", min_value=0.0, value=float(ss["capital"]), step=100.0)
        risk_pct = c2.number_input("Risk per trade (%)", min_value=0.1, max_value=50.0,
                                   value=float(ss["risk_pct"]), step=0.1)

        st.markdown("#### Signal engine thresholds")
        c3, c4 = st.columns(2)
        min_rr = c3.number_input("Minimum R:R", min_value=0.5, max_value=10.0,
                                 value=float(ss["min_rr"]), step=0.1)
        min_score = c4.number_input("Minimum score for LONG", min_value=0.0, max_value=100.0,
                                    value=float(ss["min_score_long"]), step=1.0)
        st.caption(
            "These thresholds are an initial configuration, **not** a validated "
            "edge. They should be tested with the backtester (Phase 5)."
        )

        submitted = st.form_submit_button("Apply settings")

    if submitted:
        parsed = _parse_symbols(symbols_text)
        if parsed:
            ss["symbols"] = parsed
            if ss.get("selected_symbol") not in parsed:
                ss["selected_symbol"] = parsed[0]
        ss["timeframe"] = tf
        ss["limit"] = int(limit)
        ss["capital"] = float(capital)
        ss["risk_pct"] = float(risk_pct)
        ss["min_rr"] = float(min_rr)
        ss["min_score_long"] = float(min_score)
        st.success("Settings applied.")


def _parse_symbols(text: str) -> list[str]:
    raw = text.replace(",", "\n").splitlines()
    out, seen = [], set()
    for token in raw:
        s = token.strip().upper()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out
