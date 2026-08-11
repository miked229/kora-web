"""Signal engine: turn indicators + structure into an explainable decision.

Pipeline (each stage is small and independent):

    1. guard: insufficient data -> NO_TRADE
    2. compute_snapshot (indicators, once, causal, closed candles)
    3. seven confluence blocks -> raw_score  (scoring.py)
    4. detect setup -> derive provisional entry / stop / take-profits
    5. filters (signal_filters.py) -> may veto a LONG regardless of score
    6. decide direction: LONG / NEUTRAL / NO_TRADE, keeping raw_score separate
    7. assemble an explainable Signal (reasons / warnings / invalidations)

The engine reads only the LAST row of whatever DataFrame it is given, and all
indicators are causal, so ``evaluate_at(df, i)`` depends solely on candles up to
``i``. This is what makes the engine safe for candle-by-candle backtesting
(Phase 5) with no future-data leakage.

No trading, no orders, no API keys, no optimisation, no ML.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

import pandas as pd

from core.enums import (
    ScoreClass,
    SetupType,
    SignalType,
    StructureClass,
    Timeframe,
    TrendClass,
)
from core.logger import get_logger
from core.models import Signal

from . import scoring as sc
from . import signal_filters as sf

logger = get_logger("signals.engine")


class SignalEngine:
    """Stateless evaluator. Reuse one instance across symbols/timeframes."""

    def __init__(self, config: Optional[sc.EngineConfig] = None) -> None:
        self.cfg = config or sc.EngineConfig()

    # -- public API ---------------------------------------------------------

    def evaluate(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: Timeframe,
        *,
        htf_df: Optional[pd.DataFrame] = None,
        quote_volume: Optional[float] = None,
    ) -> Signal:
        """Evaluate the LAST closed candle of ``df`` and return a Signal."""
        cfg = self.cfg
        ts = _signal_time(df)
        n = len(df)

        # 1. insufficient data -> NO_TRADE (cannot compute core indicators).
        if n < cfg.min_bars:
            return Signal(
                symbol=symbol, timeframe=timeframe, signal=SignalType.NO_TRADE,
                score=0.0, raw_score=0.0, created_at=ts,
                warnings=[f"Insufficient data: {n} bars (need >= {cfg.min_bars})"],
                blocked_by=["insufficient_data"],
            )

        # 2. snapshot + 3. blocks
        snap = sc.compute_snapshot(df, cfg)
        trend_res, trend_class = sc.evaluate_trend(snap, cfg)
        struct_res, struct_class = sc.evaluate_structure(snap, cfg)
        mom_res = sc.evaluate_momentum(snap, trend_class, cfg)
        vol_res = sc.evaluate_volume(snap, cfg)
        volat_res, volat_state, atr_pct = sc.evaluate_volatility(snap, cfg)

        # 4. setup + provisional trade plan
        setup_info = sc.detect_setup(snap, trend_class, struct_class, cfg)
        setup_res = sc.evaluate_setup(setup_info, cfg)
        candidate_long = setup_info.setup != SetupType.NONE

        entry = stop = tp1 = tp2 = risk_reward = None
        stop_method = None
        invalidations: List[str] = []
        atr_v = sc._last(snap.atr)
        if candidate_long:
            entry, stop, stop_method, tp1, tp2, risk_reward, invalidations = self._build_plan(snap, cfg)

        risk_res = sc.evaluate_risk(entry, stop, risk_reward, atr_v, cfg)

        blocks = [trend_res, struct_res, mom_res, vol_res, volat_res, setup_res, risk_res]
        raw_score = float(sum(b.score for b in blocks))

        # 5. filters
        htf_trend = self._htf_trend(htf_df) if htf_df is not None else None
        rvol = sc._last(snap.rvol)
        volume_confirmed = rvol is not None and rvol >= cfg.rvol_high
        fctx = sf.FilterContext(
            n_bars=n, min_bars=cfg.min_bars, candidate_long=candidate_long,
            atr_pct=atr_pct, atr_pct_extreme=cfg.atr_pct_extreme,
            rvol=rvol, vol_sma=sc._last(snap.vol_sma),
            quote_volume=quote_volume, min_quote_volume=cfg.min_quote_volume,
            structure_class=struct_class, setup=setup_info.setup,
            risk_reward=risk_reward, min_rr=cfg.min_rr,
            htf_trend=htf_trend, volume_confirmed=volume_confirmed,
        )
        outcome = sf.apply(fctx)

        # 6. decide direction (raw_score kept separate from the final signal)
        decision_notes: List[str] = []
        if outcome.blocked:
            direction = SignalType.NO_TRADE
        elif not candidate_long:
            direction = SignalType.NEUTRAL
            decision_notes.append("No qualifying long setup -> NEUTRAL")
        elif raw_score >= cfg.min_score_long:
            direction = SignalType.LONG
        else:
            direction = SignalType.NO_TRADE
            decision_notes.append(
                f"Confluence {raw_score:.0f} below minimum {cfg.min_score_long:.0f} -> NO_TRADE"
            )

        if htf_df is not None and htf_trend is not None:
            decision_notes.append(f"HTF trend: {htf_trend.value}")
        elif candidate_long and htf_df is None:
            decision_notes.append("Higher-timeframe context not provided")

        # 7. assemble explainable Signal
        reasons: List[str] = []
        warnings: List[str] = []
        for b in blocks:
            reasons.extend(b.reasons)
            warnings.extend(b.warnings)
        warnings.extend(outcome.warnings)
        warnings.extend(decision_notes)

        take_profits = [tp for tp in (tp1, tp2) if tp is not None] if direction == SignalType.LONG else []

        signal = Signal(
            symbol=symbol,
            timeframe=timeframe,
            signal=direction,
            score=raw_score,
            raw_score=raw_score,
            reasons=reasons if direction == SignalType.LONG else [r for r in reasons],
            warnings=warnings,
            invalidation_conditions=invalidations if direction == SignalType.LONG else [],
            entry=entry if direction == SignalType.LONG else None,
            stop=stop if direction == SignalType.LONG else None,
            take_profits=take_profits,
            invalidation=stop if direction == SignalType.LONG else None,
            risk_reward=risk_reward if direction == SignalType.LONG else None,
            setup_type=setup_info.setup,
            entry_reason=setup_info.entry_reason if direction == SignalType.LONG else None,
            stop_method=stop_method if direction == SignalType.LONG else None,
            trend_class=trend_class,
            structure_class=struct_class,
            volatility_state=volat_state,
            blocked_by=outcome.block_names,
            block_scores={b.name: [round(b.score, 2), b.max_score] for b in blocks},
            created_at=ts,
        )
        logger.debug(
            "signal computed: %s raw=%.0f", direction.value, raw_score,
            extra={"symbol": symbol, "timeframe": timeframe.value},
        )
        return signal

    def evaluate_at(
        self, df: pd.DataFrame, index: int, symbol: str, timeframe: Timeframe, **kwargs
    ) -> Signal:
        """Evaluate the candle at position ``index`` using only bars 0..index.

        This is the entry point a backtester uses to walk candle-by-candle
        without ever seeing future data.
        """
        if index < 0:
            index = len(df) + index
        return self.evaluate(df.iloc[: index + 1], symbol, timeframe, **kwargs)

    # -- internals ----------------------------------------------------------

    def _build_plan(
        self, snap: sc.MarketSnapshot, cfg: sc.EngineConfig
    ) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[float], Optional[float], Optional[float], List[str]]:
        """Derive provisional entry / stop / take-profits from structure & ATR."""
        entry = sc._last(snap.close)
        atr_v = sc._last(snap.atr)
        support = snap.sr.nearest_support
        resistance = snap.sr.nearest_resistance
        invalidations: List[str] = []

        if entry is None or atr_v is None or atr_v <= 0:
            return None, None, None, None, None, None, invalidations

        # Stop: prefer a real swing low below entry within a sane ATR distance.
        stop = None
        stop_method = None
        if support is not None and support < entry:
            dist_atr = (entry - support) / atr_v
            if cfg.min_stop_atr <= dist_atr <= cfg.max_stop_atr:
                stop = support
                stop_method = "swing"
                invalidations.append(f"Close below swing low at {support:.4f}")
        if stop is None:
            stop = entry - cfg.atr_stop_mult * atr_v
            stop_method = "atr"
            invalidations.append(f"Close below {stop:.4f} (ATR {cfg.atr_stop_mult}x stop)")

        risk = entry - stop
        if risk <= 0:
            return entry, None, stop_method, None, None, None, invalidations

        tp1 = entry + 1.0 * risk
        tp2 = entry + 2.0 * risk

        # Effective R:R accounts for a nearer resistance capping the move.
        risk_reward = 2.0
        if resistance is not None and entry < resistance < tp2:
            risk_reward = (resistance - entry) / risk
            invalidations.append(f"Resistance {resistance:.4f} may cap upside before TP2")

        return entry, stop, stop_method, tp1, tp2, round(risk_reward, 2), invalidations

    def _htf_trend(self, htf_df: pd.DataFrame) -> Optional[TrendClass]:
        """Classify the higher-timeframe trend (used by the HTF-conflict filter)."""
        if htf_df is None or len(htf_df) < 30:
            return None
        try:
            htf_snap = sc.compute_snapshot(htf_df, self.cfg)
            _, tc = sc.evaluate_trend(htf_snap, self.cfg)
            return tc
        except Exception as exc:  # never let HTF analysis crash the primary signal
            logger.warning("HTF trend computation failed: %s", exc)
            return None


# --------------------------------------------------------------------------
# Explainability rendering
# --------------------------------------------------------------------------

def format_signal(signal: Signal) -> str:
    """Human-readable explanation of a Signal (✓ reasons / ⚠ warnings)."""
    lines: List[str] = []
    lines.append(f"{signal.symbol}  {signal.timeframe.value}")
    lines.append(f"SIGNAL: {signal.direction.value}")
    lines.append(f"SCORE: {signal.score:.0f}/100  ({signal.confidence_label.value})")
    if signal.raw_score != signal.score:
        lines.append(f"RAW SCORE: {signal.raw_score:.0f}/100")
    if signal.setup_type:
        lines.append(f"SETUP: {signal.setup_type.value}")
    if signal.direction == SignalType.LONG:
        lines.append(f"Entry: {signal.entry}")
        lines.append(f"Stop:  {signal.stop}  ({signal.stop_method})")
        if signal.take_profit_1 is not None:
            lines.append(f"TP1:   {signal.take_profit_1:.4f}")
        if signal.take_profit_2 is not None:
            lines.append(f"TP2:   {signal.take_profit_2:.4f}")
        if signal.risk_reward is not None:
            lines.append(f"R:R:   1:{signal.risk_reward}")
    if signal.reasons:
        lines.append("WHY:")
        lines.extend(f"  ✓ {r}" for r in signal.reasons)
    if signal.warnings:
        lines.append("WARNINGS:")
        lines.extend(f"  ⚠ {w}" for w in signal.warnings)
    if signal.invalidation_conditions:
        lines.append("INVALIDATION:")
        lines.extend(f"  - {c}" for c in signal.invalidation_conditions)
    if signal.blocked_by:
        lines.append(f"BLOCKED BY: {', '.join(signal.blocked_by)}")
    lines.append(f"Timestamp: {signal.timestamp:%Y-%m-%d %H:%M UTC}")
    return "\n".join(lines)


def _signal_time(df: pd.DataFrame) -> datetime:
    """Deterministic signal timestamp = close time of the last candle."""
    if df is None or len(df) == 0:
        return datetime.now(timezone.utc)
    if "close_time" in df.columns:
        return datetime.fromtimestamp(int(df["close_time"].iloc[-1]) / 1000, tz=timezone.utc)
    if isinstance(df.index, pd.DatetimeIndex):
        idx = df.index[-1]
        return idx.to_pydatetime() if idx.tzinfo else idx.tz_localize("UTC").to_pydatetime()
    return datetime.now(timezone.utc)
