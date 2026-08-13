"""Chart page — interactive candlesticks with the engine's overlays.

Draws candles plus EMA20/50/200, Bollinger Bands, VWAP, support/resistance and
the signal's entry / stop / TP1 / TP2 levels. Every overlay comes from the
Analysis (snapshot indicators + Signal); the chart computes nothing itself.
"""
from __future__ import annotations

from typing import List

import pandas as pd
import streamlit as st

from core.enums import SignalType, Timeframe

from .service import Analysis, DashboardService


def build_chart(analysis: Analysis, max_bars: int = 180):
    """Return a Plotly Figure for an Analysis (importable without Streamlit)."""
    import plotly.graph_objects as go

    df = analysis.df
    snap = analysis.snapshot
    if df is None or snap is None or len(df) == 0:
        return go.Figure()

    tail = slice(-max_bars, None)
    x = pd.to_datetime(df["close_time"].iloc[tail], unit="ms", utc=True)

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=x, open=df["open"].iloc[tail], high=df["high"].iloc[tail],
        low=df["low"].iloc[tail], close=df["close"].iloc[tail], name="Price",
        increasing_line_color="#0e9f6e", decreasing_line_color="#e02424",
    ))

    def line(series, name, color, width=1.2, dash=None):
        if series is None:
            return
        fig.add_trace(go.Scatter(
            x=x, y=series.iloc[tail], name=name, mode="lines",
            line=dict(color=color, width=width, dash=dash),
        ))

    line(snap.ema20, "EMA20", "#2563eb")
    line(snap.ema50, "EMA50", "#f59e0b")
    line(snap.ema200, "EMA200", "#9333ea", width=1.6)
    line(snap.vwap, "VWAP", "#14b8a6", dash="dot")
    if snap.bb is not None and "upper" in snap.bb:
        line(snap.bb["upper"], "BB upper", "#94a3b8", width=1, dash="dot")
        line(snap.bb["lower"], "BB lower", "#94a3b8", width=1, dash="dot")

    # Support / resistance
    sr = snap.sr
    if sr is not None:
        if sr.nearest_support is not None:
            fig.add_hline(y=sr.nearest_support, line=dict(color="#0e9f6e", width=1, dash="dash"),
                          annotation_text="Support", annotation_position="bottom left")
        if sr.nearest_resistance is not None:
            fig.add_hline(y=sr.nearest_resistance, line=dict(color="#e02424", width=1, dash="dash"),
                          annotation_text="Resistance", annotation_position="top left")

    # Trade plan (LONG or SHORT). Stop is drawn red, take-profits green either way.
    s = analysis.signal
    if s is not None and s.direction.is_directional:
        if s.entry is not None:
            fig.add_hline(y=s.entry, line=dict(color="#111827", width=1.2),
                          annotation_text=f"Entry ({s.direction.value})", annotation_position="right")
        if s.stop is not None:
            fig.add_hline(y=s.stop, line=dict(color="#e02424", width=1.2, dash="dot"),
                          annotation_text="Stop", annotation_position="right")
        for i, tp in enumerate(s.take_profits, start=1):
            fig.add_hline(y=tp, line=dict(color="#0e9f6e", width=1.0, dash="dot"),
                          annotation_text=f"TP{i}", annotation_position="right")

    fig.update_layout(
        height=560, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02),
        hovermode="x unified",
    )
    return fig


def render(service: DashboardService, symbols: List[str], timeframe: Timeframe,
           source: str, selected: str) -> None:
    st.subheader("Chart")
    symbol = st.selectbox("Symbol", symbols, index=_index_of(symbols, selected), key="chart_symbol")
    a = service.get_analysis(symbol, timeframe, source)
    if not a.ok:
        st.error(a.error or "Unavailable")
        return
    st.plotly_chart(build_chart(a), use_container_width=True)
    if a.signal and a.signal.direction.is_directional:
        st.caption(
            f"{a.signal.direction.value} · Entry {a.signal.entry:.4f} · Stop {a.signal.stop:.4f} "
            f"({a.signal.stop_method}) · R:R 1:{a.signal.risk_reward} — hypothetical, no orders."
        )
        if a.signal.direction is SignalType.SHORT:
            st.caption("SHORT SIGNAL AVAILABLE — SHORT execution backend NOT enabled for Spot.")


def _index_of(symbols: List[str], selected: str) -> int:
    try:
        return symbols.index(selected)
    except (ValueError, AttributeError):
        return 0
