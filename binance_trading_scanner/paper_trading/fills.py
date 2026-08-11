"""Paper fill records — the executions that back each order (internal only)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Fill:
    id: Optional[int]
    order_id: Optional[int]
    symbol: str
    qty: float
    price: float           # effective fill price (after slippage)
    fees: float
    slippage: float
    timestamp: int
    reason: str            # entry, TP1, TP2, STOP_LOSS, INVALIDATION, END_OF_TEST

    def to_row(self) -> dict:
        return {
            "id": self.id, "order_id": self.order_id, "symbol": self.symbol,
            "qty": self.qty, "price": self.price, "fees": self.fees,
            "slippage": self.slippage, "timestamp": self.timestamp, "reason": self.reason,
        }
