"""Paper Trading page.

Shows the simulated account, open position, orders, trade history and the signal
journal for the selected symbol/timeframe. It drives a persistent PaperEngine
(SQLite) using the closed candles the DashboardService already provides — no
backtesting logic lives here, and NO real orders are ever placed.
"""
from __future__ import annotations

import os
from typing import List

import pandas as pd
import streamlit as st

from backtesting import BacktestConfig, RiskLimits
from backtesting.execution import ExecutionConfig
from core.enums import Timeframe
from paper_trading import PaperEngine, RESET_TOKEN

from ._ui import fmt_price
from .service import DashboardService


def _engine(service: DashboardService, symbol: str, timeframe: Timeframe) -> PaperEngine:
    """Return a session-cached PaperEngine for (symbol, timeframe)."""
    ss = st.session_state
    key = f"paper_engine::{symbol}::{timeframe.value}"
    if ss.get("_paper_key") != key:
        old = ss.get("_paper_engine")
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        settings = service.settings
        db_dir = os.path.dirname(settings.db_path) or "data"
        db_path = os.path.join(db_dir, f"paper_{symbol}_{timeframe.value}.db")
        cfg = BacktestConfig(
            capital=float(ss.get("capital", 10_000)),
            risk_per_trade=float(ss.get("risk_pct", 1.0)) / 100.0,
            execution=ExecutionConfig(fee_rate=settings.fee_rate, slippage_rate=settings.slippage_rate),
            limits=RiskLimits(
                risk_per_trade=float(ss.get("risk_pct", 1.0)) / 100.0,
                max_daily_loss=settings.max_daily_loss,
                max_total_exposure=settings.max_exposure,
            ),
        )
        ss["_paper_engine"] = PaperEngine(service._engine, cfg, db_path, symbol, timeframe,
                                          initial_balance=float(ss.get("capital", 10_000)))
        ss["_paper_key"] = key
    return ss["_paper_engine"]


def _banner() -> None:
    st.markdown(
        "<div style='background:#334155;color:#f8fafc;padding:10px 16px;border-radius:8px;"
        "font-weight:700;letter-spacing:0.3px'>🧪 PAPER TRADING · SIMULATED ACCOUNT · "
        "NO REAL ORDERS · NOT financial advice</div>",
        unsafe_allow_html=True,
    )


def render(service: DashboardService, symbols: List[str], timeframe: Timeframe,
           source: str, selected: str) -> None:
    st.subheader("Paper Trading")
    _banner()

    symbol = st.selectbox("Symbol", symbols, index=_idx(symbols, selected), key="paper_symbol")
    a = service.get_analysis(symbol, timeframe, source)
    if not a.ok:
        st.error(a.error or "Data unavailable")
        return

    df = a.df
    price = a.price or float(df["close"].iloc[-1])
    now_ms = int(df["close_time"].iloc[-1])
    pe = _engine(service, symbol, timeframe)

    # Advance the account with any new closed candles (idempotent).
    res = pe.process_new_candles(df)
    st.caption(
        f"Source: **{source.upper()}** · processed {res['processed']} new closed candle(s) "
        f"this refresh · {res['new_trades']} new trade(s). Signal at candle close → "
        "simulated entry at next candle open."
    )
    if res.get("error"):
        st.error(f"Processing halted safely: {res['error']}")

    view = pe.account_view(price)
    _account(view)
    _open_position(pe, price, now_ms)
    _equity_chart(pe)
    _orders(pe)
    _trades(pe)
    _journal(pe)
    _reset(pe)


# -- sections --------------------------------------------------------------

def _account(view) -> None:
    st.markdown("#### Account")
    c = st.columns(4)
    c[0].metric("Balance (cash)", fmt_price(view.cash))
    c[1].metric("Equity", fmt_price(view.equity))
    c[2].metric("Available", fmt_price(view.available_balance))
    c[3].metric("Realized PnL", fmt_price(view.realized_pnl))
    c2 = st.columns(4)
    c2[0].metric("Unrealized PnL", fmt_price(view.unrealized_pnl))
    c2[1].metric("Fees", fmt_price(view.fees))
    c2[2].metric("Slippage", fmt_price(view.slippage))
    c2[3].metric("Drawdown", f"{view.drawdown_pct:.2f}%")


def _open_position(pe: PaperEngine, price: float, now_ms: int) -> None:
    st.markdown("#### Open position")
    pv = pe.open_position_view(price, now_ms)
    if pv is None:
        st.caption("Flat — no open position.")
        return
    st.dataframe(pd.DataFrame([{
        "Symbol": pv.symbol, "Entry": pv.average_entry, "Current": pv.current_price,
        "SL": pv.stop_loss, "TP1": pv.take_profit_1, "TP2": pv.take_profit_2,
        "Qty": pv.quantity, "PnL": pv.unrealized_pnl, "R": round(pv.r_multiple, 2),
    }]), hide_index=True, use_container_width=True)


def _equity_chart(pe: PaperEngine) -> None:
    pts = pe.store.equity()
    if not pts:
        return
    import plotly.graph_objects as go
    df = pd.DataFrame(pts)
    x = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=df["equity"], name="Equity", line=dict(color="#2563eb")))
    fig.update_layout(height=240, margin=dict(l=10, r=10, t=24, b=10),
                      title="Equity curve (paper)")
    st.plotly_chart(fig, use_container_width=True)


def _orders(pe: PaperEngine) -> None:
    st.markdown("#### Orders")
    rows = pe.store.orders(200)
    if not rows:
        st.caption("No orders yet.")
        return
    df = pd.DataFrame(rows)[
        ["id", "symbol", "side", "type", "status", "requested_price", "filled_price",
         "quantity", "fees", "slippage", "reason"]]
    df.columns = ["Order ID", "Symbol", "Side", "Type", "Status", "Requested",
                  "Filled", "Qty", "Fees", "Slippage", "Reason"]
    st.dataframe(df, hide_index=True, use_container_width=True)


def _trades(pe: PaperEngine) -> None:
    st.markdown("#### Trade history")
    trades = pe.store.trades(200)
    if not trades:
        st.caption("No closed trades yet.")
        return
    df = pd.DataFrame(trades)[
        ["entry_timestamp", "exit_timestamp", "net_pnl", "r_multiple", "exit_reason", "duration_bars"]]
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"], unit="ms", utc=True)
    df["exit_timestamp"] = pd.to_datetime(df["exit_timestamp"], unit="ms", utc=True)
    df.columns = ["Entry", "Exit", "PnL", "R", "Reason", "Duration (bars)"]
    st.dataframe(df, hide_index=True, use_container_width=True)


def _journal(pe: PaperEngine) -> None:
    st.markdown("#### Signal journal")
    rows = pe.store.journal(200)
    if not rows:
        st.caption("Empty.")
        return
    sig = [r for r in rows if r["event_type"] == "SIGNAL"]
    df = pd.DataFrame(sig if sig else rows)
    keep = [c for c in ["timestamp", "symbol", "raw_score", "final_score", "signal", "setup", "blocked_by"]
            if c in df.columns]
    df = df[keep]
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    st.dataframe(df, hide_index=True, use_container_width=True)


def _reset(pe: PaperEngine) -> None:
    st.markdown("#### Danger zone")
    with st.expander("Reset paper account"):
        st.warning("This permanently wipes the simulated account, orders, trades and journal.")
        typed = st.text_input(f"Type {RESET_TOKEN} to confirm", value="", key="paper_reset_confirm")
        if st.button("Reset paper account", type="secondary"):
            if typed == RESET_TOKEN:
                pe.reset(RESET_TOKEN)
                st.success("Paper account reset.")
                st.rerun()
            else:
                st.error(f"Type {RESET_TOKEN} exactly to confirm.")


def _idx(options: List[str], value: str) -> int:
    try:
        return options.index(value)
    except (ValueError, AttributeError):
        return 0
