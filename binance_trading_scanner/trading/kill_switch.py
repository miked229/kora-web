"""Global kill switch, live-trading guard and the visible mode indicator.

Safety model (spec 8, 9, 17):
  * The kill switch defaults to ``TRADING_DISABLED`` and NEVER changes to LIVE on
    its own.
  * ``enable_live_trading`` requires THREE independent explicit conditions
    (two environment flags + a manual UI confirmation). If any is missing there
    are no live orders.
  * Even when all confirmations are present, this codebase ships NO mainnet order
    client, so live orders still cannot be placed. Live remains a future,
    deliberately-gated step.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TradingState(str, Enum):
    """Kill-switch state. Governs whether/where orders may be sent."""

    DISABLED = "TRADING_DISABLED"     # default — no orders anywhere
    TESTNET = "TRADING_TESTNET"       # orders only to Binance Spot Testnet
    LIVE = "TRADING_LIVE"             # real money — gated, and unimplemented here


@dataclass
class KillSwitch:
    """Runtime trading gate with an emergency stop."""

    state: TradingState = TradingState.DISABLED
    emergency_stopped: bool = False
    stop_reason: Optional[str] = None
    stopped_at: Optional[int] = None

    def allow_new_orders(self) -> bool:
        """True only if orders may currently be sent (testnet/live and not stopped)."""
        if self.emergency_stopped:
            return False
        return self.state in (TradingState.TESTNET, TradingState.LIVE)

    def set_state(self, state: TradingState, *, live_confirmation: bool = False) -> None:
        """Change the kill-switch state. Moving to LIVE requires the full guard."""
        if state is TradingState.LIVE and not enable_live_trading(live_confirmation):
            raise PermissionError(
                "refusing TRADING_LIVE: live-trading guard not satisfied "
                "(needs TRADING_LIVE=true, ENABLE_LIVE_CONFIRMATION=true and manual confirmation)"
            )
        self.state = state
        self.emergency_stopped = False
        self.stop_reason = None
        self.stopped_at = None

    def emergency_stop(self, reason: str) -> None:
        """STOP ALL TRADING: block new orders, keep positions for controlled exit."""
        self.emergency_stopped = True
        self.stop_reason = reason
        self.stopped_at = int(time.time() * 1000)

    def resume(self) -> None:
        self.emergency_stopped = False
        self.stop_reason = None
        self.stopped_at = None


def enable_live_trading(manual_confirmation: bool = False) -> bool:
    """Return True only when ALL explicit live conditions are present.

    Reads the environment fresh on every call (never cached), so live can never
    be silently latched on:
      * env ``TRADING_LIVE`` == "true"
      * env ``ENABLE_LIVE_CONFIRMATION`` == "true"
      * ``manual_confirmation`` passed from the Settings UI
    """
    env_live = os.getenv("TRADING_LIVE", "").strip().lower() == "true"
    env_confirm = os.getenv("ENABLE_LIVE_CONFIRMATION", "").strip().lower() == "true"
    return bool(env_live and env_confirm and manual_confirmation)


def mode_indicator(*, data_source: str, state: TradingState,
                   live_enabled: bool = False) -> str:
    """The permanent, unambiguous mode label shown in the dashboard (spec 17)."""
    if state is TradingState.LIVE and live_enabled:
        return "🔴 LIVE TRADING"
    if state is TradingState.TESTNET:
        return "🟡 TESTNET"
    if str(data_source).lower() == "live":
        return "🔵 LIVE DATA — NO ORDERS"
    return "🟢 DEMO"
