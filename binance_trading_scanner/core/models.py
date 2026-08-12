"""Validated domain models (Pydantic v2).

Every piece of market data that enters the system is parsed into one of these
models, which enforces types and basic invariants at the boundary. Nothing
downstream should ever handle a raw Binance dict.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import (
    ScoreClass,
    SetupType,
    SignalType,
    StructureClass,
    SymbolStatus,
    Timeframe,
    TrendClass,
    VolatilityState,
)


def _utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


class Candle(BaseModel):
    """A single OHLCV candlestick.

    ``open_time`` / ``close_time`` are the raw Binance millisecond epochs;
    ``is_closed`` marks whether the candle is final. Look-ahead-bias protection
    depends on this flag: signal generation must ignore un-closed candles.
    """

    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float = 0.0
    trades: int = 0
    is_closed: bool = True

    @property
    def open_dt(self) -> datetime:
        return _utc(self.open_time)

    @property
    def close_dt(self) -> datetime:
        return _utc(self.close_time)

    @model_validator(mode="after")
    def _check_ohlc(self) -> "Candle":
        # High must be the max and low the min; guards against corrupt rows.
        hi = max(self.open, self.close, self.high)
        lo = min(self.open, self.close, self.low)
        if self.high < hi or self.low > lo:
            raise ValueError(
                f"Inconsistent OHLC (o={self.open} h={self.high} "
                f"l={self.low} c={self.close})"
            )
        if self.low < 0 or self.volume < 0:
            raise ValueError("Negative price/volume")
        if self.close_time < self.open_time:
            raise ValueError("close_time precedes open_time")
        return self

    @classmethod
    def from_binance_kline(cls, row: list, *, is_closed: bool = True) -> "Candle":
        """Parse one row of a Binance ``/api/v3/klines`` response.

        Row layout (per official docs):
        [openTime, open, high, low, close, volume, closeTime, quoteVolume,
         numberOfTrades, takerBuyBase, takerBuyQuote, ignore]
        """
        return cls(
            open_time=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            close_time=int(row[6]),
            quote_volume=float(row[7]),
            trades=int(row[8]),
            is_closed=is_closed,
        )


class Ticker(BaseModel):
    """Snapshot of last price plus 24h rolling stats (/api/v3/ticker/24hr)."""

    symbol: str
    last_price: float
    price_change_pct: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0
    volume: float = 0.0          # base-asset volume
    quote_volume: float = 0.0    # quote-asset volume (e.g. USDT)
    timestamp: int = Field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp() * 1000))

    @classmethod
    def from_binance_24hr(cls, d: dict) -> "Ticker":
        return cls(
            symbol=d["symbol"],
            last_price=float(d["lastPrice"]),
            price_change_pct=float(d.get("priceChangePercent", 0.0)),
            high_24h=float(d.get("highPrice", 0.0)),
            low_24h=float(d.get("lowPrice", 0.0)),
            volume=float(d.get("volume", 0.0)),
            quote_volume=float(d.get("quoteVolume", 0.0)),
            timestamp=int(d.get("closeTime", datetime.now(timezone.utc).timestamp() * 1000)),
        )


class BookTicker(BaseModel):
    """Best bid/ask snapshot (/api/v3/ticker/bookTicker)."""

    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float

    @property
    def spread(self) -> float:
        return self.ask_price - self.bid_price

    @property
    def spread_pct(self) -> float:
        mid = self.mid_price
        return (self.spread / mid * 100) if mid else 0.0

    @property
    def mid_price(self) -> float:
        return (self.ask_price + self.bid_price) / 2

    @model_validator(mode="after")
    def _check(self) -> "BookTicker":
        if self.bid_price < 0 or self.ask_price < 0:
            raise ValueError("Negative bid/ask")
        return self

    @classmethod
    def from_binance(cls, d: dict) -> "BookTicker":
        return cls(
            symbol=d["symbol"],
            bid_price=float(d["bidPrice"]),
            bid_qty=float(d["bidQty"]),
            ask_price=float(d["askPrice"]),
            ask_qty=float(d["askQty"]),
        )


class SymbolFilters(BaseModel):
    """Precision / minimum-order constraints extracted from exchangeInfo.

    These are essential for building valid orders in later phases. We surface
    them now so validation logic can be written and tested early.
    """

    tick_size: float = 0.0        # PRICE_FILTER.tickSize
    step_size: float = 0.0        # LOT_SIZE.stepSize
    min_qty: float = 0.0          # LOT_SIZE.minQty
    max_qty: float = 0.0          # LOT_SIZE.maxQty
    min_notional: float = 0.0     # NOTIONAL / MIN_NOTIONAL


class SymbolInfo(BaseModel):
    """Per-symbol trading rules from /api/v3/exchangeInfo."""

    symbol: str
    base_asset: str
    quote_asset: str
    status: SymbolStatus = SymbolStatus.UNKNOWN
    base_precision: int = 8
    quote_precision: int = 8
    filters: SymbolFilters = Field(default_factory=SymbolFilters)

    @property
    def is_trading(self) -> bool:
        return self.status == SymbolStatus.TRADING

    @classmethod
    def from_binance(cls, d: dict) -> "SymbolInfo":
        filters = {f["filterType"]: f for f in d.get("filters", [])}
        price_f = filters.get("PRICE_FILTER", {})
        lot_f = filters.get("LOT_SIZE", {})
        notional_f = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        return cls(
            symbol=d["symbol"],
            base_asset=d["baseAsset"],
            quote_asset=d["quoteAsset"],
            status=SymbolStatus(d.get("status", "UNKNOWN")),
            base_precision=int(d.get("baseAssetPrecision", 8)),
            quote_precision=int(d.get("quoteAssetPrecision", 8)),
            filters=SymbolFilters(
                tick_size=float(price_f.get("tickSize", 0.0)),
                step_size=float(lot_f.get("stepSize", 0.0)),
                min_qty=float(lot_f.get("minQty", 0.0)),
                max_qty=float(lot_f.get("maxQty", 0.0)),
                min_notional=float(
                    notional_f.get("minNotional")
                    or notional_f.get("notional")
                    or 0.0
                ),
            ),
        )


class Signal(BaseModel):
    """A fully-explained trade signal produced by the signal engine.

    Design goals:
      * Explainable — ``reasons`` / ``warnings`` / ``invalidation_conditions``
        are derived from real calculated conditions, never generic text.
      * Separable — ``raw_score`` (confluence strength) is kept distinct from the
        ``signal`` (final decision), so a strong-but-filtered setup remains
        auditable (e.g. raw_score=84 but signal=NO_TRADE).
      * Stable — extra Phase-3 fields are additive; existing persistence keeps
        working. Spec-named accessors (``direction``, ``stop_loss``, ...) are
        exposed as read-only properties over the stored fields.

    ``score`` reflects the strength of the system's confluence rules. It is NOT
    a probability of winning.
    """

    symbol: str
    timeframe: Timeframe
    signal: SignalType                       # final decision (a.k.a. direction)
    score: float = 0.0                       # confluence strength 0..100 (winning side)
    raw_score: float = 0.0                   # pre-filter score of the reported side (auditing)
    long_score: float = 0.0                  # independent LONG confluence 0..100
    short_score: float = 0.0                 # independent SHORT confluence 0..100
    score_class: ScoreClass = ScoreClass.NO_TRADE
    reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    entry: Optional[float] = None
    stop: Optional[float] = None
    take_profits: List[float] = Field(default_factory=list)
    invalidation: Optional[float] = None     # numeric invalidation level
    risk_reward: Optional[float] = None
    # Analysis context (optional; populated by the engine)
    setup_type: Optional[SetupType] = None
    entry_reason: Optional[str] = None
    stop_method: Optional[str] = None
    trend_class: Optional[TrendClass] = None
    structure_class: Optional[StructureClass] = None
    volatility_state: Optional[VolatilityState] = None
    blocked_by: List[str] = Field(default_factory=list)
    block_scores: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("score", "raw_score", "long_score", "short_score")
    @classmethod
    def _score_range(cls, v: float) -> float:
        if not 0 <= v <= 100:
            raise ValueError("score must be within 0..100")
        return v

    @model_validator(mode="after")
    def _sync_class(self) -> "Signal":
        # Keep the classification consistent with the numeric score.
        self.score_class = ScoreClass.from_score(self.score)
        return self

    # --- spec-named read-only accessors (no new storage) ---
    @property
    def direction(self) -> SignalType:
        return self.signal

    @property
    def confidence_label(self) -> ScoreClass:
        return self.score_class

    @property
    def timestamp(self) -> datetime:
        return self.created_at

    @property
    def stop_loss(self) -> Optional[float]:
        return self.stop

    @property
    def take_profit_1(self) -> Optional[float]:
        return self.take_profits[0] if len(self.take_profits) >= 1 else None

    @property
    def take_profit_2(self) -> Optional[float]:
        return self.take_profits[1] if len(self.take_profits) >= 2 else None
