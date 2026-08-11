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
    st.title("📊 Binance Trading Scanner Pro")
    st.caption(
        "Educational research tool. **No live orders are placed.** "
        "Signals reflect the system's confluence rules, not a probability of profit."
    )

    # --- Sidebar controls ---
    with st.sidebar:
        st.header("Controls")
        mode = st.selectbox("Mode", [m.value for m in TradingMode],
                            index=list(TradingMode).index(settings.mode))
        if mode == TradingMode.LIVE_DISABLED.value:
            st.error("LIVE trading is disabled.")
        symbol = st.selectbox("Symbol", settings.symbols)
        timeframe = st.selectbox(
            "Timeframe", [t.value for t in settings.timeframes],
            index=[t.value for t in settings.timeframes].index(settings.default_timeframe.value),
        )
        st.number_input("Capital", value=float(settings.capital), min_value=0.0, step=100.0)
        st.number_input("Risk per trade (%)", value=settings.risk_per_trade * 100,
                        min_value=0.1, max_value=50.0, step=0.1)
        st.divider()
        st.caption(f"REST: {settings.rest_base}")

    client, market, exinfo = build_services(settings)
    try:
        st.subheader("Market Overview")
        cols = st.columns(4)
        overview_symbols = settings.symbols[:4] or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
        for col, sym in zip(cols, overview_symbols):
            with col:
                try:
                    t = market.get_ticker(sym)
                    st.metric(sym, f"{t.last_price:,.4f}", f"{t.price_change_pct:+.2f}%")
                    st.caption(f"24h quote vol: {t.quote_volume:,.0f}")
                except Exception as exc:  # one symbol failing must not break the page
                    st.metric(sym, "—")
                    st.caption(f"unavailable: {type(exc).__name__}")

        st.info(
            "Indicators, scoring, scanner table, charts, backtesting and paper "
            "trading arrive in later phases. This Phase 1 build validates the "
            "data foundation."
        )
    finally:
        client.close()


def main() -> None:
    if "--check" in sys.argv:
        raise SystemExit(run_check())
    run_dashboard()


if __name__ == "__main__":
    main()
