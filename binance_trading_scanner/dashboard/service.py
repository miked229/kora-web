"""Dashboard service layer.

The ONLY place the dashboard talks to the rest of the system. Pages call this;
they never touch indicators or the signal engine directly and never re-implement
any analysis. This keeps a single source of truth and makes the logic testable
without Streamlit.

Responsibilities:
  * fetch closed candles (live via the cached CandleStore, or deterministic demo)
  * detect whether live data is reachable ("LIVE DATA UNAVAILABLE" otherwise)
  * run the existing SignalEngine and expose its Signal + block scores
  * cache results per (symbol, timeframe, source, last-candle) so Streamlit
    reruns do not re-fetch or re-compute unnecessarily
  * never raise to the caller — a failing symbol yields an Analysis with an
    ``error`` string so a scan can continue past it
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

from binance.client import BinanceRESTClient
from binance.exchange_info import ExchangeInfoService
from binance.market_data import MarketDataService, candles_to_df
from config import Settings, get_settings
from core.enums import Timeframe
from core.exceptions import ScannerError
from core.logger import get_logger
from core.models import Signal
from data.candles import CandleStore
from signals import EngineConfig, MarketSnapshot, SignalEngine, compute_snapshot

from .demo_data import demo_klines_df

logger = get_logger("dashboard.service")

LIVE = "live"
DEMO = "demo"
LIVE_UNAVAILABLE = "LIVE DATA UNAVAILABLE"


def _last(s) -> Optional[float]:
    if s is None or len(s) == 0:
        return None
    v = s.iloc[-1]
    return None if pd.isna(v) else float(v)


@dataclass
class Analysis:
    """Everything a page needs to render one symbol/timeframe."""

    symbol: str
    timeframe: Timeframe
    source: str
    df: Optional[pd.DataFrame] = None
    snapshot: Optional[MarketSnapshot] = None
    signal: Optional[Signal] = None
    price: Optional[float] = None
    change_24h: Optional[float] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.signal is not None


class DashboardService:
    """Caching orchestrator over Binance / indicators / signals."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        engine_config: Optional[EngineConfig] = None,
        *,
        client: Optional[BinanceRESTClient] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cfg = engine_config or EngineConfig()
        self._client = client or BinanceRESTClient(
            self.settings.rest_base,
            timeout=self.settings.http_timeout,
            max_retries=1,  # dashboard stays responsive; deeper retries not wanted
        )
        self._market = MarketDataService(self._client)
        self._exinfo = ExchangeInfoService(self._client)
        self._candles = CandleStore(self._market, cache_ttl=20.0)
        self._engine = SignalEngine(self.cfg)

        self._demo_cache: Dict[Tuple[str, str, int], pd.DataFrame] = {}
        self._analysis_cache: Dict[Tuple, Analysis] = {}
        self._live_probe: Optional[Tuple[float, bool]] = None

    # -- live availability --------------------------------------------------

    def probe_live(self, ttl: float = 30.0) -> bool:
        """Return True if the public Binance REST endpoint answers a ping.

        Cached for ``ttl`` seconds so we do not ping on every rerun.
        """
        now = time.time()
        if self._live_probe and (now - self._live_probe[0]) < ttl:
            return self._live_probe[1]
        try:
            ok = self._client.ping()
        except Exception as exc:
            logger.warning("live probe failed: %s", exc)
            ok = False
        self._live_probe = (now, ok)
        return ok

    # -- core analysis ------------------------------------------------------

    def get_analysis(
        self, symbol: str, timeframe: Timeframe, source: str, *, limit: int = 300,
    ) -> Analysis:
        """Fetch + analyse one symbol. Never raises; errors land in Analysis."""
        symbol = symbol.upper()
        try:
            df = self._load_df(symbol, timeframe, source, limit)
            if df is None or len(df) == 0:
                return Analysis(symbol, timeframe, source, error=LIVE_UNAVAILABLE)

            cache_key = (symbol, timeframe.value, source, int(df["close_time"].iloc[-1]))
            if cache_key in self._analysis_cache:
                return self._analysis_cache[cache_key]

            snapshot = compute_snapshot(df, self.cfg)
            signal = self._engine.evaluate(df, symbol, timeframe)
            price, change = self._price_change(symbol, source, df)
            analysis = Analysis(
                symbol=symbol, timeframe=timeframe, source=source,
                df=df, snapshot=snapshot, signal=signal, price=price, change_24h=change,
            )
            self._analysis_cache[cache_key] = analysis
            return analysis
        except ScannerError as exc:
            logger.warning("analysis failed for %s: %s", symbol, exc,
                           extra={"symbol": symbol, "timeframe": timeframe.value})
            return Analysis(symbol, timeframe, source, error=f"{type(exc).__name__}: {exc}")
        except Exception as exc:  # defensive: one symbol must never crash the app
            logger.error("unexpected analysis error for %s: %s", symbol, exc,
                         extra={"symbol": symbol, "timeframe": timeframe.value})
            return Analysis(symbol, timeframe, source, error=f"Unexpected error: {exc}")

    def scan(
        self, symbols: List[str], timeframe: Timeframe, source: str, *, limit: int = 300,
    ) -> List[Analysis]:
        """Analyse many symbols, continuing past any individual failure."""
        return [self.get_analysis(s, timeframe, source, limit=limit) for s in symbols]

    # -- data loading -------------------------------------------------------

    def _load_df(self, symbol: str, timeframe: Timeframe, source: str, limit: int) -> Optional[pd.DataFrame]:
        if source == DEMO:
            key = (symbol, timeframe.value, limit)
            if key not in self._demo_cache:
                self._demo_cache[key] = demo_klines_df(symbol, timeframe, n=max(limit, 260))
            return self._demo_cache[key]
        # live
        if not self.probe_live():
            return None
        candles = self._candles.get(symbol, timeframe, limit=limit)
        return candles_to_df(candles)

    def _price_change(self, symbol: str, source: str, df: pd.DataFrame) -> Tuple[Optional[float], Optional[float]]:
        if source == LIVE:
            try:
                t = self._market.get_ticker(symbol)
                return t.last_price, t.price_change_pct
            except Exception:
                pass  # fall through to df-derived
        close = df["close"]
        price = _last(close)
        bars_24h = max(1, int(86_400_000 / timeframe_ms(df)))
        if len(close) > bars_24h:
            ref = float(close.iloc[-1 - bars_24h])
        else:
            ref = float(close.iloc[0])
        change = ((price / ref) - 1.0) * 100.0 if (price and ref) else None
        return price, change

    # -- row projection for overview / scanner ------------------------------

    def metrics_row(self, a: Analysis) -> Dict[str, object]:
        """Flatten an Analysis into the display fields used by tables/cards."""
        if not a.ok:
            return {"Symbol": a.symbol, "Error": a.error or LIVE_UNAVAILABLE}
        s = a.signal
        snap = a.snapshot
        rsi = _last(snap.rsi) if snap else None
        adx = _last(snap.adx["adx"]) if (snap is not None and "adx" in snap.adx) else None
        rvol = _last(snap.rvol) if snap else None
        tp1 = s.take_profit_1
        tp2 = s.take_profit_2
        return {
            "Symbol": a.symbol,
            "Price": a.price,
            "24h %": a.change_24h,
            "Trend": s.trend_class.value if s.trend_class else None,
            "Structure": s.structure_class.value if s.structure_class else None,
            "RSI": rsi,
            "ADX": adx,
            "RVOL": rvol,
            "Score": round(s.score, 1),
            "Raw Score": round(s.raw_score, 1),
            "Signal": s.direction.value,
            "Setup": s.setup_type.value if s.setup_type else None,
            "Entry": s.entry,
            "Stop": s.stop,
            "TP1": tp1,
            "TP2": tp2,
            "R:R": s.risk_reward,
        }

    def clear_cache(self) -> None:
        """Drop cached analyses/candles and force a fresh live probe."""
        self._analysis_cache.clear()
        self._demo_cache.clear()
        self._candles = CandleStore(self._market, cache_ttl=20.0)
        self._live_probe = None

    def close(self) -> None:
        self._client.close()


def timeframe_ms(df: pd.DataFrame) -> int:
    """Infer the candle step (ms) from a df's open times; fallback 1h."""
    if "open_time" in df.columns and len(df) >= 2:
        return int(df["open_time"].iloc[1] - df["open_time"].iloc[0])
    return 3_600_000
