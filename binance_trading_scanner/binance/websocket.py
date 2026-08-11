"""Binance Spot WebSocket client — real-time market data.

STATUS: scaffolding for a later phase (Phase 1 uses REST only).

Design notes captured now so the later implementation stays faithful to the
official docs and the reliability requirements in the spec:

    * Base stream endpoint (mainnet): wss://stream.binance.com:9443
      Combined streams:  /stream?streams=<s1>/<s2>
      Raw single stream: /ws/<streamName>
    * Kline stream name:      <symbol_lower>@kline_<interval>   (e.g. btcusdt@kline_15m)
    * Book ticker stream:     <symbol_lower>@bookTicker
    * A single connection is valid for at most 24h; the server may send a ping
      frame every ~3 min and expects a pong. Plan for scheduled reconnects.

Reliability requirements this module MUST implement when built:
    - automatic reconnection with backoff
    - heartbeat / ping-pong handling
    - de-duplication of events by kline open time
    - dropping un-closed klines (``k.x == false``) for signal purposes
    - surfacing gaps so the REST layer can backfill

Only official, currently-supported streams will be used.
"""
from __future__ import annotations

from typing import Callable, Iterable

from core.enums import Timeframe
from core.logger import get_logger

logger = get_logger("binance.websocket")


class BinanceWebSocketClient:
    """Placeholder for the streaming client (implemented in a later phase)."""

    def __init__(self, ws_base: str = "wss://stream.binance.com:9443") -> None:
        self.ws_base = ws_base.rstrip("/")

    def kline_stream_names(self, symbols: Iterable[str], timeframe: Timeframe) -> list[str]:
        """Build the official kline stream names for a set of symbols."""
        return [f"{s.lower()}@kline_{timeframe.value}" for s in symbols]

    async def run(self, streams: list[str], on_message: Callable[[dict], None]) -> None:  # pragma: no cover
        raise NotImplementedError(
            "WebSocket streaming is scheduled for a later phase; "
            "Phase 1 relies on the REST market-data service."
        )
