"""SafeExecutor — the one place an order can be sent, behind every guard.

Order of enforcement for every intent (spec 7, 8, 13, 14):
  1. idempotency  — refuse if this logical order was already submitted
  2. kill switch  — no orders unless TESTNET/LIVE and not emergency-stopped
  3. safety       — whitelist, filters, balance, risk, exposure, duplicate
  4. routing      — TESTNET -> testnet client only; LIVE -> guarded AND has no
                    mainnet client, so it can never place a real order here
  5. reconcile    — query the exchange for the true status (never assume filled)

DISABLED / DEMO / LIVE_DATA / PAPER never reach the exchange through this class.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from core.exceptions import LiveTradingDisabledError
from core.logger import get_logger
from core.models import SymbolFilters

from .kill_switch import KillSwitch, TradingState, enable_live_trading
from .reconciliation import ReconciledOrder, reconcile_from_response, reconcile_order, reconcile_all
from .safety import OrderIntent, PortfolioState, SafetyConfig, check_order, client_order_id
from .store import LiveOrderStore

logger = get_logger("trading.executor")


@dataclass
class ExecutionResult:
    status: str                       # BLOCKED | DUPLICATE | SUBMITTED
    submitted: bool
    client_order_id: Optional[str] = None
    blocked_reason: Optional[str] = None
    reconciled: Optional[ReconciledOrder] = None


class SafeExecutor:
    def __init__(self, kill_switch: KillSwitch, safety_cfg: SafetyConfig,
                 store: LiveOrderStore, *, testnet_client=None,
                 live_confirmation: bool = False) -> None:
        self.kill = kill_switch
        self.safety_cfg = safety_cfg
        self.store = store
        self.testnet_client = testnet_client
        self.live_confirmation = live_confirmation

    # -- submission ---------------------------------------------------------

    def submit(self, intent: OrderIntent, filters: Optional[SymbolFilters],
               portfolio_state: PortfolioState) -> ExecutionResult:
        cid = client_order_id(intent)

        # 1. idempotency — never send the same logical order twice.
        if self.store.exists(cid):
            return ExecutionResult("DUPLICATE", False, cid, "already submitted")

        # 2. kill switch.
        if not self.kill.allow_new_orders():
            reason = ("emergency_stopped" if self.kill.emergency_stopped
                      else f"kill switch: {self.kill.state.value}")
            self.store.log_event("BLOCKED", f"{cid}: {reason}")
            return ExecutionResult("BLOCKED", False, cid, reason)

        # 3. safety checks.
        sres = check_order(intent, filters, portfolio_state, self.safety_cfg,
                           self.store.known_client_ids())
        if not sres.ok:
            self.store.log_event("BLOCKED", f"{cid}: {sres.reason}")
            return ExecutionResult("BLOCKED", False, cid, sres.reason)

        # 4. routing.
        if self.kill.state is TradingState.TESTNET:
            return self._submit_testnet(intent, cid)

        if self.kill.state is TradingState.LIVE:
            if not enable_live_trading(self.live_confirmation):
                self.store.log_event("BLOCKED", f"{cid}: live guard not satisfied")
                return ExecutionResult("BLOCKED", False, cid, "live-trading guard not satisfied")
            # Even fully-confirmed, there is no mainnet order client in this codebase.
            raise LiveTradingDisabledError(
                "live order placement is intentionally not implemented in this phase")

        return ExecutionResult("BLOCKED", False, cid, "trading disabled")

    def _submit_testnet(self, intent: OrderIntent, cid: str) -> ExecutionResult:
        from core.exceptions import BinanceError

        if self.testnet_client is None:
            return ExecutionResult("BLOCKED", False, cid, "no testnet client configured")
        self.store.record_submitted(cid, "TESTNET", intent.symbol, intent.side,
                                    intent.quantity, intent.signal_timestamp, status="NEW")
        try:
            resp = self.testnet_client.new_market_order(intent.symbol, intent.side, intent.quantity, cid)
        except BinanceError as exc:
            # Exchange rejected the order — mark it, never assume it worked.
            self.store.update_from_exchange(cid, "REJECTED", 0.0, 0.0, 0.0, raw={"error": str(exc)})
            self.store.log_event("REJECTED", f"{cid}: {exc}")
            return ExecutionResult("REJECTED", False, cid, str(exc))
        # Reconcile from the response, then confirm with an explicit query
        # (never assume filled just because the request was accepted).
        rec = reconcile_from_response(self.store, cid, resp)
        try:
            rec = reconcile_order(self.testnet_client, self.store, intent.symbol, cid)
        except Exception as exc:  # pragma: no cover - query best-effort
            logger.warning("post-submit reconcile query failed for %s: %s", cid, exc)
        self.store.log_event("SUBMITTED", f"{cid}: {rec.status} exec={rec.executed_qty}")
        return ExecutionResult("SUBMITTED", True, cid, None, rec)

    # -- emergency controls -------------------------------------------------

    def emergency_stop(self, reason: str, *, cancel_open: bool = False,
                       symbol: Optional[str] = None) -> None:
        """STOP ALL TRADING: block new orders; keep positions for controlled exit."""
        self.kill.emergency_stop(reason)
        self.store.log_event("EMERGENCY_STOP", reason)
        if cancel_open and symbol:
            self.cancel_open_orders(symbol)

    def cancel_open_orders(self, symbol: str) -> list:
        """Separate action: cancel resting orders (testnet only) without stopping."""
        if self.kill.state is TradingState.TESTNET and self.testnet_client is not None:
            res = self.testnet_client.cancel_all_open_orders(symbol)
            self.store.log_event("CANCEL_OPEN", symbol)
            return res
        return []

    # -- crash recovery -----------------------------------------------------

    def recover(self) -> List[ReconciledOrder]:
        """On restart, reconcile local non-terminal orders with the exchange."""
        if self.kill.state is TradingState.TESTNET and self.testnet_client is not None:
            recs = reconcile_all(self.testnet_client, self.store)
            self.store.log_event("RECOVER", f"reconciled {len(recs)} order(s)")
            return recs
        return []
