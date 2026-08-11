"""Live / Execution page — Binance connection, mode indicator and safety controls.

Shows the permanent mode indicator, Binance connection status, the kill-switch
state (Testnet is the highest selectable state — LIVE is permanently disabled in
this build), an emergency stop and a separate cancel-open-orders action. It never
places real-money orders.
"""
from __future__ import annotations

import time
from typing import List, Optional

import streamlit as st

from core.enums import Timeframe
from trading import LiveOrderStore, TradingState, mode_indicator
from trading.kill_switch import KillSwitch

from ._ui import fmt_price
from .service import DashboardService

_STATE_COLORS = {
    "🟢 DEMO": "#0e9f6e",
    "🔵 LIVE DATA — NO ORDERS": "#2563eb",
    "🟡 TESTNET": "#d97706",
    "🔴 LIVE TRADING": "#dc2626",
}


def render(service: DashboardService, symbols: List[str], timeframe: Timeframe, source: str) -> None:
    ss = st.session_state
    ss.setdefault("trading_state", TradingState.DISABLED.value)
    ss.setdefault("emergency_stopped", False)

    st.subheader("Live / Execution")

    state = TradingState(ss["trading_state"])
    indicator = mode_indicator(data_source=source, state=state, live_enabled=False)
    color = _STATE_COLORS.get(indicator, "#334155")
    st.markdown(
        f"<div style='background:{color};color:white;padding:10px 16px;border-radius:8px;"
        f"font-weight:800;font-size:1.05rem'>{indicator}</div>",
        unsafe_allow_html=True,
    )

    _connection(service)
    _kill_switch(ss)
    _emergency(service, ss)
    _explainer()
    _orders_and_events(service)


# -- sections --------------------------------------------------------------

def _connection(service: DashboardService) -> None:
    st.markdown("#### Binance connection (market data)")
    t0 = time.time()
    connected = service.probe_live()
    latency_ms = (time.time() - t0) * 1000.0
    c = st.columns(3)
    c[0].metric("Status", "CONNECTED" if connected else "DISCONNECTED")
    c[1].metric("Last update", time.strftime("%H:%M:%S UTC", time.gmtime()))
    c[2].metric("Latency", f"{latency_ms:.0f} ms" if connected else "—")
    if not connected:
        st.info("🔌 LIVE DATA UNAVAILABLE from this environment — using Demo data is fine "
                "for verifying the engine. LIVE MARKET DATA ≠ LIVE TRADING.")


def _kill_switch(ss) -> None:
    st.markdown("#### Kill switch")
    options = [TradingState.DISABLED.value, TradingState.TESTNET.value]
    current = ss["trading_state"] if ss["trading_state"] in options else options[0]
    choice = st.radio("Trading state", options, index=options.index(current),
                      help="Default is TRADING_DISABLED. Testnet is the highest selectable state.")
    ss["trading_state"] = choice
    st.markdown(
        "<div style='opacity:0.6'>🔴 <b>TRADING_LIVE is permanently disabled in this build.</b> "
        "Real-money orders require TRADING_LIVE=true and ENABLE_LIVE_CONFIRMATION=true in the "
        "environment plus a manual confirmation — and there is intentionally no mainnet order "
        "client, so live orders cannot be placed.</div>",
        unsafe_allow_html=True,
    )
    if choice == TradingState.TESTNET.value:
        has_creds = service_has_credentials()
        st.caption(f"Testnet credentials in environment: {'present' if has_creds else 'not set'} "
                   "(read from env only; never stored or shown).")


def _emergency(service: DashboardService, ss) -> None:
    st.markdown("#### Emergency controls")
    store = _store(service)
    c = st.columns(2)
    if c[0].button("🛑 STOP ALL TRADING", type="primary"):
        ss["emergency_stopped"] = True
        store.log_event("EMERGENCY_STOP", "manual stop from dashboard")
        st.error("Emergency stop engaged: new orders are blocked. Existing positions are "
                 "preserved for controlled exit.")
    if c[1].button("Cancel open orders"):
        store.log_event("CANCEL_OPEN", "manual cancel request from dashboard")
        st.warning("Cancel-open-orders requested (no testnet session connected here).")
    if ss.get("emergency_stopped"):
        st.error("⛔ EMERGENCY STOP ACTIVE — new orders are blocked.")
        if st.button("Resume (clear emergency stop)"):
            ss["emergency_stopped"] = False
            store.log_event("RESUME", "emergency stop cleared")
            st.rerun()


def _explainer() -> None:
    with st.expander("What each mode means"):
        st.markdown(
            "- 🟢 **DEMO** — synthetic data, zero orders.\n"
            "- 🔵 **LIVE DATA — NO ORDERS** — real Binance market data, zero orders "
            "(verify the engine on real markets, no risk).\n"
            "- 🟡 **TESTNET** — orders go ONLY to Binance Spot Testnet (fake money) after "
            "passing every safety check.\n"
            "- 🔴 **LIVE TRADING** — disabled in this build.\n\n"
            "Order safety runs on every order: whitelist, quantity/step/tick, min notional, "
            "balance, risk-per-trade, max exposure, max open positions, max daily loss, and "
            "duplicate-signal protection. Any failure blocks the order with the exact reason."
        )


def _orders_and_events(service: DashboardService) -> None:
    store = _store(service)
    import pandas as pd
    orders = store.all_orders()
    st.markdown("#### Orders (testnet ledger)")
    if orders:
        df = pd.DataFrame(orders)[["client_order_id", "environment", "symbol", "side",
                                   "quantity", "status", "executed_qty", "avg_price", "fees"]]
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.caption("No orders recorded.")
    events = store.events(50)
    st.markdown("#### Trading events")
    if events:
        st.dataframe(pd.DataFrame(events)[["ts", "kind", "detail"]], hide_index=True,
                     use_container_width=True)
    else:
        st.caption("No events yet.")


# -- helpers ---------------------------------------------------------------

def _store(service: DashboardService) -> LiveOrderStore:
    ss = st.session_state
    if "_live_store" not in ss:
        import os
        db_dir = os.path.dirname(service.settings.db_path) or "data"
        ss["_live_store"] = LiveOrderStore(os.path.join(db_dir, "live_orders.db"))
    return ss["_live_store"]


def service_has_credentials() -> bool:
    from config import Settings
    key, secret = Settings.get_api_credentials()
    return bool(key and secret)
