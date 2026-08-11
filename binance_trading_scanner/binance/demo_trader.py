"""Binance Spot Demo Mode / Testnet trader.

STATUS: scaffolding only. NOT implemented in Phase 1 and MUST NOT place real
orders. This module will only ever target the Binance Spot **Testnet**
(https://testnet.binance.vision) and requires an explicit opt-in plus testnet
credentials supplied via environment variables.

LIVE trading is intentionally unavailable. There is no code path here that can
send an order to production, and none may be added without explicit user
approval (see CLAUDE.md).
"""
from __future__ import annotations

from core.exceptions import LiveTradingDisabledError
from core.logger import get_logger

logger = get_logger("binance.demo_trader")


class DemoTrader:
    """Placeholder for the Testnet order interface (later phase)."""

    def __init__(self) -> None:
        logger.info("DemoTrader initialised (inactive — no orders will be sent)")

    def place_order(self, *args, **kwargs):  # pragma: no cover - guard
        raise LiveTradingDisabledError(
            "Demo/live order placement is not enabled in this phase."
        )
