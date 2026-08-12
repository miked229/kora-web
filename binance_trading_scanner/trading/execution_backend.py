"""Execution backends: WHERE and WHETHER a signal can actually be executed.

The signal engine is symmetric (LONG + SHORT). Execution is NOT: **Binance Spot
cannot short natively**, so a SHORT signal must never be turned into a SELL Spot
order. This module abstracts that decision so the rest of the system asks a
backend "can you execute this direction?" instead of hard-coding LONG.

Backends in this build:

* ``SpotTestnetExecution`` — the only backend that can place orders. It executes
  LONG on Binance Spot Testnet and **refuses SHORT** ("SHORT EXECUTION BACKEND
  NOT ENABLED FOR SPOT"). SHORT signals are still produced, back-tested and paper
  traded; they are simply surfaced, never sent as a spot SELL-to-open.
* ``FuturesTestnetExecution`` — a placeholder for the future path that *could*
  short. It is deliberately **not available** in this build (there is no futures
  order client), so it refuses every direction. This is the mirror of the
  "no mainnet order client exists" guarantee: real SHORT execution cannot happen.

Nothing here places an order; a backend only *decides*. The actual routing stays
in ``trading.SafeExecutor`` (kill switch -> safety -> Testnet client).
"""
from __future__ import annotations

from dataclasses import dataclass

from core.enums import SignalType


@dataclass(frozen=True)
class ExecutionDecision:
    """Whether a direction can be executed, with an explainable reason."""

    allowed: bool
    reason: str = ""
    note: str = ""            # e.g. "SHORT SIGNAL AVAILABLE" for the dashboard


class ExecutionBackend:
    """Base class. Subclasses declare their market and short capability."""

    name: str = "base"
    market: str = "NONE"          # "SPOT" | "FUTURES"
    supports_short: bool = False
    available: bool = False       # can this backend actually place orders now?

    def decide(self, direction: SignalType) -> ExecutionDecision:
        if not self.available:
            return ExecutionDecision(
                False, f"{self.name} execution backend not enabled in this build")
        if not direction.is_directional:
            return ExecutionDecision(False, "no directional signal to execute")
        if direction is SignalType.SHORT and not self.supports_short:
            return ExecutionDecision(
                False,
                "SHORT EXECUTION BACKEND NOT ENABLED FOR SPOT",
                note="SHORT SIGNAL AVAILABLE",
            )
        return ExecutionDecision(True)

    # Convenience for dashboards / status lines.
    def short_status(self) -> str:
        if self.supports_short and self.available:
            return "SHORT EXECUTION ENABLED"
        return "SHORT SIGNAL AVAILABLE — SHORT EXECUTION BACKEND NOT ENABLED FOR SPOT"


class SpotTestnetExecution(ExecutionBackend):
    """Binance Spot Testnet: LONG only. SHORT is signalled but never executed."""

    name = "spot-testnet"
    market = "SPOT"
    supports_short = False
    available = True


class FuturesTestnetExecution(ExecutionBackend):
    """Futures Testnet placeholder — could short, but is NOT enabled in this build.

    Kept so the abstraction and the dashboard can show the intended future path
    without ever enabling a real short. ``available`` is False, so ``decide``
    refuses every direction.
    """

    name = "futures-testnet"
    market = "FUTURES"
    supports_short = True
    available = False
