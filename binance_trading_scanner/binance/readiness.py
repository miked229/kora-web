"""Headless readiness checks — NO Streamlit, NO orders, NO live trading.

This module is deliberately free of any Streamlit import so ``--testnet-check``
and ``--live-check`` run completely headless. It never places an order and never
prints credentials.

Import graph is intentionally minimal (config, binance.testnet_client,
core.models, trading.safety) — none of which import Streamlit.
"""
from __future__ import annotations

import time
from typing import Callable, List, Optional, Tuple

from binance.testnet_client import TESTNET_BASE, BinanceTestnetClient
from config import Settings, get_settings
from core.models import SymbolInfo
from trading.safety import DEFAULT_WHITELIST


def _fmt(name: str, status: str, detail: str = "") -> str:
    return f"{name:<22} {status}" + (f" — {detail}" if detail else "")


def testnet_check(
    *,
    client: Optional[BinanceTestnetClient] = None,
    credentials: Optional[Tuple[Optional[str], Optional[str]]] = None,
    connect: bool = True,
    out: Callable[[str], None] = print,
) -> int:
    """Print a Testnet readiness report and return an exit code (0 ready, 1 not).

    Places NO orders. ``client``/``credentials`` may be injected for testing.
    """
    settings = get_settings()
    lines: List[str] = ["", "TESTNET READINESS CHECK", ""]
    ready = True
    reasons: List[str] = []

    def fail(reason: str) -> None:
        nonlocal ready
        ready = False
        reasons.append(reason)

    # Configuration
    lines.append(_fmt("Configuration:", "OK", f"BINANCE_ENV={settings.binance_env}"))

    # Credentials (never printed)
    key, secret = credentials if credentials is not None else Settings.get_api_credentials()
    has_creds = bool(key and secret)
    lines.append(_fmt("Credentials:", "PRESENT" if has_creds else "MISSING",
                      "" if has_creds else "set BINANCE_API_KEY/SECRET (testnet) in .env"))
    if not has_creds:
        fail("testnet credentials not available")

    # Endpoint
    lines.append(_fmt("Endpoint:", "OK", TESTNET_BASE))

    # Connectivity / account / filters — only if we can build a client
    if has_creds and connect:
        try:
            tc = client or BinanceTestnetClient(key, secret, base_url=TESTNET_BASE)
        except Exception as exc:
            tc = None
            lines.append(_fmt("Connectivity:", "FAIL", f"{type(exc).__name__}: {exc}"))
            fail("could not construct testnet client")
        if tc is not None:
            try:
                tc.ping()
                lines.append(_fmt("Connectivity:", "OK", "testnet reachable"))
            except Exception as exc:
                lines.append(_fmt("Connectivity:", "FAIL", f"{type(exc).__name__}: {exc}"))
                fail("testnet not reachable")

            try:
                drift = abs(int(time.time() * 1000) - tc.server_time())
                ok = drift < 5000
                lines.append(_fmt("Server time:", "OK" if ok else "WARN", f"drift={drift}ms"))
                if not ok:
                    fail(f"clock drift {drift}ms too large")
            except Exception as exc:
                lines.append(_fmt("Server time:", "FAIL", f"{type(exc).__name__}: {exc}"))

            try:
                acct = tc.account()
                can_trade = bool(acct.get("canTrade"))
                lines.append(_fmt("Account permissions:", "OK" if can_trade else "FAIL",
                                  "canTrade=True; must NOT have withdrawal permission"
                                  if can_trade else "canTrade is False"))
                if not can_trade:
                    fail("account cannot trade")
            except Exception as exc:
                lines.append(_fmt("Account permissions:", "FAIL", f"{type(exc).__name__}: {exc}"))
                fail("could not read account")

            sym = sorted(DEFAULT_WHITELIST)[0]
            try:
                info = tc.exchange_info(sym)
                entry = next((s for s in info.get("symbols", []) if s.get("symbol") == sym), None)
                if entry is None:
                    lines.append(_fmt("Exchange info:", "FAIL", f"{sym} not found"))
                    fail(f"{sym} missing from exchangeInfo")
                else:
                    si = SymbolInfo.from_binance(entry)
                    lines.append(_fmt("Exchange info:", "OK", f"{sym} status={si.status.value}"))
                    f = si.filters
                    lines.append(_fmt("Symbol filters:", "OK",
                                      f"tick={f.tick_size} step={f.step_size} "
                                      f"minQty={f.min_qty} minNotional={f.min_notional}"))
            except Exception as exc:
                lines.append(_fmt("Exchange info:", "FAIL", f"{type(exc).__name__}: {exc}"))
                fail("could not read exchangeInfo")
            if client is None:
                tc.close()
    else:
        lines.append(_fmt("Connectivity:", "SKIPPED", "no credentials — not attempted"))

    lines.append("")
    if ready:
        lines.append("RESULT: TESTNET READY")
    else:
        lines.append("RESULT: TESTNET NOT READY — " + "; ".join(reasons))
    lines.append("(No orders were placed.)")
    lines.append("")
    for ln in lines:
        out(ln)
    return 0 if ready else 1


def live_check(out: Callable[[str], None] = print) -> int:
    """Always reports that live trading is disabled (no mainnet order client)."""
    from trading.kill_switch import enable_live_trading

    out("")
    out("LIVE TRADING CHECK")
    out("")
    out("RESULT: LIVE TRADING DISABLED")
    out(f"  enable_live_trading(manual=True) = {enable_live_trading(True)}")
    out("  Reason: no mainnet order client exists in this build; real orders "
        "cannot be placed regardless of configuration.")
    out("")
    return 0
