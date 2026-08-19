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

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from core.enums import (
    SetupType,
    SignalType,
    Timeframe,
    TrendClass,
)
from core.logger import get_logger
from core.models import Signal
from indicators.structure import (
    StructureState,
    SupportResistance,
    swing_highs,
    swing_lows,
)

from . import scoring as sc
from . import signal_filters as sf

logger = get_logger("signals.engine")


@dataclass
class _SideEval:
    """Everything computed for ONE direction (LONG or SHORT) in a single bar."""
    side: SignalType
    blocks: list
    raw_score: float
    setup_info: "sc.SetupInfo"
    candidate: bool
    entry: Optional[float]
    stop: Optional[float]
    stop_method: Optional[str]
    tp1: Optional[float]
    tp2: Optional[float]
    risk_reward: Optional[float]
    invalidations: List[str]
    outcome: "sf.FilterOutcome"


@dataclass
class _Prepared:
    """Precomputed context for fast candle-by-candle evaluation over ONE frame.

    The full snapshot (all causal indicators) is computed ONCE; each bar reads a
    cheap slice of the precomputed series plus an incrementally-derived structure
    /support-resistance state. Because every indicator is causal and swing pivots
    are only counted once confirmed (index <= i - swing_right), the per-bar result
    is bit-for-bit identical to recomputing the snapshot on ``df.iloc[:i+1]`` — with
    no look-ahead. See tests/test_perf.py for the equivalence proof.
    """
    engine: "SignalEngine"
    df: pd.DataFrame
    full: "sc.MarketSnapshot"
    bb_width_mean: pd.Series
    right: int
    hi_idx: np.ndarray
    hi_val: np.ndarray
    lo_idx: np.ndarray
    lo_val: np.ndarray
    close_ffill: np.ndarray
    max_levels: int = 5

    @property
    def n(self) -> int:
        return len(self.df)

    def _structure_at(self, i: int) -> StructureState:
        cut = i - self.right
        k_hi = int(np.searchsorted(self.hi_idx, cut, side="right"))
        k_lo = int(np.searchsorted(self.lo_idx, cut, side="right"))
        st = StructureState()
        if k_hi >= 1:
            st.last_swing_high = float(self.hi_val[k_hi - 1])
        if k_hi >= 2:
            st.prev_swing_high = float(self.hi_val[k_hi - 2])
            st.higher_high = st.last_swing_high > st.prev_swing_high
            st.lower_high = st.last_swing_high < st.prev_swing_high
        if k_lo >= 1:
            st.last_swing_low = float(self.lo_val[k_lo - 1])
        if k_lo >= 2:
            st.prev_swing_low = float(self.lo_val[k_lo - 2])
            st.higher_low = st.last_swing_low > st.prev_swing_low
            st.lower_low = st.last_swing_low < st.prev_swing_low
        if st.higher_high and st.higher_low:
            st.trend = "up"
        elif st.lower_high and st.lower_low:
            st.trend = "down"
        elif st.last_swing_high is not None and st.last_swing_low is not None:
            st.trend = "range"
        return st

    def _sr_at(self, i: int) -> SupportResistance:
        cut = i - self.right
        k_hi = int(np.searchsorted(self.hi_idx, cut, side="right"))
        k_lo = int(np.searchsorted(self.lo_idx, cut, side="right"))
        res_levels = [float(x) for x in self.hi_val[:k_hi]]
        sup_levels = [float(x) for x in self.lo_val[:k_lo]]
        sr = SupportResistance()
        sr.resistance_levels = res_levels[-self.max_levels:]
        sr.support_levels = sup_levels[-self.max_levels:]
        price = self.close_ffill[i]
        if price != price:   # NaN: no valid close yet
            return sr
        price = float(price)
        res_above = [lv for lv in res_levels if lv >= price]
        sup_below = [lv for lv in sup_levels if lv <= price]
        sr.nearest_resistance = min(res_above) if res_above else None
        sr.nearest_support = max(sup_below) if sup_below else None
        return sr

    def snapshot_at(self, i: int) -> "sc.MarketSnapshot":
        f = self.full
        s = slice(0, i + 1)
        return sc.MarketSnapshot(
            df=self.df.iloc[s],
            close=f.close.iloc[s], high=f.high.iloc[s], low=f.low.iloc[s],
            open=f.open.iloc[s], volume=f.volume.iloc[s],
            ema20=f.ema20.iloc[s], ema50=f.ema50.iloc[s], ema200=f.ema200.iloc[s],
            sma200=f.sma200.iloc[s], adx=f.adx.iloc[s], rsi=f.rsi.iloc[s],
            macd=f.macd.iloc[s], stoch=f.stoch.iloc[s], atr=f.atr.iloc[s],
            bb=f.bb.iloc[s], bb_width=f.bb_width.iloc[s], vol_sma=f.vol_sma.iloc[s],
            rvol=f.rvol.iloc[s], obv=f.obv.iloc[s], vwap=f.vwap.iloc[s],
            structure=self._structure_at(i), breakout=f.breakout.iloc[s],
            sr=self._sr_at(i), bb_width_mean=self.bb_width_mean.iloc[s],
        )

    def signal_at(self, i: int, symbol: str, timeframe: Timeframe,
                  quote_volume: Optional[float] = None) -> Signal:
        cfg = self.engine.cfg
        n = i + 1
        ts = _signal_time(self.df.iloc[: i + 1])
        if n < cfg.min_bars:
            return self.engine._insufficient(symbol, timeframe, n, ts)
        snap = self.snapshot_at(i)
        return self.engine._signal_from_snapshot(
            snap, symbol, timeframe, ts, n, None, False, quote_volume)


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
            return self._insufficient(symbol, timeframe, n, ts)

        # 2. snapshot (recompute path) + shared decision core.
        snap = sc.compute_snapshot(df, cfg)
        htf_trend = self._htf_trend(htf_df) if htf_df is not None else None
        return self._signal_from_snapshot(
            snap, symbol, timeframe, ts, n, htf_trend, htf_df is not None, quote_volume)

    def _insufficient(self, symbol, timeframe, n: int, ts) -> Signal:
        cfg = self.cfg
        return Signal(
            symbol=symbol, timeframe=timeframe, signal=SignalType.NO_TRADE,
            score=0.0, raw_score=0.0, created_at=ts,
            warnings=[f"Insufficient data: {n} bars (need >= {cfg.min_bars})"],
            blocked_by=["insufficient_data"],
        )

    def _signal_from_snapshot(
        self, snap: "sc.MarketSnapshot", symbol: str, timeframe: Timeframe, ts,
        n: int, htf_trend, htf_present: bool, quote_volume: Optional[float],
    ) -> Signal:
        """Shared decision core: snapshot -> Signal. Used by both the recompute
        path (``evaluate``) and the prepared fast path (``evaluate_prepared``)."""
        cfg = self.cfg
        # 2. shared (direction-neutral) blocks
        atr_v = sc._last(snap.atr)
        volat_res, volat_state, atr_pct = sc.evaluate_volatility(snap, cfg)
        # trend/structure CLASSIFICATION is the same regardless of side; only the
        # per-side block SCORES differ. Compute the class once via the long
        # evaluators (byte-identical to the previous long-only path).
        trend_res, trend_class = sc.evaluate_trend(snap, cfg)
        struct_res, struct_class = sc.evaluate_structure(snap, cfg)

        rvol = sc._last(snap.rvol)
        volume_confirmed = rvol is not None and rvol >= cfg.rvol_high

        # 3-5. evaluate BOTH directions independently (blocks, plan, filters)
        long_side = self._evaluate_side(
            SignalType.LONG, snap, cfg, trend_res, struct_res, trend_class, struct_class,
            volat_res, atr_v, atr_pct, n, htf_trend, rvol, volume_confirmed, quote_volume,
        )
        short_side = self._evaluate_side(
            SignalType.SHORT, snap, cfg, None, None, trend_class, struct_class,
            volat_res, atr_v, atr_pct, n, htf_trend, rvol, volume_confirmed, quote_volume,
        )

        long_ok = (long_side.candidate and not long_side.outcome.blocked
                   and long_side.raw_score >= cfg.min_score_long)
        short_ok = (short_side.candidate and not short_side.outcome.blocked
                    and short_side.raw_score >= cfg.min_score_short)

        # 6. decide direction + which side to REPORT (raw_score kept separate)
        decision_notes: List[str] = []
        ambiguous = (long_ok and short_ok
                     and abs(long_side.raw_score - short_side.raw_score)
                     < cfg.direction_ambiguity_margin)

        if ambiguous:
            reported = long_side if long_side.raw_score >= short_side.raw_score else short_side
            direction = SignalType.NO_TRADE
            decision_notes.append(
                "Both LONG and SHORT setups qualify within margin -> NO_TRADE (ambiguous)"
            )
        elif long_ok and (not short_ok or long_side.raw_score >= short_side.raw_score):
            reported, direction = long_side, SignalType.LONG
        elif short_ok:
            reported, direction = short_side, SignalType.SHORT
        else:
            # Neither side qualifies as a trade. Pick a side to report and a
            # non-trade outcome (NEUTRAL if no setup at all, else NO_TRADE).
            if long_side.candidate and short_side.candidate:
                reported = long_side if long_side.raw_score >= short_side.raw_score else short_side
            elif short_side.candidate and not long_side.candidate:
                reported = short_side
            else:
                reported = long_side   # backward-compatible default
            if not reported.candidate:
                direction = SignalType.NEUTRAL
                decision_notes.append("No qualifying long or short setup -> NEUTRAL")
            elif reported.outcome.blocked:
                direction = SignalType.NO_TRADE
            else:
                direction = SignalType.NO_TRADE
                floor = cfg.min_score_long if reported.side is SignalType.LONG else cfg.min_score_short
                decision_notes.append(
                    f"Confluence {reported.raw_score:.0f} below minimum {floor:.0f} -> NO_TRADE"
                )

        any_candidate = long_side.candidate or short_side.candidate
        if htf_present and htf_trend is not None:
            decision_notes.append(f"HTF trend: {htf_trend.value}")
        elif any_candidate and not htf_present:
            decision_notes.append("Higher-timeframe context not provided")

        # 7. assemble explainable Signal from the REPORTED side
        emit = direction.is_directional
        blocks = reported.blocks
        raw_score = reported.raw_score

        reasons: List[str] = []
        warnings: List[str] = []
        for b in blocks:
            reasons.extend(b.reasons)
            warnings.extend(b.warnings)
        warnings.extend(reported.outcome.warnings)
        warnings.extend(decision_notes)

        blocked_by = list(reported.outcome.block_names)
        if ambiguous:
            blocked_by.append("ambiguous_direction")

        take_profits = [tp for tp in (reported.tp1, reported.tp2) if tp is not None] if emit else []

        signal = Signal(
            symbol=symbol,
            timeframe=timeframe,
            signal=direction,
            score=raw_score,
            raw_score=raw_score,
            long_score=long_side.raw_score,
            short_score=short_side.raw_score,
            reasons=reasons,
            warnings=warnings,
            invalidation_conditions=reported.invalidations if emit else [],
            entry=reported.entry if emit else None,
            stop=reported.stop if emit else None,
            take_profits=take_profits,
            invalidation=reported.stop if emit else None,
            risk_reward=reported.risk_reward if emit else None,
            setup_type=reported.setup_info.setup,
            entry_reason=reported.setup_info.entry_reason if emit else None,
            stop_method=reported.stop_method if emit else None,
            trend_class=trend_class,
            structure_class=struct_class,
            volatility_state=volat_state,
            blocked_by=blocked_by,
            block_scores={b.name: [round(b.score, 2), b.max_score] for b in blocks},
            created_at=ts,
        )
        logger.debug(
            "signal computed: %s raw=%.0f (L=%.0f S=%.0f)",
            direction.value, raw_score, long_side.raw_score, short_side.raw_score,
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

    def prepare(self, df: pd.DataFrame) -> _Prepared:
        """Precompute a fast per-bar evaluation context for ``df`` (one frame).

        Compute the full snapshot and swing pivots ONCE; ``prep.signal_at(i, ...)``
        then evaluates bar ``i`` in O(1)-ish time with output identical to
        ``evaluate_at(df, i, ...)`` and no look-ahead."""
        cfg = self.cfg
        full = sc.compute_snapshot(df, cfg)
        bb_width_mean = full.bb_width.rolling(cfg.bb_width_lookback).mean()
        high = full.high.to_numpy(dtype="float64")
        low = full.low.to_numpy(dtype="float64")
        sh = swing_highs(full.high, cfg.swing_left, cfg.swing_right).to_numpy()
        sl = swing_lows(full.low, cfg.swing_left, cfg.swing_right).to_numpy()
        hi_idx = np.flatnonzero(sh)
        lo_idx = np.flatnonzero(sl)
        return _Prepared(
            engine=self, df=df, full=full, bb_width_mean=bb_width_mean,
            right=cfg.swing_right,
            hi_idx=hi_idx, hi_val=high[hi_idx],
            lo_idx=lo_idx, lo_val=low[lo_idx],
            close_ffill=full.close.ffill().to_numpy(dtype="float64"),
        )

    # -- internals ----------------------------------------------------------

    def _evaluate_side(
        self,
        side: SignalType,
        snap: sc.MarketSnapshot,
        cfg: sc.EngineConfig,
        shared_trend_res,
        shared_struct_res,
        trend_class: TrendClass,
        struct_class,
        volat_res,
        atr_v: Optional[float],
        atr_pct: Optional[float],
        n: int,
        htf_trend: Optional[TrendClass],
        rvol: Optional[float],
        volume_confirmed: bool,
        quote_volume: Optional[float],
    ) -> "_SideEval":
        """Evaluate one direction end-to-end: blocks, setup, plan and filters.

        The LONG path reuses the already-computed shared trend/structure blocks so
        its output is byte-identical to the previous long-only engine. The SHORT
        path uses the mirror evaluators in :mod:`signals.scoring`.
        """
        if side is SignalType.LONG:
            trend_res = shared_trend_res
            struct_res = shared_struct_res
            mom_res = sc.evaluate_momentum(snap, trend_class, cfg)
            vol_res = sc.evaluate_volume(snap, cfg)
            setup_info = sc.detect_setup(snap, trend_class, struct_class, cfg)
        else:
            trend_res, _ = sc.evaluate_trend_short(snap, cfg)
            struct_res, _ = sc.evaluate_structure_short(snap, cfg)
            mom_res = sc.evaluate_momentum_short(snap, trend_class, cfg)
            vol_res = sc.evaluate_volume_short(snap, cfg)
            setup_info = sc.detect_setup_short(snap, trend_class, struct_class, cfg)

        setup_res = sc.evaluate_setup(setup_info, cfg)
        candidate = setup_info.setup != SetupType.NONE

        entry = stop = tp1 = tp2 = risk_reward = None
        stop_method = None
        invalidations: List[str] = []
        if candidate:
            entry, stop, stop_method, tp1, tp2, risk_reward, invalidations = self._build_plan(snap, cfg, side)

        risk_res = sc.evaluate_risk(entry, stop, risk_reward, atr_v, cfg, side)

        blocks = [trend_res, struct_res, mom_res, vol_res, volat_res, setup_res, risk_res]
        raw_score = float(sum(b.score for b in blocks))

        fctx = sf.FilterContext(
            n_bars=n, min_bars=cfg.min_bars, candidate=candidate,
            atr_pct=atr_pct, atr_pct_extreme=cfg.atr_pct_extreme,
            rvol=rvol, vol_sma=sc._last(snap.vol_sma),
            quote_volume=quote_volume, min_quote_volume=cfg.min_quote_volume,
            structure_class=struct_class, setup=setup_info.setup,
            risk_reward=risk_reward, min_rr=cfg.min_rr,
            htf_trend=htf_trend, volume_confirmed=volume_confirmed,
            direction=side,
        )
        outcome = sf.apply(fctx)

        return _SideEval(
            side=side, blocks=blocks, raw_score=raw_score, setup_info=setup_info,
            candidate=candidate, entry=entry, stop=stop, stop_method=stop_method,
            tp1=tp1, tp2=tp2, risk_reward=risk_reward, invalidations=invalidations,
            outcome=outcome,
        )

    def _build_plan(
        self, snap: sc.MarketSnapshot, cfg: sc.EngineConfig, side: SignalType = SignalType.LONG,
    ) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[float], Optional[float], Optional[float], List[str]]:
        """Derive a direction-aware provisional entry / stop / take-profits.

        LONG: stop < entry, TP1/TP2 above entry, capped by nearest resistance.
        SHORT: stop > entry, TP1/TP2 below entry, capped by nearest support.
        These invariants are asserted by the critical-invariant tests.
        """
        entry = sc._last(snap.close)
        atr_v = sc._last(snap.atr)
        support = snap.sr.nearest_support
        resistance = snap.sr.nearest_resistance
        invalidations: List[str] = []

        if entry is None or atr_v is None or atr_v <= 0:
            return None, None, None, None, None, None, invalidations

        stop = None
        stop_method = None
        if side is SignalType.LONG:
            # Stop: prefer a real swing low below entry within a sane ATR distance.
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

        # SHORT — mirror of the long plan. Never reuse support as the stop.
        if resistance is not None and resistance > entry:
            dist_atr = (resistance - entry) / atr_v
            if cfg.min_stop_atr <= dist_atr <= cfg.max_stop_atr:
                stop = resistance
                stop_method = "swing"
                invalidations.append(f"Close above swing high at {resistance:.4f}")
        if stop is None:
            stop = entry + cfg.atr_stop_mult * atr_v
            stop_method = "atr"
            invalidations.append(f"Close above {stop:.4f} (ATR {cfg.atr_stop_mult}x stop)")

        risk = stop - entry
        if risk <= 0:
            return entry, None, stop_method, None, None, None, invalidations

        tp1 = entry - 1.0 * risk
        tp2 = entry - 2.0 * risk

        # Effective R:R accounts for a nearer support capping the decline.
        risk_reward = 2.0
        if support is not None and tp2 < support < entry:
            risk_reward = (entry - support) / risk
            invalidations.append(f"Support {support:.4f} may cap downside before TP2")
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
    lines.append(f"LONG SCORE:  {signal.long_score:.0f}/100")
    lines.append(f"SHORT SCORE: {signal.short_score:.0f}/100")
    if signal.setup_type:
        lines.append(f"SETUP: {signal.setup_type.value}")
    if signal.direction.is_directional:
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
