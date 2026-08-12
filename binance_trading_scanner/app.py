"""Application entry point.

Two ways to run:

    streamlit run app.py          # launch the dashboard
    python app.py --check         # headless connectivity self-check
                                  # (prints BTCUSDT / ETHUSDT, no Streamlit needed)

Phase 1 renders a Market Overview from public REST data and degrades gracefully
if the network/API is unreachable. Later pages (scanner, chart, backtest,
positions, settings) are wired in during their respective phases.
"""
from __future__ import annotations

import sys

from config import get_settings
from core.enums import Timeframe, TradingMode
from core.logger import configure_logging


# --------------------------------------------------------------------------
# Headless CLI checks — thin wrappers over Streamlit-free modules.
#
# The actual logic lives in binance/connectivity.py and binance/readiness.py,
# neither of which imports Streamlit. These wrappers exist for convenience; the
# canonical headless entry point is cli.py. NONE of these touch Streamlit.
# --------------------------------------------------------------------------

def run_check() -> int:
    from binance.connectivity import connectivity_check
    return connectivity_check()


def run_testnet_check() -> int:
    """Verify Testnet readiness WITHOUT placing any order (headless)."""
    from binance.readiness import testnet_check
    return testnet_check()


def run_live_check() -> int:
    """Always reports that live trading is disabled (headless)."""
    from binance.readiness import live_check
    return live_check()


# --------------------------------------------------------------------------
# Streamlit dashboard (Phase 1: Market Overview)
# --------------------------------------------------------------------------

def run_dashboard() -> None:
    import streamlit as st

    settings = get_settings()
    configure_logging(settings.log_level)

    st.set_page_config(page_title="Binance Trading Scanner Pro", page_icon="📊", layout="wide")
    from dashboard import chart, execution, overview, paper, scanner, signal_details
    from dashboard import settings as settings_page
    from dashboard.service import DEMO, LIVE
    from trading import TradingState, mode_indicator

    st.title("📊 Binance Trading Scanner Pro")
    st.caption(
        "Educational research tool. **No live orders are placed.** "
        "Scores reflect the system's confluence rules, not a probability of profit."
    )

    settings_page.init_state(settings)
    ss = st.session_state
    ss.setdefault("trading_state", TradingState.DISABLED.value)

    # Permanent, unambiguous mode indicator (spec 17).
    _mode = mode_indicator(data_source=ss["source"],
                           state=TradingState(ss["trading_state"]), live_enabled=False)
    st.markdown(
        f"<div style='display:inline-block;background:#111827;color:#f8fafc;padding:4px 12px;"
        f"border-radius:14px;font-weight:700;font-size:0.9rem'>{_mode}</div>",
        unsafe_allow_html=True,
    )
    service = _service_for(settings, ss)
    live_ok = service.probe_live()

    # --- Sidebar controls ---
    with st.sidebar:
        st.header("Controls")
        st.selectbox("Mode", [m.value for m in TradingMode],
                     index=list(TradingMode).index(TradingMode.LIVE_DISABLED),
                     disabled=True, help="Live trading is disabled in this build.")

        source_label = st.radio(
            "Data source",
            ["Demo (synthetic)", "Live (Binance)"],
            index=0 if ss["source"] == DEMO else 1,
            key="source_radio",
        )
        ss["source"] = DEMO if source_label.startswith("Demo") else LIVE
        st.caption(f"Live endpoint: {'reachable' if live_ok else 'UNREACHABLE'}")

        ss["selected_symbol"] = st.selectbox(
            "Symbol", ss["symbols"],
            index=_safe_index(ss["symbols"], ss.get("selected_symbol")),
        )
        ss["timeframe"] = st.selectbox(
            "Timeframe", [t.value for t in Timeframe],
            index=[t.value for t in Timeframe].index(ss["timeframe"]),
        )
        st.metric("Capital", f"{ss['capital']:,.0f}")
        st.metric("Risk / trade", f"{ss['risk_pct']:.1f}%")
        if st.button("↻ Refresh data"):
            service.clear_cache()
            st.rerun()
        st.divider()
        pages = ["Overview", "Scanner", "Chart", "Signal Details", "Paper Trading",
                 "Live / Execution", "Settings"]
        page = st.radio("Page", pages,
                        index=_safe_index(pages, ss.get("page", "Overview")),
                        key="page_radio")
        ss["page"] = page

    # --- Live availability banner ---
    if ss["source"] == LIVE and not live_ok:
        st.error(
            "🔌 **LIVE DATA UNAVAILABLE** — the Binance public API is not reachable "
            "from this environment. Switch **Data source** to *Demo (synthetic)* in "
            "the sidebar to explore the interface with clearly-labelled fake data."
        )

    tf = Timeframe.from_value(ss["timeframe"])
    symbols = ss["symbols"]
    source = ss["source"]

    if page == "Overview":
        overview.render(service, symbols, tf, source)
    elif page == "Scanner":
        scanner.render(service, symbols, tf, source)
    elif page == "Chart":
        chart.render(service, symbols, tf, source, ss["selected_symbol"])
    elif page == "Signal Details":
        signal_details.render(service, symbols, tf, source, ss["selected_symbol"])
    elif page == "Paper Trading":
        paper.render(service, symbols, tf, source, ss["selected_symbol"])
    elif page == "Live / Execution":
        execution.render(service, symbols, tf, source)
    elif page == "Settings":
        settings_page.render(settings)


def _service_for(settings, ss):
    """Build (and cache in session_state) a DashboardService for the current
    engine thresholds; rebuild only when those thresholds change."""
    from dashboard.service import DashboardService
    from signals import EngineConfig

    sig = (settings.rest_base, ss["min_rr"], ss["min_score_long"])
    if ss.get("_svc_sig") != sig:
        old = ss.get("_service")
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        cfg = EngineConfig(min_rr=float(ss["min_rr"]), min_score_long=float(ss["min_score_long"]))
        ss["_service"] = DashboardService(settings, cfg)
        ss["_svc_sig"] = sig
    return ss["_service"]


def _safe_index(options, value) -> int:
    try:
        return options.index(value)
    except (ValueError, AttributeError):
        return 0


# CLI flags handled headlessly (never start Streamlit when any is supplied).
_CLI_FLAGS = frozenset({"--check", "--testnet-check", "--live-check"})


def main() -> None:
    # Handle CLI flags FIRST, before importing/initialising Streamlit, by
    # delegating to the Streamlit-free cli module. This guarantees a fully
    # headless run with no ScriptRunContext warnings.
    if _CLI_FLAGS.intersection(sys.argv[1:]):
        import cli
        raise SystemExit(cli.main(sys.argv[1:]))
    run_dashboard()


if __name__ == "__main__":
    main()
