"""Trading safety & execution package.

Real Binance market data plus SAFE, gated execution for Binance Spot **Testnet**.
There is no mainnet order client, the kill switch defaults to TRADING_DISABLED,
and live trading is guarded behind multiple explicit confirmations. NO real
money is enabled in this phase.
"""
from .execution_backend import (
    ExecutionBackend,
    ExecutionDecision,
    FuturesTestnetExecution,
    SpotTestnetExecution,
)
from .executor import ExecutionResult, SafeExecutor
from .kill_switch import KillSwitch, TradingState, enable_live_trading, mode_indicator
from .overtrading import OvertradingConfig, OvertradingGuard
from .reconciliation import ReconciledOrder, reconcile_all, reconcile_from_response, reconcile_order
from .safety import (
    DEFAULT_WHITELIST,
    OrderIntent,
    PortfolioState,
    SafetyConfig,
    SafetyResult,
    check_order,
    client_order_id,
    conform_to_filters,
)
from .store import LiveOrderStore
from .testnet_session import TestnetSession, run_testnet_session

__all__ = [
    "SafeExecutor", "ExecutionResult",
    "KillSwitch", "TradingState", "enable_live_trading", "mode_indicator",
    "SafetyConfig", "SafetyResult", "OrderIntent", "PortfolioState",
    "check_order", "client_order_id", "conform_to_filters", "DEFAULT_WHITELIST",
    "LiveOrderStore",
    "TestnetSession", "run_testnet_session",
    "ReconciledOrder", "reconcile_order", "reconcile_all", "reconcile_from_response",
    "ExecutionBackend", "ExecutionDecision", "SpotTestnetExecution", "FuturesTestnetExecution",
    "OvertradingConfig", "OvertradingGuard",
]
