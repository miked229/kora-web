"""Enumerations shared across the application.

Keeping these in one isolated module avoids circular imports and gives every
other package a single source of truth for the vocabulary of the system.
"""
from __future__ import annotations

from enum import Enum


class Timeframe(str, Enum):
    """Supported candlestick intervals.

    The string value is exactly the ``interval`` token expected by the Binance
    Spot REST ``/api/v3/klines`` endpoint and the kline WebSocket streams.
    """

    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H2 = "2h"
    H4 = "4h"
    H6 = "6h"
    H12 = "12h"
    D1 = "1d"

    @property
    def milliseconds(self) -> int:
        """Duration of one candle of this timeframe, in milliseconds."""
        unit = self.value[-1]
        amount = int(self.value[:-1])
        factor = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}[unit]
        return amount * factor

    @classmethod
    def from_value(cls, value: str) -> "Timeframe":
        for tf in cls:
            if tf.value == value:
                return tf
        raise ValueError(f"Unsupported timeframe: {value!r}")


class SignalType(str, Enum):
    """Directional decision emitted by the signal engine.

    SHORT is intentionally absent: Spot trading is long/flat only in the
    initial phases of the project.
    """

    LONG = "LONG"
    NEUTRAL = "NEUTRAL"
    NO_TRADE = "NO_TRADE"


class ScoreClass(str, Enum):
    """Confluence-strength buckets.

    IMPORTANT: this classification describes only how many of the system's
    conditions align. It is NOT a probability of profit.
    """

    NO_TRADE = "NO_TRADE"      # 0-39
    WEAK = "WEAK"              # 40-59
    MODERATE = "MODERATE"      # 60-74
    STRONG = "STRONG"          # 75-84
    VERY_STRONG = "VERY_STRONG"  # 85-100

    @classmethod
    def from_score(cls, score: float) -> "ScoreClass":
        if score < 40:
            return cls.NO_TRADE
        if score < 60:
            return cls.WEAK
        if score < 75:
            return cls.MODERATE
        if score < 85:
            return cls.STRONG
        return cls.VERY_STRONG


class TradingMode(str, Enum):
    """Execution context. LIVE is deliberately a disabled sentinel."""

    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    BINANCE_DEMO = "BINANCE_DEMO"
    LIVE_DISABLED = "LIVE_DISABLED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SymbolStatus(str, Enum):
    """Trading status reported by exchangeInfo (subset we care about)."""

    TRADING = "TRADING"
    BREAK = "BREAK"
    HALT = "HALT"
    AUCTION_MATCH = "AUCTION_MATCH"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def _missing_(cls, value):  # pragma: no cover - defensive
        return cls.UNKNOWN
