"""Central configuration.

Loads settings from the environment (via a ``.env`` file when present) into a
validated Pydantic model. Secrets (API key/secret) are read on demand and are
NEVER stored on the settings object that gets rendered in the UI or logged.

All operational parameters (symbols, timeframes, risk, fees, slippage) have
sensible, clearly-documented defaults and can be overridden at runtime from the
Settings page — no code edits required.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from pydantic import BaseModel, Field, field_validator

from core.enums import Timeframe, TradingMode

# Load .env if python-dotenv is available; harmless if the file is absent.
try:  # pragma: no cover - trivial
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


DEFAULT_SYMBOLS: List[str] = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT",
]

# Official Binance Spot endpoints.
MAINNET_REST = "https://api.binance.com"
MAINNET_WS = "wss://stream.binance.com:9443"
# Public market-data mirror (no account endpoints); useful when api.binance.com
# is geo/network blocked.
MARKET_DATA_REST = "https://data-api.binance.vision"
# Binance Spot Testnet (Demo Mode) — used only in later, opt-in phases.
TESTNET_REST = "https://testnet.binance.vision"
TESTNET_WS = "wss://stream.testnet.binance.vision"


def _get_env(name: str, default: str) -> str:
    val = os.getenv(name)
    return val if val not in (None, "") else default


class Settings(BaseModel):
    """Runtime configuration. Never holds secrets."""

    # --- Environment / endpoints ---
    binance_env: str = "mainnet"          # "mainnet" | "testnet"
    rest_base: str = MAINNET_REST
    ws_base: str = MAINNET_WS

    # --- Market universe ---
    symbols: List[str] = Field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    timeframes: List[Timeframe] = Field(default_factory=lambda: list(Timeframe))
    default_timeframe: Timeframe = Timeframe.M15

    # --- Mode & account ---
    mode: TradingMode = TradingMode.PAPER
    capital: float = 10_000.0
    risk_per_trade: float = 0.01          # 1% — configurable, NOT a recommendation

    # --- Risk limits ---
    max_daily_loss: float = 0.05          # 5% of capital
    max_positions: int = 5
    max_exposure: float = 0.50            # 50% of capital deployed at once

    # --- Backtest cost model ---
    fee_rate: float = 0.001               # 0.10% Binance Spot taker default
    slippage_rate: float = 0.0005         # 0.05%

    # --- Infra ---
    log_level: str = "INFO"
    db_path: str = "data/scanner.db"
    http_timeout: float = 10.0
    request_max_retries: int = 3

    @field_validator("risk_per_trade")
    @classmethod
    def _risk_bounds(cls, v: float) -> float:
        if not 0 < v <= 0.5:
            raise ValueError("risk_per_trade must be in (0, 0.5]")
        return v

    @field_validator("symbols")
    @classmethod
    def _upper_symbols(cls, v: List[str]) -> List[str]:
        return [s.strip().upper() for s in v if s.strip()]

    # --- Secret access (read on demand; never persisted on the instance) ---

    @staticmethod
    def get_api_credentials() -> tuple[str | None, str | None]:
        """Return (api_key, api_secret) from the environment, or (None, None).

        Kept as a static method returning ephemeral values so credentials are
        never attributes of a rendered/logged settings object.
        """
        return os.getenv("BINANCE_API_KEY") or None, os.getenv("BINANCE_API_SECRET") or None

    @property
    def has_credentials(self) -> bool:
        key, secret = self.get_api_credentials()
        return bool(key and secret)


def load_settings() -> Settings:
    """Build a Settings instance from environment variables."""
    env = _get_env("BINANCE_ENV", "mainnet").lower()
    if env == "testnet":
        rest_base = _get_env("BINANCE_REST_BASE", TESTNET_REST)
        ws_base = TESTNET_WS
    else:
        rest_base = _get_env("BINANCE_REST_BASE", MAINNET_REST)
        ws_base = MAINNET_WS

    try:
        mode = TradingMode(_get_env("APP_MODE", "PAPER").upper())
    except ValueError:
        mode = TradingMode.PAPER

    return Settings(
        binance_env=env,
        rest_base=rest_base,
        ws_base=ws_base,
        mode=mode,
        capital=float(_get_env("CAPITAL", "10000")),
        risk_per_trade=float(_get_env("RISK_PER_TRADE", "0.01")),
        fee_rate=float(_get_env("FEE_RATE", "0.001")),
        slippage_rate=float(_get_env("SLIPPAGE_RATE", "0.0005")),
        log_level=_get_env("LOG_LEVEL", "INFO"),
        db_path=_get_env("DB_PATH", "data/scanner.db"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton for import-time convenience."""
    return load_settings()
