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

from binance.client import BinanceRESTClient
from binance.exchange_info import ExchangeInfoService
from binance.market_data import MarketDataService
from config import get_settings
from core.enums import Timeframe, TradingMode
from core.exceptions import ScannerError
from core.logger import configure_logging, get_logger


def build_services(settings) -> tuple[BinanceRESTClient, MarketDataService, ExchangeInfoService]:
    client = BinanceRESTClient(
        settings.rest_base,
        timeout=settings.http_timeout,
        max_retries=settings.request_max_retries,
    )
    return client, MarketDataService(client), ExchangeInfoService(client)


# --------------------------------------------------------------------------
# Headless self-check (Phase 1 verification)
# --------------------------------------------------------------------------

def run_check() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("app.check")
    log.info("connectivity self-check against %s", settings.rest_base)

    client, market, _ = build_services(settings)
    try:
        client.ping()
        server_ms = client.server_time()
        log.info("ping OK; server time=%d", server_ms)
        for symbol in ("BTCUSDT", "ETHUSDT"):
            ticker = market.get_ticker(symbol)
            book = market.get_book_ticker(symbol)
            print(
                f"{symbol:9s} last={ticker.last_price:<12} "
                f"24h={ticker.price_change_pct:+.2f}%  "
                f"bid={book.bid_price} ask={book.ask_price} "
                f"spread={book.spread_pct:.4f}%  "
                f"quoteVol24h={ticker.quote_volume:,.0f}"
            )
        print("\nConnectivity OK — public market data reachable.")
        return 0
    except ScannerError as exc:
        print(f"\nConnectivity FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "If this environment blocks api.binance.com, set "
            "BINANCE_REST_BASE=https://data-api.binance.vision in your .env "
            "or run from a network with Binance access.",
            file=sys.stderr,
        )
        return 1
    finally:
        client.close()


# --------------------------------------------------------------------------
# Streamlit dashboard (Phase 1: Market Overview)
# --------------------------------------------------------------------------

def run_dashboard() -> None:
    import streamlit as st

    settings = get_settings()
    configure_logging(settings.log_level)

    st.set_page_config(page_title="Binance Trading Scanner Pro", page_icon="📊", layout="wide")
    from dashboard import chart, overview, paper, scanner, signal_details
    from dashboard import settings as settings_page
    from dashboard.service import DEMO, LIVE

    st.title("📊 Binance Trading Scanner Pro")
    st.caption(
        "Educational research tool. **No live orders are placed.** "
        "Scores reflect the system's confluence rules, not a probability of profit."
    )

    settings_page.init_state(settings)
    ss = st.session_state
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
        pages = ["Overview", "Scanner", "Chart", "Signal Details", "Paper Trading", "Settings"]
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


def main() -> None:
    if "--check" in sys.argv:
        raise SystemExit(run_check())
    run_dashboard()


if __name__ == "__main__":
    main()
