"""High-level market-data service.

Turns raw REST payloads into validated domain models and pandas DataFrames,
applying integrity checks (gaps, duplicates, ordering, un-closed candles) so no
downstream code ever consumes bad data.

Look-ahead-bias protection: :meth:`get_klines` marks the most recent candle as
``is_closed=False`` when it is still forming, and :meth:`get_closed_klines`
drops it entirely. Signal/backtest code must use closed candles only.
"""
from __future__ import annotations

import time
from typing import List, Optional

import pandas as pd

from core.enums import Timeframe
from core.exceptions import DataValidationError
from core.logger import get_logger
from core.models import BookTicker, Candle, Ticker

from .client import BinanceRESTClient

logger = get_logger("binance.market_data")

CANDLE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "is_closed",
]


class MarketDataService:
    """Fetch + validate public market data."""

    def __init__(self, client: BinanceRESTClient) -> None:
        self._client = client

    # -- prices / tickers ---------------------------------------------------

    def get_price(self, symbol: str) -> float:
        d = self._client.ticker_price(symbol)
        return float(d["price"])

    def get_ticker(self, symbol: str) -> Ticker:
        return Ticker.from_binance_24hr(self._client.ticker_24hr(symbol))

    def get_book_ticker(self, symbol: str) -> BookTicker:
        return BookTicker.from_binance(self._client.book_ticker(symbol))

    # -- candles ------------------------------------------------------------

    def get_klines(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Candle]:
        """Return validated candles, newest last.

        The final candle is flagged ``is_closed=False`` if its close time is in
        the future relative to the server-agnostic wall clock.
        """
        rows = self._client.klines(
            symbol, timeframe.value, limit=limit,
            start_time=start_time, end_time=end_time,
        )
        now_ms = int(time.time() * 1000)
        candles: List[Candle] = []
        for row in rows:
            close_time = int(row[6])
            is_closed = close_time <= now_ms
            try:
                candles.append(Candle.from_binance_kline(row, is_closed=is_closed))
            except Exception as exc:
                # A single corrupt row should not sink the whole request.
                logger.warning(
                    "dropping malformed candle: %s", exc,
                    extra={"symbol": symbol, "timeframe": timeframe.value},
                )
        _validate_candles(candles, timeframe, symbol)
        return candles

    def get_closed_klines(
        self, symbol: str, timeframe: Timeframe, *, limit: int = 500,
    ) -> List[Candle]:
        """Same as :meth:`get_klines` but strips any still-forming candle.

        Use this for signal generation and backtesting to avoid look-ahead bias.
        We request one extra candle so the caller still gets ``limit`` closed ones.
        """
        candles = self.get_klines(symbol, timeframe, limit=min(limit + 1, 1000))
        closed = [c for c in candles if c.is_closed]
        return closed[-limit:]

    def get_klines_df(
        self, symbol: str, timeframe: Timeframe, *, limit: int = 500, closed_only: bool = True,
    ) -> pd.DataFrame:
        """Return candles as a tidy DataFrame indexed by UTC close time."""
        candles = (
            self.get_closed_klines(symbol, timeframe, limit=limit)
            if closed_only
            else self.get_klines(symbol, timeframe, limit=limit)
        )
        return candles_to_df(candles)


def candles_to_df(candles: List[Candle]) -> pd.DataFrame:
    """Convert candles to a DataFrame (UTC ``close_dt`` index)."""
    if not candles:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    df = pd.DataFrame([c.model_dump() for c in candles])
    df["close_dt"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df = df.set_index("close_dt")
    return df


def _validate_candles(candles: List[Candle], timeframe: Timeframe, symbol: str) -> None:
    """Check ordering, duplicates and gaps. Raises on structural corruption."""
    if not candles:
        return
    step = timeframe.milliseconds
    prev: Optional[Candle] = None
    for c in candles:
        if prev is not None:
            if c.open_time == prev.open_time:
                raise DataValidationError(f"{symbol}: duplicate candle at {c.open_time}")
            if c.open_time < prev.open_time:
                raise DataValidationError(f"{symbol}: candles out of order at {c.open_time}")
            gap = c.open_time - prev.open_time
            if gap != step:
                # Missing candle(s): warn but do not crash the scanner.
                logger.warning(
                    "candle gap: expected %dms got %dms", step, gap,
                    extra={"symbol": symbol, "timeframe": timeframe.value},
                )
        prev = c
