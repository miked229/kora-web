"""Professional logging setup.

A single ``configure_logging`` entry point installs a consistent formatter on
the root logger; ``get_logger`` returns namespaced child loggers. Log records
carry a compact, greppable format:

    2026-08-11T12:00:00Z | INFO     | binance.market_data | fetched klines | BTCUSDT 15m n=500

Optional ``symbol`` / ``timeframe`` context can be attached via the ``extra``
argument and is rendered when present.

Security: this module NEVER logs API keys or secrets. Callers must not pass
credentials into log messages.
"""
from __future__ import annotations

import logging
import sys
import time
from typing import Optional

_CONFIGURED = False

_SENSITIVE_HINTS = ("api_key", "api_secret", "apikey", "secret", "signature", "token")


class _ContextFormatter(logging.Formatter):
    """Formatter that appends optional symbol/timeframe context."""

    default_time_format = "%Y-%m-%d %H:%M:%S"
    default_msec_format = "%s.%03d UTC"

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        symbol = getattr(record, "symbol", None)
        timeframe = getattr(record, "timeframe", None)
        ctx = " ".join(str(x) for x in (symbol, timeframe) if x)
        return f"{base} | {ctx}" if ctx else base


def _redaction_filter(record: logging.LogRecord) -> bool:
    """Best-effort guard against accidentally logging obvious secrets."""
    try:
        msg = str(record.getMessage()).lower()
    except Exception:  # pragma: no cover - defensive
        return True
    if any(hint in msg and "=" in msg for hint in _SENSITIVE_HINTS):
        record.msg = "[REDACTED: message appeared to contain a credential]"
        record.args = ()
    return True


def configure_logging(level: str = "INFO") -> None:
    """Idempotently configure the root logger. Safe to call multiple times."""
    global _CONFIGURED
    root = logging.getLogger()
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    root.setLevel(numeric)

    if _CONFIGURED:
        # Only adjust level on subsequent calls (e.g. user changes it in UI).
        for h in root.handlers:
            h.setLevel(numeric)
        return

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(numeric)
    formatter = _ContextFormatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    formatter.converter = time.gmtime  # log timestamps in UTC
    handler.setFormatter(formatter)
    handler.addFilter(_redaction_filter)

    root.handlers.clear()
    root.addHandler(handler)
    # Quiet noisy third-party libraries unless we are debugging.
    for noisy in ("httpx", "httpcore", "websockets", "urllib3"):
        logging.getLogger(noisy).setLevel(max(numeric, logging.WARNING))

    _CONFIGURED = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a namespaced logger, ensuring configuration has run once."""
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name if name else "scanner")
