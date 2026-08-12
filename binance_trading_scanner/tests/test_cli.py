"""Tests for the headless CLI checks (--testnet-check / --live-check).

Proves the checks run completely headless (no Streamlit import, no
ScriptRunContext warnings), exit cleanly, place no orders, and keep LIVE
disabled.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from binance import readiness
from trading.kill_switch import enable_live_trading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(args, timeout=90):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=timeout)


# ---- subprocess: headless, no Streamlit, clean exit ----------------------

def test_cli_testnet_check_is_headless():
    r = _run(["cli.py", "--testnet-check"])
    assert "TESTNET READINESS CHECK" in r.stdout
    assert "RESULT:" in r.stdout
    assert "ScriptRunContext" not in (r.stdout + r.stderr)      # no Streamlit warnings
    assert r.returncode in (0, 1)                                # clean exit


def test_cli_live_check_is_headless():
    r = _run(["cli.py", "--live-check"])
    assert "LIVE TRADING DISABLED" in r.stdout
    assert "ScriptRunContext" not in (r.stdout + r.stderr)
    assert r.returncode == 0


def test_app_testnet_check_no_scriptruncontext():
    # app.py must delegate to the headless path and never start Streamlit.
    r = _run(["app.py", "--testnet-check"])
    assert "TESTNET READINESS CHECK" in r.stdout
    assert "ScriptRunContext" not in (r.stdout + r.stderr)
    assert "missing ScriptRunContext" not in (r.stdout + r.stderr)
    assert r.returncode in (0, 1)


def test_app_live_check_no_scriptruncontext():
    r = _run(["app.py", "--live-check"])
    assert "LIVE TRADING DISABLED" in r.stdout
    assert "ScriptRunContext" not in (r.stdout + r.stderr)
    assert r.returncode == 0


def test_checks_do_not_import_streamlit():
    # Run the checks in a fresh interpreter and assert streamlit was never imported.
    code = (
        "import sys, cli;"
        "cli.main(['--testnet-check']);"
        "cli.main(['--live-check']);"
        "assert 'streamlit' not in sys.modules, 'streamlit was imported';"
        "print('NO_STREAMLIT_OK')"
    )
    r = _run(["-c", code])
    assert r.returncode == 0, r.stderr
    assert "NO_STREAMLIT_OK" in r.stdout


# ---- in-process: no orders, LIVE disabled --------------------------------

class _MockTestnet:
    """Readiness-only mock; fails loudly if an order is ever attempted."""

    def __init__(self):
        self.order_attempted = False

    def ping(self):
        return True

    def server_time(self):
        return int(time.time() * 1000)

    def account(self):
        return {"canTrade": True}

    def exchange_info(self, symbol=None):
        return {"symbols": [{
            "symbol": symbol or "BTCUSDT", "status": "TRADING",
            "baseAsset": "BTC", "quoteAsset": "USDT",
            "baseAssetPrecision": 8, "quoteAssetPrecision": 8,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
                {"filterType": "LOT_SIZE", "stepSize": "0.00001000",
                 "minQty": "0.00001000", "maxQty": "9000.00000000"},
                {"filterType": "NOTIONAL", "minNotional": "5.00000000"},
            ]}]}

    def new_market_order(self, *a, **k):
        self.order_attempted = True
        raise AssertionError("an order was placed during a readiness check!")

    def close(self):
        pass


def test_testnet_check_places_no_orders_and_reports_ready():
    tc = _MockTestnet()
    lines = []
    rc = readiness.testnet_check(client=tc, credentials=("KEY", "SECRET"), out=lines.append)
    text = "\n".join(lines)
    assert rc == 0
    assert "RESULT: TESTNET READY" in text
    assert "No orders were placed" in text
    assert tc.order_attempted is False                    # never attempted an order


def test_testnet_check_not_ready_without_credentials():
    lines = []
    rc = readiness.testnet_check(credentials=(None, None), connect=False, out=lines.append)
    text = "\n".join(lines)
    assert rc == 1
    assert "TESTNET NOT READY" in text
    assert "credentials not available" in text


def test_live_check_reports_disabled_and_places_nothing():
    lines = []
    rc = readiness.live_check(out=lines.append)
    text = "\n".join(lines)
    assert rc == 0
    assert "LIVE TRADING DISABLED" in text


@pytest.mark.parametrize("env", [{}, {"TRADING_LIVE": "true"}, {"ENABLE_LIVE_CONFIRMATION": "true"}])
def test_live_remains_disabled(monkeypatch, env):
    monkeypatch.delenv("TRADING_LIVE", raising=False)
    monkeypatch.delenv("ENABLE_LIVE_CONFIRMATION", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Never true unless BOTH env flags AND manual confirmation are present.
    assert enable_live_trading(True) is False
