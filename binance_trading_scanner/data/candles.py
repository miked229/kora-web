"""Candle store with incremental updates.

Wraps :class:`MarketDataService` with a TTL cache and supports incremental
fetching: on refresh we only request candles newer than the last one we hold,
avoiding a full history re-download on every Streamlit rerun.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from binance.market_data import MarketDataService
from core.enums import Timeframe
from core.logger import get_logger
from core.models import Candle

from .cache import TTLCache

logger = get_logger("data.candles")


class CandleStore:
    """Caches candles per (symbol, timeframe) and updates incrementally."""

    def __init__(self, market: MarketDataService, *, cache_ttl: float = 20.0) -> None:
        self._market = market
        self._cache = TTLCache(ttl=cache_ttl)
        self._history: Dict[Tuple[str, str], List[Candle]] = {}

    def get(self, symbol: str, timeframe: Timeframe, *, limit: int = 500) -> List[Candle]:
        """Return up to ``limit`` closed candles, refreshing incrementally."""
        key = (symbol.upper(), timeframe.value)
        cached = self._cache.get(key)
        if cached is not None:
            return cached[-limit:]

        existing = self._history.get(key, [])
        if not existing:
            candles = self._market.get_closed_klines(symbol, timeframe, limit=limit)
        else:
            last_open = existing[-1].open_time
            fresh = self._market.get_closed_klines(symbol, timeframe, limit=min(limit, 500))
            candles = _merge(existing, fresh)
            if candles and candles[-1].open_time == last_open:
                logger.debug("no new candles", extra={"symbol": symbol, "timeframe": timeframe.value})

        candles = candles[-max(limit, 500):]
        self._history[key] = candles
        self._cache.set(key, candles)
        return candles[-limit:]

    def invalidate(self, symbol: str, timeframe: Timeframe) -> None:
        self._cache.clear()
        self._history.pop((symbol.upper(), timeframe.value), None)


def _merge(existing: List[Candle], fresh: List[Candle]) -> List[Candle]:
    """Merge two candle lists, de-duplicating by open_time, keeping order."""
    by_open = {c.open_time: c for c in existing}
    for c in fresh:
        by_open[c.open_time] = c  # fresh overrides (e.g. a finalised last candle)
    return [by_open[k] for k in sorted(by_open)]
