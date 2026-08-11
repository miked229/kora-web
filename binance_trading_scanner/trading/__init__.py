"""Trading safety & execution package.

Real Binance market data plus SAFE, gated execution for Binance Spot **Testnet**.
There is no mainnet order client, the kill switch defaults to TRADING_DISABLED,
and live trading is guarded behind multiple explicit confirmations. NO real
money is enabled in this phase.
"""
from .executor import ExecutionResult, SafeExecutor
from .kill_switch import KillSwitch, TradingState, enable_live_trading, mode_indicator
from .reconciliation import ReconciledOrder, reconcile_all, reconcile_from_response, reconcile_order
from .safety import (
    DEFAULT_WHITELIST,
    OrderIntent,
    PortfolioState,
    SafetyConfig,
    SafetyResult,
    check_order,
    client_order_id,
)
from .store import LiveOrderStore

__all__ = [
    "SafeExecutor", "ExecutionResult",
    "KillSwitch", "TradingState", "enable_live_trading", "mode_indicator",
    "SafetyConfig", "SafetyResult", "OrderIntent", "PortfolioState",
    "check_order", "client_order_id", "DEFAULT_WHITELIST",
    "LiveOrderStore",
    "ReconciledOrder", "reconcile_order", "reconcile_all", "reconcile_from_response",
]
