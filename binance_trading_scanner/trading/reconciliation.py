"""Order reconciliation.

Never assume an order filled just because the API accepted the request (spec 14).
After submitting, and again on restart (spec 15), we query the exchange for the
authoritative status / executed quantity / average fill price / fees and update
the local store to match.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from core.logger import get_logger

from .store import LiveOrderStore

logger = get_logger("trading.reconciliation")


@dataclass
class ReconciledOrder:
    client_order_id: str
    status: str
    executed_qty: float
    avg_price: float
    fees: float


def _avg_price_and_fees(order: dict) -> tuple[float, float]:
    """Compute average fill price and total fees from an order's ``fills``."""
    fills = order.get("fills") or []
    total_qty = 0.0
    total_quote = 0.0
    fees = 0.0
    for f in fills:
        q = float(f.get("qty", 0))
        p = float(f.get("price", 0))
        total_qty += q
        total_quote += q * p
        fees += float(f.get("commission", 0))
    if total_qty > 0:
        return total_quote / total_qty, fees
    # Fall back to cummulativeQuoteQty / executedQty when fills aren't present.
    exec_qty = float(order.get("executedQty", 0) or 0)
    cq = float(order.get("cummulativeQuoteQty", 0) or 0)
    return (cq / exec_qty if exec_qty > 0 else 0.0), fees


def reconcile_from_response(store: LiveOrderStore, client_order_id: str, order: dict) -> ReconciledOrder:
    """Update the local store from an order response/query (authoritative)."""
    status = str(order.get("status", "UNKNOWN")).upper()
    executed_qty = float(order.get("executedQty", 0) or 0)
    avg_price, fees = _avg_price_and_fees(order)
    store.update_from_exchange(client_order_id, status, executed_qty, avg_price, fees, raw=order)
    return ReconciledOrder(client_order_id, status, executed_qty, avg_price, fees)


def reconcile_order(client, store: LiveOrderStore, symbol: str, client_order_id: str) -> ReconciledOrder:
    """Query the exchange for one order and update the store."""
    order = client.get_order(symbol, client_order_id)
    return reconcile_from_response(store, client_order_id, order)


def reconcile_all(client, store: LiveOrderStore) -> List[ReconciledOrder]:
    """On restart: reconcile every non-terminal local order with the exchange."""
    out: List[ReconciledOrder] = []
    for row in store.non_terminal_orders():
        try:
            out.append(reconcile_order(client, store, row["symbol"], row["client_order_id"]))
        except Exception as exc:  # keep going; a missing order is logged, not fatal
            logger.warning("reconcile failed for %s: %s", row["client_order_id"], exc)
    return out
