"""Typed exception hierarchy.

Every failure mode the application deliberately handles has a dedicated type so
callers (scanner loop, dashboard, tests) can react precisely instead of
catching bare ``Exception``.
"""
from __future__ import annotations


class ScannerError(Exception):
    """Base class for all application-specific errors."""


class ConfigurationError(ScannerError):
    """Invalid or missing configuration."""


# --- Binance / networking -------------------------------------------------

class BinanceError(ScannerError):
    """Base class for anything originating from the Binance API layer."""


class BinanceAPIError(BinanceError):
    """Non-2xx response from Binance carrying its error code/message.

    See https://developers.binance.com for the canonical error-code list.
    """

    def __init__(self, status_code: int, code: int | None = None, message: str = ""):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"HTTP {status_code} (code={code}): {message}")


class RateLimitError(BinanceError):
    """HTTP 429 (rate limit) or 418 (IP auto-ban). ``retry_after`` in seconds."""

    def __init__(self, status_code: int, retry_after: float | None = None):
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(
            f"Rate limited (HTTP {status_code}); retry_after={retry_after}s"
        )


class BinanceConnectionError(BinanceError):
    """Network-level failure (timeout, DNS, refused, TLS)."""


# --- Data integrity -------------------------------------------------------

class DataValidationError(ScannerError):
    """Market data failed validation (gaps, duplicates, bad OHLC, NaNs)."""


class InvalidSymbolError(ScannerError):
    """Symbol is not present / not TRADING in exchangeInfo."""


class InsufficientDataError(ScannerError):
    """Not enough candles to compute the requested indicator/signal."""


# --- Trading / risk -------------------------------------------------------

class RiskRuleViolation(ScannerError):
    """A prospective order would breach a configured risk rule."""


class InsufficientBalanceError(ScannerError):
    """Not enough (paper/demo) balance to open the position."""


class LiveTradingDisabledError(ScannerError):
    """Guard: live order placement is disabled and must never execute."""
