"""Low-level Binance Spot REST client.

Wraps httpx with the operational concerns the spec demands:
    * timeouts
    * bounded retries with exponential backoff
    * rate-limit awareness (HTTP 429 / 418, ``Retry-After``)
    * typed error translation

This client only performs **public, unauthenticated** GET requests in Phase 1.
Signed/account endpoints are intentionally not implemented here yet; they will
be added (behind an explicit opt-in) when Demo Mode arrives.

Endpoint reference (current Binance Spot API):
    GET /api/v3/ping
    GET /api/v3/time
    GET /api/v3/exchangeInfo
    GET /api/v3/klines
    GET /api/v3/ticker/price
    GET /api/v3/ticker/bookTicker
    GET /api/v3/ticker/24hr
    GET /api/v3/depth
    GET /api/v3/trades
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from core.exceptions import (
    BinanceAPIError,
    BinanceConnectionError,
    RateLimitError,
)
from core.logger import get_logger

logger = get_logger("binance.client")

_DEFAULT_BASE = "https://api.binance.com"
_USER_AGENT = "binance-trading-scanner/0.1 (+public-data)"


class BinanceRESTClient:
    """Synchronous public REST client.

    Parameters
    ----------
    base_url:
        REST base, e.g. ``https://api.binance.com`` or the public mirror
        ``https://data-api.binance.vision``.
    timeout:
        Per-request timeout in seconds.
    max_retries:
        Maximum retry attempts for transient failures (network errors and
        rate limits). ``0`` disables retrying.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover - defensive
            pass

    def __enter__(self) -> "BinanceRESTClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- core request -------------------------------------------------------

    def _request(self, path: str, params: Optional[dict] = None) -> Any:
        """GET ``path`` with retry/backoff, returning parsed JSON."""
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._client.get(url, params=params)
            except httpx.TimeoutException as exc:
                if attempt > self.max_retries:
                    raise BinanceConnectionError(f"Timeout after {attempt} attempts: {exc}") from exc
                self._backoff(attempt, reason="timeout")
                continue
            except httpx.HTTPError as exc:
                if attempt > self.max_retries:
                    raise BinanceConnectionError(f"Network error after {attempt} attempts: {exc}") from exc
                self._backoff(attempt, reason="network")
                continue

            # Rate limiting: 429 = too many requests, 418 = auto-ban.
            if resp.status_code in (418, 429):
                retry_after = _parse_retry_after(resp)
                if attempt > self.max_retries:
                    raise RateLimitError(resp.status_code, retry_after)
                logger.warning(
                    "rate limited (HTTP %s), backing off %.1fs",
                    resp.status_code, retry_after or self._backoff_seconds(attempt),
                )
                time.sleep(retry_after if retry_after is not None else self._backoff_seconds(attempt))
                continue

            if resp.status_code >= 400:
                code, message = _parse_error_body(resp)
                # 5xx are transient; retry. 4xx (bad symbol etc.) are terminal.
                if resp.status_code >= 500 and attempt <= self.max_retries:
                    self._backoff(attempt, reason=f"http {resp.status_code}")
                    continue
                raise BinanceAPIError(resp.status_code, code, message)

            try:
                return resp.json()
            except ValueError as exc:
                raise BinanceConnectionError(f"Invalid JSON from {path}: {exc}") from exc

    def _backoff_seconds(self, attempt: int) -> float:
        # 2, 4, 8, ... capped at 16s.
        return min(2 ** attempt, 16)

    def _backoff(self, attempt: int, *, reason: str) -> None:
        delay = self._backoff_seconds(attempt)
        logger.warning("retrying after %s (attempt %d), sleeping %.1fs", reason, attempt, delay)
        time.sleep(delay)

    # -- public endpoints ---------------------------------------------------

    def ping(self) -> bool:
        self._request("/api/v3/ping")
        return True

    def server_time(self) -> int:
        return int(self._request("/api/v3/time")["serverTime"])

    def exchange_info(self, symbol: Optional[str] = None) -> dict:
        params = {"symbol": symbol} if symbol else None
        return self._request("/api/v3/exchangeInfo", params)

    def klines(
        self,
        symbol: str,
        interval: str,
        *,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list:
        params: dict = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return self._request("/api/v3/klines", params)

    def ticker_price(self, symbol: Optional[str] = None) -> Any:
        params = {"symbol": symbol} if symbol else None
        return self._request("/api/v3/ticker/price", params)

    def book_ticker(self, symbol: Optional[str] = None) -> Any:
        params = {"symbol": symbol} if symbol else None
        return self._request("/api/v3/ticker/bookTicker", params)

    def ticker_24hr(self, symbol: Optional[str] = None) -> Any:
        params = {"symbol": symbol} if symbol else None
        return self._request("/api/v3/ticker/24hr", params)

    def depth(self, symbol: str, *, limit: int = 100) -> dict:
        return self._request("/api/v3/depth", {"symbol": symbol, "limit": limit})

    def trades(self, symbol: str, *, limit: int = 500) -> list:
        return self._request("/api/v3/trades", {"symbol": symbol, "limit": min(limit, 1000)})


def _parse_retry_after(resp: httpx.Response) -> Optional[float]:
    val = resp.headers.get("Retry-After")
    if val is None:
        return None
    try:
        return float(val)
    except ValueError:  # pragma: no cover - header is normally numeric
        return None


def _parse_error_body(resp: httpx.Response) -> tuple[Optional[int], str]:
    try:
        body = resp.json()
        return body.get("code"), str(body.get("msg", resp.text))
    except Exception:
        return None, resp.text
