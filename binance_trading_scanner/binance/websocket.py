"""Binance Spot WebSocket client — real-time market data.

The network transport (``run``) needs an outbound WebSocket connection; the
message logic (``KlineStreamHandler``) is pure and fully unit-tested offline.

Closed-candle discipline (spec 1, 2, 17): signals are only ever evaluated on
CLOSED candles. A Binance kline message carries ``k.x`` (is-this-kline-closed);
the handler emits a candle exactly once, the first time it sees a closed kline
for a given ``(symbol, interval, open_time)``, and de-duplicates thereafter.

Official streams used (currently supported):
    Base:            wss://stream.binance.com:9443
    Kline stream:    <symbol_lower>@kline_<interval>   e.g. btcusdt@kline_15m
    Combined:        /stream?streams=s1/s2
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from core.enums import Timeframe
from core.logger import get_logger
from core.models import Candle

logger = get_logger("binance.websocket")

MAINNET_WS = "wss://stream.binance.com:9443"
TESTNET_WS = "wss://stream.testnet.binance.vision"


def kline_stream_names(symbols: Iterable[str], timeframe: Timeframe) -> List[str]:
    """Official kline stream names for a set of symbols."""
    return [f"{s.lower()}@kline_{timeframe.value}" for s in symbols]


def parse_kline_message(msg: dict) -> Optional[Tuple[str, str, Candle, bool]]:
    """Parse a Binance kline event.

    Returns ``(symbol, interval, candle, is_closed)`` or ``None`` if the message
    is not a kline event. Accepts both raw (``{e,k,...}``) and combined-stream
    (``{stream, data:{...}}``) envelopes.
    """
    if "data" in msg and isinstance(msg["data"], dict):
        msg = msg["data"]
    if msg.get("e") != "kline" or "k" not in msg:
        return None
    k = msg["k"]
    symbol = k.get("s") or msg.get("s")
    interval = k.get("i")
    row = [k["t"], k["o"], k["h"], k["l"], k["c"], k["v"], k["T"],
           k.get("q", "0"), k.get("n", 0), "0", "0", "0"]
    is_closed = bool(k.get("x", False))
    candle = Candle.from_binance_kline(row, is_closed=is_closed)
    return symbol, interval, candle, is_closed


@dataclass
class KlineStreamHandler:
    """Detects NEW CLOSED candles and de-duplicates by (symbol, interval, open_time)."""

    on_closed_candle: Optional[Callable[[str, str, Candle], None]] = None
    _seen: Dict[Tuple[str, str, int], bool] = field(default_factory=dict)
    last_event_ms: Optional[int] = None

    def handle(self, msg: dict) -> Optional[Candle]:
        """Process one WS message; return a Candle only for a NEW closed kline."""
        self.last_event_ms = msg.get("E") or (msg.get("data", {}) or {}).get("E")
        parsed = parse_kline_message(msg)
        if parsed is None:
            return None
        symbol, interval, candle, is_closed = parsed
        if not is_closed:
            return None                              # never act on an open candle
        key = (symbol, interval, candle.open_time)
        if key in self._seen:
            return None                              # duplicate closed candle
        self._seen[key] = True
        if self.on_closed_candle is not None:
            self.on_closed_candle(symbol, interval, candle)
        return candle

    def reset(self) -> None:
        self._seen.clear()


class BinanceWebSocketClient:
    """Thin async wrapper that connects and feeds messages to a handler.

    Requires network access; the ``websockets`` library is imported lazily so the
    module (and its tested handler) import without it.
    """

    def __init__(self, ws_base: str = MAINNET_WS) -> None:
        self.ws_base = ws_base.rstrip("/")

    def combined_url(self, streams: List[str]) -> str:
        return f"{self.ws_base}/stream?streams={'/'.join(streams)}"

    async def run(self, streams: List[str], handler: KlineStreamHandler,
                  max_reconnects: int = 100) -> None:  # pragma: no cover - needs network
        import json
        import asyncio
        try:
            import websockets
        except Exception as exc:
            raise RuntimeError("the 'websockets' package is required for live streaming") from exc

        url = self.combined_url(streams)
        attempt = 0
        while attempt <= max_reconnects:
            try:
                async with websockets.connect(url, ping_interval=180, ping_timeout=60) as ws:
                    attempt = 0
                    async for raw in ws:
                        handler.handle(json.loads(raw))
            except Exception as exc:
                attempt += 1
                delay = min(2 ** attempt, 30)
                logger.warning("WS disconnected (%s); reconnecting in %ds", exc, delay)
                await asyncio.sleep(delay)
