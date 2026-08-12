"""Binance Spot **Testnet** signed client.

A deliberately separate adapter from the public mainnet client. It targets ONLY
``https://testnet.binance.vision`` and refuses to be constructed against a
mainnet host, so testnet and mainnet endpoints can never be mixed (spec 5).

Credentials come exclusively from the environment and are NEVER logged, printed,
returned to the frontend, or stored. The signature and secret never appear in
any log line.

There is intentionally NO mainnet order client anywhere in this codebase, so
there is no code path that can place a real-money order (spec: LIVE stays
disabled).
"""
from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse
from typing import Optional

import httpx

from core.exceptions import BinanceAPIError, ConfigurationError
from core.logger import get_logger

logger = get_logger("binance.testnet")

TESTNET_BASE = "https://testnet.binance.vision"
_USER_AGENT = "binance-trading-scanner/0.1 (testnet)"


def _is_testnet_host(base_url: str) -> bool:
    host = urllib.parse.urlparse(base_url).hostname or ""
    return host.endswith("testnet.binance.vision")


class BinanceTestnetClient:
    """Signed Spot Testnet client. Testnet only — refuses mainnet hosts."""

    def __init__(self, api_key: str, api_secret: str, *, base_url: str = TESTNET_BASE,
                 recv_window: int = 5000, timeout: float = 10.0,
                 client: Optional[httpx.Client] = None) -> None:
        if not _is_testnet_host(base_url):
            raise ConfigurationError(
                f"BinanceTestnetClient refuses non-testnet host: {base_url!r}. "
                "Testnet and mainnet endpoints must never be mixed."
            )
        if not api_key or not api_secret:
            raise ConfigurationError("testnet API key/secret are required (from environment)")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret.encode()
        self.recv_window = recv_window
        self.environment = "TESTNET"
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT, "X-MBX-APIKEY": api_key},
        )

    # -- construction from environment (never from code/args in callers) ----

    @classmethod
    def from_env(cls, get_credentials, **kwargs) -> "BinanceTestnetClient":
        key, secret = get_credentials()
        if not key or not secret:
            raise ConfigurationError("testnet credentials missing in environment")
        return cls(key, secret, **kwargs)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover
            pass

    # -- signing ------------------------------------------------------------

    def _sign(self, params: dict) -> dict:
        params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": self.recv_window}
        query = urllib.parse.urlencode(params, doseq=True)
        signature = hmac.new(self._api_secret, query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    def _signed(self, method: str, path: str, params: Optional[dict] = None):
        signed = self._sign(params or {})
        url = f"{self.base_url}{path}"
        try:
            resp = self._client.request(method, url, params=signed,
                                        headers={"X-MBX-APIKEY": self._api_key})
        except httpx.HTTPError as exc:
            raise BinanceAPIError(0, message=f"testnet network error: {exc}") from exc
        if resp.status_code >= 400:
            code, msg = _err(resp)
            # Never include credentials/signature in the raised message.
            raise BinanceAPIError(resp.status_code, code, _redact(msg))
        return resp.json()

    def _public(self, path: str, params: Optional[dict] = None):
        resp = self._client.get(f"{self.base_url}{path}", params=params)
        if resp.status_code >= 400:
            code, msg = _err(resp)
            raise BinanceAPIError(resp.status_code, code, msg)
        return resp.json()

    # -- endpoints ----------------------------------------------------------

    def ping(self) -> bool:
        self._public("/api/v3/ping")
        return True

    def server_time(self) -> int:
        return int(self._public("/api/v3/time")["serverTime"])

    def exchange_info(self, symbol: Optional[str] = None) -> dict:
        """Public exchangeInfo (no signing) — for readiness checks / filters."""
        return self._public("/api/v3/exchangeInfo", {"symbol": symbol} if symbol else None)

    def account(self) -> dict:
        return self._signed("GET", "/api/v3/account")

    def new_market_order(self, symbol: str, side: str, quantity: float,
                         new_client_order_id: str) -> dict:
        """Place a MARKET order on Testnet. Returns the raw order response."""
        params = {
            "symbol": symbol, "side": side, "type": "MARKET",
            "quantity": _fmt_qty(quantity), "newClientOrderId": new_client_order_id,
            "newOrderRespType": "FULL",
        }
        logger.info("testnet MARKET %s %s qty=%s cid=%s", side, symbol,
                    params["quantity"], new_client_order_id)
        return self._signed("POST", "/api/v3/order", params)

    def get_order(self, symbol: str, orig_client_order_id: str) -> dict:
        return self._signed("GET", "/api/v3/order",
                            {"symbol": symbol, "origClientOrderId": orig_client_order_id})

    def open_orders(self, symbol: Optional[str] = None) -> list:
        return self._signed("GET", "/api/v3/openOrders",
                            {"symbol": symbol} if symbol else {})

    def cancel_order(self, symbol: str, orig_client_order_id: str) -> dict:
        return self._signed("DELETE", "/api/v3/order",
                            {"symbol": symbol, "origClientOrderId": orig_client_order_id})

    def cancel_all_open_orders(self, symbol: str) -> list:
        return self._signed("DELETE", "/api/v3/openOrders", {"symbol": symbol})


def _fmt_qty(q: float) -> str:
    return f"{q:.8f}".rstrip("0").rstrip(".")


def _err(resp: httpx.Response):
    try:
        b = resp.json()
        return b.get("code"), str(b.get("msg", resp.text))
    except Exception:
        return None, resp.text


def _redact(msg: str) -> str:
    low = msg.lower()
    if "signature" in low or "apikey" in low or "api-key" in low:
        return "[redacted testnet auth error]"
    return msg
