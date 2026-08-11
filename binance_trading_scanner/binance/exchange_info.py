"""Exchange-info service: symbol validation and trading-rule lookup.

Fetches ``/api/v3/exchangeInfo`` once and caches per-symbol rules
(:class:`SymbolInfo`) so the rest of the app can validate symbols and precision
without repeated network calls.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from core.exceptions import InvalidSymbolError
from core.logger import get_logger
from core.models import SymbolInfo

from .client import BinanceRESTClient

logger = get_logger("binance.exchange_info")


class ExchangeInfoService:
    """Loads and caches symbol trading rules from exchangeInfo."""

    def __init__(self, client: BinanceRESTClient, *, ttl_seconds: float = 3600.0) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._symbols: Dict[str, SymbolInfo] = {}
        self._loaded_at: float = 0.0

    @property
    def is_stale(self) -> bool:
        return not self._symbols or (time.time() - self._loaded_at) > self._ttl

    def load(self, force: bool = False) -> None:
        """Populate the cache from the exchange (respecting TTL)."""
        if not force and not self.is_stale:
            return
        raw = self._client.exchange_info()
        symbols: Dict[str, SymbolInfo] = {}
        for entry in raw.get("symbols", []):
            try:
                info = SymbolInfo.from_binance(entry)
                symbols[info.symbol] = info
            except Exception as exc:  # skip a single malformed entry, keep going
                logger.warning("skipping malformed exchangeInfo entry: %s", exc)
        if symbols:
            self._symbols = symbols
            self._loaded_at = time.time()
            logger.info("loaded exchangeInfo for %d symbols", len(symbols))

    def get(self, symbol: str) -> Optional[SymbolInfo]:
        if self.is_stale:
            self.load()
        return self._symbols.get(symbol.upper())

    def require(self, symbol: str) -> SymbolInfo:
        info = self.get(symbol)
        if info is None:
            raise InvalidSymbolError(f"Unknown symbol: {symbol}")
        return info

    def is_valid(self, symbol: str) -> bool:
        """True only if the symbol exists AND is actively TRADING."""
        info = self.get(symbol)
        return bool(info and info.is_trading)

    def validate_symbols(self, symbols: List[str]) -> tuple[List[str], List[str]]:
        """Split a list into (valid_trading, invalid_or_halted)."""
        valid, invalid = [], []
        for s in symbols:
            (valid if self.is_valid(s) else invalid).append(s.upper())
        if invalid:
            logger.warning("symbols not tradable/unknown: %s", ", ".join(invalid))
        return valid, invalid
