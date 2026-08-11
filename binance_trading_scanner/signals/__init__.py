"""Signals package.

Confluence-based, explainable signal engine. Converts Phase-2 indicators and
market structure into a LONG / NEUTRAL / NO_TRADE decision with a 0-100
confluence score, a provisional trade plan, and full reason/warning/invalidation
explainability. No trading, no orders, no optimisation.
"""
from .scoring import (
    BlockResult,
    BlockWeights,
    EngineConfig,
    MarketSnapshot,
    compute_snapshot,
    detect_setup,
)
from .signal_engine import SignalEngine, format_signal

__all__ = [
    "SignalEngine",
    "format_signal",
    "EngineConfig",
    "BlockWeights",
    "BlockResult",
    "MarketSnapshot",
    "compute_snapshot",
    "detect_setup",
]
