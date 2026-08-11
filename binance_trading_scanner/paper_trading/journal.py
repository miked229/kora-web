"""Signal & event journal — an audit trail of everything the paper trader does.

Records ALL signals (LONG / NEUTRAL / NO_TRADE) with raw/final score and
blocked_by, plus every order, fill, position open, exit and risk block. Nothing
here is a secret; it is a plain audit log.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class JournalEventType(str, Enum):
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"
    POSITION_OPEN = "POSITION_OPEN"
    EXIT = "EXIT"
    RISK_BLOCKED = "RISK_BLOCKED"
    RESET = "RESET"
    ERROR = "ERROR"


@dataclass
class JournalEntry:
    id: Optional[int]
    timestamp: int
    symbol: str
    timeframe: str
    event_type: JournalEventType
    signal: Optional[str] = None
    setup: Optional[str] = None
    raw_score: Optional[float] = None
    final_score: Optional[float] = None
    blocked_by: Optional[List[str]] = None
    detail: Optional[str] = None
