"""Paper trading package.

A fully-internal simulated trading account that reuses the backtester's
Simulator (same execution, fees, slippage, stops, TPs, risk limits) driven
incrementally over closed candles, persisted to SQLite so it survives restarts.
NO real orders, NO API keys, NO live trading.
"""
from .account import AccountView, build_account_view
from .engine import RESET_TOKEN, PaperEngine, PaperStore
from .fills import Fill
from .journal import JournalEntry, JournalEventType
from .orders import Order, OrderSide, OrderStatus, OrderType
from .positions import PositionView

__all__ = [
    "PaperEngine", "PaperStore", "RESET_TOKEN",
    "AccountView", "build_account_view",
    "Order", "OrderSide", "OrderStatus", "OrderType",
    "Fill", "PositionView",
    "JournalEntry", "JournalEventType",
]
