"""Read-only position projection for display.

Reuses the backtester's ``Position`` (no duplicated position logic) and adds a
mark-to-market view with unrealized PnL and R multiple.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backtesting.trade import Position


@dataclass
class PositionView:
    symbol: str
    side: str
    quantity: float
    average_entry: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    stop_loss: float
    take_profit_1: Optional[float]
    take_profit_2: Optional[float]
    r_multiple: float
    opened_at: int
    duration_ms: int

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def build_position_view(pos: Position, price: float, now_ms: int) -> PositionView:
    unreal = (price - pos.entry_eff) * pos.remaining_qty
    r = unreal / pos.initial_risk if pos.initial_risk > 0 else 0.0
    return PositionView(
        symbol=pos.symbol, side="LONG", quantity=pos.remaining_qty,
        average_entry=pos.entry_eff, current_price=price,
        unrealized_pnl=unreal, realized_pnl=pos.realized_pnl,
        stop_loss=pos.stop, take_profit_1=pos.tp1, take_profit_2=pos.tp2,
        r_multiple=r, opened_at=pos.entry_time,
        duration_ms=max(now_ms - pos.entry_time, 0),
    )
