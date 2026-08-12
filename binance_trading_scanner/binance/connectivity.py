"""Headless public market-data connectivity self-check — NO Streamlit, NO orders.

Prints BTCUSDT / ETHUSDT from the public REST endpoint and degrades gracefully
if the network/API is unreachable.
"""
from __future__ import annotations

import sys
from typing import Callable

from binance.client import BinanceRESTClient
from binance.market_data import MarketDataService
from config import get_settings
from core.exceptions import ScannerError
from core.logger import configure_logging, get_logger


def connectivity_check(out: Callable[[str], None] = print) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("app.check")
    log.info("connectivity self-check against %s", settings.rest_base)

    client = BinanceRESTClient(settings.rest_base, timeout=settings.http_timeout,
                               max_retries=settings.request_max_retries)
    market = MarketDataService(client)
    try:
        client.ping()
        log.info("ping OK; server time=%d", client.server_time())
        for symbol in ("BTCUSDT", "ETHUSDT"):
            ticker = market.get_ticker(symbol)
            book = market.get_book_ticker(symbol)
            out(f"{symbol:9s} last={ticker.last_price:<12} "
                f"24h={ticker.price_change_pct:+.2f}%  "
                f"bid={book.bid_price} ask={book.ask_price} "
                f"spread={book.spread_pct:.4f}%  quoteVol24h={ticker.quote_volume:,.0f}")
        out("\nConnectivity OK — public market data reachable.")
        return 0
    except ScannerError as exc:
        print(f"\nConnectivity FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("If this environment blocks api.binance.com, set "
              "BINANCE_REST_BASE=https://data-api.binance.vision in your .env "
              "or run from a network with Binance access.", file=sys.stderr)
        return 1
    finally:
        client.close()
