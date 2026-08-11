"""Backtesting package.

Independent, event-driven, candle-by-candle backtester for the existing
SignalEngine. No look-ahead, realistic fees/slippage, conservative intrabar
assumptions, risk-based sizing, portfolio/equity/drawdown accounting, honest
metrics and in-sample/out-of-sample splitting. No trading, no optimisation.
"""
from .data_split import Split, split_in_out, walk_forward_windows
from .engine import BacktestConfig, BacktestEngine, BacktestResult, check_data_quality
from .execution import AmbiguityPolicy, EntryTiming, ExecutionConfig
from .metrics import Metrics, compute_metrics
from .portfolio import Portfolio, RiskLimits, SizingResult, position_size
from .report import format_report, signal_stats, summary_dict, trade_distribution
from .trade import Leg, Position, Trade

__all__ = [
    "BacktestEngine", "BacktestConfig", "BacktestResult", "check_data_quality",
    "ExecutionConfig", "EntryTiming", "AmbiguityPolicy",
    "Portfolio", "RiskLimits", "SizingResult", "position_size",
    "Trade", "Position", "Leg",
    "Metrics", "compute_metrics",
    "split_in_out", "walk_forward_windows", "Split",
    "format_report", "summary_dict", "trade_distribution", "signal_stats",
]
