"""Confluence scoring: independent block evaluators + a market snapshot.

The signal engine is deliberately split into small, independent blocks so the
logic stays auditable and testable. Each block reads a :class:`MarketSnapshot`
(indicators computed once, causally, on CLOSED candles) and returns a
:class:`BlockResult` with its own ``score`` / ``max_score`` / ``status`` /
``reasons`` / ``warnings``. No block mutates shared state.

SCORING WEIGHTS (0..100):

    Trend            25
    Structure        20
    Momentum         15
    Volume           15
    Volatility       10
    Setup Quality    10
    Risk Quality      5
    -------------------
    Total           100

IMPORTANT: these weights and every threshold below are an INITIAL, hand-set
configuration — NOT a statistical truth. They must be validated with the
backtesting engine in Phase 5. The score measures the strength of the system's
confluence rules; it is NOT a probability of winning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel

from core.enums import (
    SetupType,
    StructureClass,
    TrendClass,
    VolatilityState,
)
from indicators import (
    adx,
    atr,
    bollinger_band_width,
    bollinger_bands,
    breakout_detection,
    ema,
    macd,
    market_structure,
    obv,
    relative_volume,
    rsi,
    sma,
    stoch_rsi,
    support_resistance,
    volume_sma,
    vwap,
)
from indicators.structure import StructureState, SupportResistance


# --------------------------------------------------------------------------
# Configuration (initial values; validate via backtesting — Phase 5)
# --------------------------------------------------------------------------

class BlockWeights(BaseModel):
    trend: float = 25
    structure: float = 20
    momentum: float = 15
    volume: float = 15
    volatility: float = 10
    setup: float = 10
    risk: float = 5

    @property
    def total(self) -> float:
        return (
            self.trend + self.structure + self.momentum + self.volume
            + self.volatility + self.setup + self.risk
        )


class EngineConfig(BaseModel):
    """All tunables live here. Not optimised — see Phase 5."""

    weights: BlockWeights = BlockWeights()

    # data sufficiency
    min_bars: int = 210            # enough for EMA200 + swing confirmation

    # trend
    adx_trend: float = 25.0
    adx_weak: float = 20.0

    # momentum
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    rsi_bull_low: float = 45.0
    rsi_bull_high: float = 70.0

    # volume
    rvol_high: float = 1.3
    rvol_low: float = 0.7
    obv_lookback: int = 5

    # volatility (ATR as % of price)
    atr_pct_low: float = 0.015
    atr_pct_high: float = 0.06
    atr_pct_extreme: float = 0.12   # hard block above this
    bb_squeeze_ratio: float = 0.6   # bb_width < ratio * its rolling mean -> squeeze
    bb_expand_ratio: float = 1.4
    bb_width_lookback: int = 20

    # structure / setup
    swing_left: int = 2
    swing_right: int = 2
    breakout_lookback: int = 20
    pullback_atr_mult: float = 0.75

    # risk (provisional; full risk manager is Phase 5)
    atr_stop_mult: float = 1.5
    min_stop_atr: float = 0.4
    max_stop_atr: float = 3.0
    min_rr: float = 1.5
    good_rr: float = 2.0

    # decision
    min_score_long: float = 40.0

    # liquidity (optional absolute floor on quote volume, if the caller has it)
    min_quote_volume: Optional[float] = None


# --------------------------------------------------------------------------
# Block result
# --------------------------------------------------------------------------

@dataclass
class BlockResult:
    name: str
    score: float
    max_score: float
    status: str
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def pct(self) -> float:
        return (self.score / self.max_score) if self.max_score else 0.0

    def clamp(self) -> "BlockResult":
        self.score = float(max(0.0, min(self.score, self.max_score)))
        return self


# --------------------------------------------------------------------------
# Market snapshot: indicators computed once, causally, on closed candles
# --------------------------------------------------------------------------

@dataclass
class MarketSnapshot:
    df: pd.DataFrame
    close: pd.Series
    high: pd.Series
    low: pd.Series
    open: pd.Series
    volume: pd.Series
    ema20: pd.Series
    ema50: pd.Series
    ema200: pd.Series
    sma200: pd.Series
    adx: pd.DataFrame
    rsi: pd.Series
    macd: pd.DataFrame
    stoch: pd.DataFrame
    atr: pd.Series
    bb: pd.DataFrame
    bb_width: pd.Series
    vol_sma: pd.Series
    rvol: pd.Series
    obv: pd.Series
    vwap: pd.Series
    structure: StructureState
    breakout: pd.DataFrame
    sr: SupportResistance

    @property
    def n(self) -> int:
        return len(self.df)


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Case-insensitive column access (accepts open/High/etc.)."""
    for c in df.columns:
        if str(c).lower() == name:
            return df[c].astype("float64")
    raise KeyError(f"DataFrame missing required column '{name}'")


def compute_snapshot(df: pd.DataFrame, cfg: EngineConfig) -> MarketSnapshot:
    """Compute every indicator once for ``df`` (assumed CLOSED candles).

    All indicators are causal; the engine only ever reads the LAST row, so the
    result for a given bar depends solely on that bar and earlier ones.
    """
    close = _col(df, "close")
    high = _col(df, "high")
    low = _col(df, "low")
    open_ = _col(df, "open")
    volume = _col(df, "volume")

    return MarketSnapshot(
        df=df,
        close=close, high=high, low=low, open=open_, volume=volume,
        ema20=ema(close, 20), ema50=ema(close, 50), ema200=ema(close, 200),
        sma200=sma(close, 200),
        adx=adx(high, low, close, 14),
        rsi=rsi(close, 14),
        macd=macd(close),
        stoch=stoch_rsi(close),
        atr=atr(high, low, close, 14),
        bb=bollinger_bands(close, 20, 2),
        bb_width=bollinger_band_width(close, 20, 2),
        vol_sma=volume_sma(volume, 20),
        rvol=relative_volume(volume, 20),
        obv=obv(close, volume),
        vwap=vwap(high, low, close, volume),
        structure=market_structure(high, low, cfg.swing_left, cfg.swing_right),
        breakout=breakout_detection(high, low, close, cfg.breakout_lookback),
        sr=support_resistance(high, low, close, cfg.swing_left, cfg.swing_right),
    )


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _last(s: Optional[pd.Series]) -> Optional[float]:
    if s is None or len(s) == 0:
        return None
    v = s.iloc[-1]
    return None if pd.isna(v) else float(v)


def _last_bool(df: pd.DataFrame, col: str) -> bool:
    if df is None or len(df) == 0 or col not in df.columns:
        return False
    v = df[col].iloc[-1]
    return bool(v) if not pd.isna(v) else False


# --------------------------------------------------------------------------
# Block A — Trend (max 25)
# --------------------------------------------------------------------------

def classify_trend(
    close, e20, e50, e200, adx_v, pdi, mdi, cfg: EngineConfig
) -> TrendClass:
    if None in (close, e20, e50, e200):
        return TrendClass.NEUTRAL
    strong = adx_v is not None and adx_v >= cfg.adx_trend
    di_bull = pdi is not None and mdi is not None and pdi > mdi
    di_bear = pdi is not None and mdi is not None and mdi > pdi
    bull_stack = close > e200 and e20 > e50 > e200
    bear_stack = close < e200 and e20 < e50 < e200
    if bull_stack and strong and di_bull:
        return TrendClass.STRONG_BULLISH
    if close > e200 and e20 > e50:
        return TrendClass.BULLISH
    if bear_stack and strong and di_bear:
        return TrendClass.STRONG_BEARISH
    if close < e200 and e20 < e50:
        return TrendClass.BEARISH
    return TrendClass.NEUTRAL


def evaluate_trend(snap: MarketSnapshot, cfg: EngineConfig) -> tuple[BlockResult, TrendClass]:
    close = _last(snap.close)
    e20, e50, e200 = _last(snap.ema20), _last(snap.ema50), _last(snap.ema200)
    adx_v = _last(snap.adx["adx"]) if "adx" in snap.adx else None
    pdi = _last(snap.adx["plus_di"]) if "plus_di" in snap.adx else None
    mdi = _last(snap.adx["minus_di"]) if "minus_di" in snap.adx else None

    score = 0.0
    reasons: List[str] = []
    warnings: List[str] = []

    if close is not None and e200 is not None:
        if close > e200:
            score += 8
            reasons.append("Price above EMA200")
        else:
            warnings.append("Price below EMA200 (long-term bearish)")
    else:
        warnings.append("EMA200 unavailable (insufficient history)")

    if e20 is not None and e50 is not None:
        if e20 > e50:
            score += 6
            reasons.append("EMA20 above EMA50")
        else:
            warnings.append("EMA20 below EMA50")

    if e50 is not None and e200 is not None:
        if e50 > e200:
            score += 6
            reasons.append("EMA50 above EMA200")
        else:
            warnings.append("EMA50 below EMA200")

    if adx_v is not None and pdi is not None and mdi is not None:
        if adx_v >= cfg.adx_trend and pdi > mdi:
            score += 5
            reasons.append(f"ADX {adx_v:.0f} strong with +DI>-DI")
        elif adx_v >= cfg.adx_weak and pdi > mdi:
            score += 3
            reasons.append(f"ADX {adx_v:.0f} building with +DI>-DI")
        elif mdi > pdi:
            warnings.append(f"-DI above +DI (bearish directional, ADX {adx_v:.0f})")

    tc = classify_trend(close, e20, e50, e200, adx_v, pdi, mdi, cfg)
    res = BlockResult("trend", score, cfg.weights.trend, tc.value, reasons, warnings).clamp()
    return res, tc


# --------------------------------------------------------------------------
# Block B — Market structure (max 20). Uses swings/breakouts, never EMA crosses.
# --------------------------------------------------------------------------

def classify_structure(st: StructureState) -> StructureClass:
    if st.higher_high and st.higher_low:
        return StructureClass.BULLISH_STRUCTURE
    if st.lower_high and st.lower_low:
        return StructureClass.BEARISH_STRUCTURE
    if st.last_swing_high is not None and st.last_swing_low is not None:
        # both sides present but not cleanly trending -> range
        return StructureClass.RANGE
    return StructureClass.TRANSITION


def evaluate_structure(snap: MarketSnapshot, cfg: EngineConfig) -> tuple[BlockResult, StructureClass]:
    st = snap.structure
    sc = classify_structure(st)
    close = _last(snap.close)
    breakout_up = _last_bool(snap.breakout, "breakout_up")

    score = 0.0
    reasons: List[str] = []
    warnings: List[str] = []

    if sc == StructureClass.BULLISH_STRUCTURE:
        score += 12
        reasons.append("Bullish structure (higher high & higher low)")
    elif sc == StructureClass.RANGE:
        score += 5
        reasons.append("Ranging structure (swings both sides)")
    elif sc == StructureClass.TRANSITION:
        score += 2
        warnings.append("Structure in transition (insufficient confirmed swings)")
    else:
        warnings.append("Bearish structure (lower high & lower low)")

    if breakout_up:
        score += 5
        reasons.append("Breakout above prior range confirmed")

    if close is not None and snap.sr.nearest_support is not None and close > snap.sr.nearest_support:
        score += 3
        reasons.append(f"Holding above support {snap.sr.nearest_support:.4f}")

    if close is not None and snap.sr.nearest_resistance is not None:
        warnings.append(f"Resistance nearby at {snap.sr.nearest_resistance:.4f}")

    res = BlockResult("structure", score, cfg.weights.structure, sc.value, reasons, warnings).clamp()
    return res, sc


# --------------------------------------------------------------------------
# Block C — Momentum (max 15). Context-aware: no naive "RSI<30 = BUY".
# --------------------------------------------------------------------------

def evaluate_momentum(snap: MarketSnapshot, trend: TrendClass, cfg: EngineConfig) -> BlockResult:
    rsi_v = _last(snap.rsi)
    macd_line = _last(snap.macd["macd"]) if "macd" in snap.macd else None
    macd_sig = _last(snap.macd["signal"]) if "signal" in snap.macd else None
    hist = _last(snap.macd["hist"]) if "hist" in snap.macd else None
    k = _last(snap.stoch["k"]) if "k" in snap.stoch else None

    score = 0.0
    reasons: List[str] = []
    warnings: List[str] = []
    status = "neutral"

    # MACD: bullish only when line>signal AND histogram positive.
    if macd_line is not None and macd_sig is not None and hist is not None:
        if macd_line > macd_sig and hist > 0:
            score += 5
            reasons.append("MACD positive (line above signal)")
        elif hist < 0:
            warnings.append("MACD histogram negative")

    # RSI is interpreted in trend context (this is the key anti-simplistic rule).
    if rsi_v is not None:
        if trend.is_bearish:
            # Low RSI in a downtrend is NOT a long trigger.
            if rsi_v < cfg.rsi_oversold:
                warnings.append(f"RSI {rsi_v:.0f} oversold within a downtrend (not a long)")
            else:
                warnings.append(f"RSI {rsi_v:.0f} in a bearish context")
        else:
            if cfg.rsi_bull_low <= rsi_v <= cfg.rsi_bull_high:
                score += 6
                reasons.append(f"RSI {rsi_v:.0f} healthy for continuation")
            elif rsi_v > cfg.rsi_overbought:
                score += 2
                warnings.append(f"RSI {rsi_v:.0f} overbought (extension risk)")
            elif rsi_v < cfg.rsi_bull_low:
                score += 2
                reasons.append(f"RSI {rsi_v:.0f} recovering")

    # Stochastic RSI: reward turning up from lower half, flag overbought.
    if k is not None:
        if k < 50 and not trend.is_bearish:
            score += 4
            reasons.append(f"StochRSI %K {k:.0f} turning up from lower half")
        elif k > 80:
            warnings.append(f"StochRSI %K {k:.0f} overbought")

    if score >= 10:
        status = "bullish"
    elif score <= 2:
        status = "weak"
    return BlockResult("momentum", score, cfg.weights.momentum, status, reasons, warnings).clamp()


# --------------------------------------------------------------------------
# Block D — Volume (max 15). High volume is not assumed bullish.
# --------------------------------------------------------------------------

def evaluate_volume(snap: MarketSnapshot, cfg: EngineConfig) -> BlockResult:
    rvol = _last(snap.rvol)
    close = _last(snap.close)
    open_ = _last(snap.open)
    vwap_v = _last(snap.vwap)
    vol = _last(snap.volume)
    vol_sma = _last(snap.vol_sma)

    up_candle = close is not None and open_ is not None and close >= open_
    obv_rising = False
    if snap.obv is not None and len(snap.obv) > cfg.obv_lookback:
        past = snap.obv.iloc[-1 - cfg.obv_lookback]
        obv_rising = (not pd.isna(past)) and snap.obv.iloc[-1] > past

    score = 0.0
    reasons: List[str] = []
    warnings: List[str] = []

    if rvol is not None:
        if rvol >= cfg.rvol_high:
            if up_candle or obv_rising:
                score += 5
                reasons.append(f"Relative volume {rvol:.2f} confirming the move")
            else:
                warnings.append(f"High relative volume {rvol:.2f} on a down candle")
        elif rvol < cfg.rvol_low:
            warnings.append(f"Below-average volume (RVOL {rvol:.2f})")

    if obv_rising:
        score += 5
        reasons.append("OBV rising (accumulation)")
    else:
        warnings.append("OBV not rising")

    if close is not None and vwap_v is not None and close > vwap_v:
        score += 3
        reasons.append("Price above VWAP")

    if vol is not None and vol_sma is not None and vol_sma > 0 and vol > vol_sma:
        score += 2
        reasons.append("Volume above its 20-period average")

    confirmed = score >= 8
    status = "confirmed" if confirmed else "unconfirmed"
    return BlockResult("volume", score, cfg.weights.volume, status, reasons, warnings).clamp()


# --------------------------------------------------------------------------
# Block E — Volatility (max 10).
# --------------------------------------------------------------------------

def classify_volatility(atr_pct, bb_width, bb_width_mean, cfg: EngineConfig) -> VolatilityState:
    if bb_width is not None and bb_width_mean is not None and bb_width_mean > 0:
        if bb_width < cfg.bb_squeeze_ratio * bb_width_mean:
            return VolatilityState.COMPRESSION
        if bb_width > cfg.bb_expand_ratio * bb_width_mean:
            return VolatilityState.EXPANSION
    if atr_pct is None:
        return VolatilityState.NORMAL
    if atr_pct < cfg.atr_pct_low:
        return VolatilityState.LOW
    if atr_pct > cfg.atr_pct_high:
        return VolatilityState.HIGH
    return VolatilityState.NORMAL


def evaluate_volatility(snap: MarketSnapshot, cfg: EngineConfig) -> tuple[BlockResult, VolatilityState, Optional[float]]:
    close = _last(snap.close)
    atr_v = _last(snap.atr)
    atr_pct = (atr_v / close) if (atr_v is not None and close) else None
    bb_w = _last(snap.bb_width)
    bb_w_mean = None
    if snap.bb_width is not None and len(snap.bb_width.dropna()) >= cfg.bb_width_lookback:
        bb_w_mean = float(snap.bb_width.rolling(cfg.bb_width_lookback).mean().iloc[-1])

    vs = classify_volatility(atr_pct, bb_w, bb_w_mean, cfg)

    score = 0.0
    reasons: List[str] = []
    warnings: List[str] = []

    if vs == VolatilityState.NORMAL:
        score += 7
        reasons.append("Volatility normal")
    elif vs == VolatilityState.EXPANSION:
        score += 8
        reasons.append("Volatility expanding")
    elif vs == VolatilityState.COMPRESSION:
        score += 5
        reasons.append("Volatility compressed (potential energy)")
    elif vs == VolatilityState.LOW:
        score += 4
        warnings.append("Low volatility (limited follow-through)")
    else:  # HIGH
        score += 2
        warnings.append("High volatility (wider stops required)")

    if atr_pct is not None and atr_pct > cfg.atr_pct_extreme:
        warnings.append(f"Extreme volatility (ATR {atr_pct*100:.1f}% of price)")

    res = BlockResult("volatility", score, cfg.weights.volatility, vs.value, reasons, warnings).clamp()
    return res, vs, atr_pct


# --------------------------------------------------------------------------
# Block F — Setup quality (max 10). Each setup has its own explicit rules.
# --------------------------------------------------------------------------

@dataclass
class SetupInfo:
    setup: SetupType
    entry_reason: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def detect_setup(
    snap: MarketSnapshot, trend: TrendClass, structure: StructureClass, cfg: EngineConfig
) -> SetupInfo:
    """Identify which (if any) long setup is occurring. Rules are kept separate
    per setup type — no single blended formula."""
    close = _last(snap.close)
    open_ = _last(snap.open)
    e20 = _last(snap.ema20)
    atr_v = _last(snap.atr)
    rvol = _last(snap.rvol)
    breakout_up = _last_bool(snap.breakout, "breakout_up")
    up_candle = close is not None and open_ is not None and close >= open_
    vol_ok = rvol is not None and rvol >= cfg.rvol_high

    # D. Range breakout — breaking OUT of a range (structure must be RANGE).
    if structure == StructureClass.RANGE and breakout_up and up_candle:
        return SetupInfo(
            SetupType.RANGE_BREAKOUT,
            entry_reason="Close breaking above range resistance",
            reasons=["Range breakout: close above prior range high"],
            warnings=[] if vol_ok else ["Range breakout lacks volume confirmation"],
        )

    # B/C. Within an established uptrend: pullback or trend continuation.
    # A breakout close in an ongoing uptrend is continuation, not a new breakout.
    if trend.is_bullish and structure == StructureClass.BULLISH_STRUCTURE:
        if None not in (close, e20, atr_v):
            near_ema = abs(close - e20) <= cfg.pullback_atr_mult * atr_v
            if near_ema and up_candle and close >= e20:
                return SetupInfo(
                    SetupType.PULLBACK,
                    entry_reason="Bullish pullback into EMA20 resuming higher",
                    reasons=["Pullback into EMA20 within an uptrend"],
                )
        return SetupInfo(
            SetupType.TREND_CONTINUATION,
            entry_reason="Trend continuation in an established uptrend",
            reasons=["Trend continuation: bullish trend with bullish structure"],
        )

    # A. Fresh breakout from a base/transition (not already bearish).
    if breakout_up and up_candle and not trend.is_bearish:
        return SetupInfo(
            SetupType.BREAKOUT,
            entry_reason="Close breaking above prior swing range",
            reasons=["Breakout: close above prior range high"],
            warnings=[] if vol_ok else ["Breakout lacks volume confirmation"],
        )

    return SetupInfo(SetupType.NONE, warnings=["No qualifying long setup"])


def evaluate_setup(info: SetupInfo, cfg: EngineConfig) -> BlockResult:
    points = {
        SetupType.BREAKOUT: 10,
        SetupType.RANGE_BREAKOUT: 10,
        SetupType.PULLBACK: 8,
        SetupType.TREND_CONTINUATION: 6,
        SetupType.NONE: 0,
    }
    score = float(points[info.setup])
    return BlockResult(
        "setup", score, cfg.weights.setup, info.setup.value, list(info.reasons), list(info.warnings)
    ).clamp()


# --------------------------------------------------------------------------
# Block G — Risk quality (max 5). Provisional; full risk manager is Phase 5.
# --------------------------------------------------------------------------

def evaluate_risk(
    entry: Optional[float],
    stop: Optional[float],
    risk_reward: Optional[float],
    atr_v: Optional[float],
    cfg: EngineConfig,
) -> BlockResult:
    score = 0.0
    reasons: List[str] = []
    warnings: List[str] = []
    status = "n/a"

    if entry is None or stop is None or risk_reward is None:
        warnings.append("Risk not assessable (no valid entry/stop)")
        return BlockResult("risk", 0.0, cfg.weights.risk, status, reasons, warnings)

    risk = entry - stop
    if risk <= 0:
        warnings.append("Invalid stop (not below entry)")
        return BlockResult("risk", 0.0, cfg.weights.risk, "invalid", reasons, warnings)

    # Reward:risk quality
    if risk_reward >= cfg.good_rr:
        score += 4
        reasons.append(f"Risk/reward {risk_reward:.2f} favourable")
    elif risk_reward >= cfg.min_rr:
        score += 2
        reasons.append(f"Risk/reward {risk_reward:.2f} acceptable")
    else:
        warnings.append(f"Risk/reward {risk_reward:.2f} below minimum {cfg.min_rr}")

    # Stop distance sanity vs ATR
    if atr_v is not None and atr_v > 0:
        dist_atr = risk / atr_v
        if cfg.min_stop_atr <= dist_atr <= cfg.max_stop_atr:
            score += 1
            reasons.append(f"Stop distance {dist_atr:.1f}×ATR reasonable")
        else:
            warnings.append(f"Stop distance {dist_atr:.1f}×ATR outside {cfg.min_stop_atr}-{cfg.max_stop_atr}")

    status = "ok" if score >= 3 else "weak"
    return BlockResult("risk", score, cfg.weights.risk, status, reasons, warnings).clamp()
