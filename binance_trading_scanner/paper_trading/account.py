"""Paper account: simulated balances only. No real money, ever.

The account's scalar state mirrors the backtester's Portfolio (cash, realized
PnL, fees, slippage, peak equity, drawdown) so both share one accounting model.
``AccountView`` is the read-only projection the dashboard renders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backtesting.portfolio import Portfolio
from backtesting.trade import Position


@dataclass
class AccountView:
    initial_balance: float
    cash: float
    equity: float
    available_balance: float
    realized_pnl: float
    unrealized_pnl: float
    fees: float
    slippage: float
    drawdown: float
    drawdown_pct: float
    open_positions: int

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def unrealized_pnl(position: Optional[Position], price: Optional[float]) -> float:
    if position is None or not position.is_open or price is None:
        return 0.0
    # Long only: (mark - effective entry) * remaining quantity.
    return (price - position.entry_eff) * position.remaining_qty


def build_account_view(portfolio: Portfolio, position: Optional[Position],
                       price: Optional[float], initial_balance: float) -> AccountView:
    mark = price if price is not None else (position.entry_eff if position else 0.0)
    equity = portfolio.cash + (position.remaining_qty * mark if (position and position.is_open) else 0.0)
    peak = max(portfolio.peak_equity, equity)
    dd = peak - equity
    dd_pct = (dd / peak * 100.0) if peak > 0 else 0.0
    return AccountView(
        initial_balance=initial_balance,
        cash=portfolio.cash,
        equity=equity,
        available_balance=portfolio.cash,     # Spot: only free cash can open new trades
        realized_pnl=portfolio.realized_pnl,
        unrealized_pnl=unrealized_pnl(position, price),
        fees=portfolio.fees_total,
        slippage=portfolio.slippage_total,
        drawdown=dd,
        drawdown_pct=dd_pct,
        open_positions=1 if (position and position.is_open) else 0,
    )
