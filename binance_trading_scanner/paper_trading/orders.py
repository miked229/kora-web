"""Paper order records and enums. Internal only — never sent to any exchange."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    """A simulated order. No real order is ever placed."""

    id: Optional[int]
    symbol: str
    side: OrderSide
    type: OrderType
    quantity: float
    requested_price: Optional[float]
    filled_price: Optional[float]
    status: OrderStatus
    created_at: int
    filled_at: Optional[int]
    fees: float = 0.0
    slippage: float = 0.0
    reason: str = ""              # entry, TP1, TP2, STOP_LOSS, ...
    signal_time: Optional[int] = None

    def to_row(self) -> dict:
        return {
            "id": self.id, "symbol": self.symbol, "side": self.side.value,
            "type": self.type.value, "quantity": self.quantity,
            "requested_price": self.requested_price, "filled_price": self.filled_price,
            "status": self.status.value, "created_at": self.created_at,
            "filled_at": self.filled_at, "fees": self.fees, "slippage": self.slippage,
            "reason": self.reason, "signal_time": self.signal_time,
        }
