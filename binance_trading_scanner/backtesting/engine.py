"""Event-driven, candle-by-candle backtesting engine.

For each candle (spec 2): fill any pending entry at THIS candle's open (the
entry scheduled by the previous candle's signal), manage the open position
against this candle's OHLC (stops / take-profits / invalidation), evaluate the
signal engine using only data up to this candle, optionally schedule an entry
for the NEXT candle, then record equity.

Guarantees:
  * The existing SignalEngine is the ONLY source of signals (``evaluate_at`` uses
    bars 0..i only) — signals are never recomputed or modified retrospectively.
  * Entry is at the NEXT candle open (no look-ahead); gaps are respected by
    filling at the actual open.
  * Stops / TPs come from the signal and are never changed after entry.
  * Intrabar SL/TP ambiguity is resolved by the configured policy (default
    conservative), never by picking the favourable outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from core.enums import Timeframe
from core.logger import get_logger
from core.models import SymbolFilters
from signals import SignalEngine

from .data_split import split_in_out
from .execution import ExecutionConfig
from .metrics import Metrics, compute_metrics
from .portfolio import Portfolio, RiskLimits
from .simulator import Simulator
from .trade import Trade

logger = get_logger("backtesting.engine")

_REQUIRED_COLS = ("open", "high", "low", "close", "volume", "open_time", "close_time")


@dataclass
class BacktestConfig:
    capital: float = 10_000.0
    risk_per_trade: float = 0.01
    limits: RiskLimits = field(default_factory=RiskLimits)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    filters: Optional[SymbolFilters] = None
    exit_on_structure_break: bool = True
    min_bars: Optional[int] = None     # defaults to the signal engine's min_bars

    def __post_init__(self) -> None:
        self.limits.risk_per_trade = self.risk_per_trade


@dataclass
class DataQualityReport:
    n_bars: int
    ordered: bool
    duplicate_count: int
    gap_count: int
    gaps: List[dict]
    ohlc_valid: bool
    volume_valid: bool
    sufficient: bool
    messages: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "n_bars": self.n_bars, "ordered": self.ordered,
            "duplicate_count": self.duplicate_count, "gap_count": self.gap_count,
            "gaps": self.gaps[:20], "ohlc_valid": self.ohlc_valid,
            "volume_valid": self.volume_valid, "sufficient": self.sufficient,
            "messages": self.messages,
        }


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    label: str
    period_start: Optional[int]
    period_end: Optional[int]
    initial_capital: float
    final_equity: float
    trades: List[Trade]
    equity_curve: list
    signal_log: List[dict]
    metrics: Metrics
    data_quality: dict
    risk_blocked: int

    @property
    def net_return_pct(self) -> Optional[float]:
        return self.metrics.net_return_pct


def check_data_quality(df: pd.DataFrame, timeframe: Timeframe, min_bars: int) -> DataQualityReport:
    """Validate timestamps, duplicates, gaps, OHLC and volume. Never fills data."""
    n = len(df)
    messages: List[str] = []
    for col in _REQUIRED_COLS:
        if col not in df.columns:
            messages.append(f"missing column '{col}'")
    if any("missing column" in m for m in messages):
        return DataQualityReport(n, False, 0, 0, [], False, False, False, messages)

    ot = df["open_time"].to_numpy()
    ordered = bool(np.all(np.diff(ot) > 0)) if n > 1 else True
    if not ordered:
        messages.append("timestamps are not strictly increasing")
    diffs = np.diff(np.sort(ot)) if n > 1 else np.array([])
    duplicate_count = int(np.sum(diffs == 0))
    if duplicate_count:
        messages.append(f"{duplicate_count} duplicate timestamp(s)")

    step = timeframe.milliseconds
    gaps = []
    if n > 1:
        d = np.diff(np.sort(np.unique(ot)))
        for k, gap in enumerate(d):
            if gap != step:
                gaps.append({"after_index": int(k), "gap_ms": int(gap), "expected_ms": int(step)})
    if gaps:
        messages.append(f"{len(gaps)} gap(s) detected (not filled — reported only)")

    o, h, l, c = (df[x].to_numpy(dtype="float64") for x in ("open", "high", "low", "close"))
    ohlc_valid = bool(
        np.all(h >= np.maximum(o, c) - 1e-9) and np.all(l <= np.minimum(o, c) + 1e-9)
        and np.all(h >= l) and np.all((o > 0) & (c > 0) & (h > 0) & (l > 0))
    )
    if not ohlc_valid:
        messages.append("invalid OHLC relationships or non-positive prices")
    vol = df["volume"].to_numpy(dtype="float64")
    volume_valid = bool(np.all(np.isfinite(vol)) and np.all(vol >= 0))
    if not volume_valid:
        messages.append("invalid volume (NaN or negative)")

    sufficient = n >= min_bars
    if not sufficient:
        messages.append(f"insufficient candles: {n} < required {min_bars}")
    return DataQualityReport(n, ordered, duplicate_count, len(gaps), gaps,
                             ohlc_valid, volume_valid, sufficient, messages)


class BacktestEngine:
    """Runs one symbol/timeframe at a time (spec 23: symbols run separately)."""

    def __init__(self, signal_engine: Optional[SignalEngine] = None,
                 config: Optional[BacktestConfig] = None) -> None:
        self.signal_engine = signal_engine or SignalEngine()
        self.config = config or BacktestConfig()

    # -- public -------------------------------------------------------------

    def run(self, df: pd.DataFrame, symbol: str, timeframe: Timeframe,
            label: str = "full") -> BacktestResult:
        cfg = self.config
        min_bars = cfg.min_bars or self.signal_engine.cfg.min_bars
        quality = check_data_quality(df, timeframe, min_bars)

        # Clean deterministically: sort, drop duplicate timestamps (keep first).
        clean = df.sort_values("open_time").drop_duplicates("open_time", keep="first").reset_index(drop=True)

        portfolio = Portfolio(cfg.capital, cfg.limits)
        trades: List[Trade] = []
        signal_log: List[dict] = []

        if not quality.sufficient or len(clean) == 0:
            metrics = compute_metrics(trades, portfolio.equity_curve, cfg.capital, timeframe, cfg.capital)
            return self._result(symbol, timeframe, label, clean, cfg.capital, cfg.capital,
                                trades, portfolio, signal_log, metrics, quality)

        opens = clean["open"].to_numpy(dtype="float64")
        highs = clean["high"].to_numpy(dtype="float64")
        lows = clean["low"].to_numpy(dtype="float64")
        closes = clean["close"].to_numpy(dtype="float64")
        otimes = clean["open_time"].to_numpy()
        ctimes = clean["close_time"].to_numpy()
        n = len(clean)

        sim = Simulator(cfg, portfolio, symbol, timeframe.value)

        for i in range(n):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            ct = int(ctimes[i])

            # Evaluate the signal at this candle close (bars 0..i only).
            sig = self.signal_engine.evaluate_at(clean, i, symbol, timeframe)
            log = {
                "timestamp": ct, "direction": sig.direction.value,
                "raw_score": round(sig.raw_score, 2), "final_score": round(sig.score, 2),
                "blocked_by": list(sig.blocked_by),
                "setup": sig.setup_type.value if sig.setup_type else None,
                "executed": False, "note": None,
            }
            signal_log.append(log)

            # Advance the shared simulator by one candle.
            res = sim.process_candle(o, h, l, c, int(otimes[i]), ct, sig, i)
            trades.extend(res.closed_trades)
            if res.opened is not None:
                for e in reversed(signal_log):
                    if e["timestamp"] == res.opened.signal_time:
                        e["executed"] = True
                        break

        # Force-close any residual position at the last close (END_OF_TEST).
        residual = sim.force_close(float(closes[-1]), int(ctimes[-1]), n - 1)
        if residual is not None:
            trades.append(residual)

        final_equity = portfolio.equity_curve[-1].equity if portfolio.equity_curve else cfg.capital
        metrics = compute_metrics(trades, portfolio.equity_curve, cfg.capital, timeframe, final_equity)
        return self._result(symbol, timeframe, label, clean, cfg.capital, final_equity,
                            trades, portfolio, signal_log, metrics, quality)

    def run_split(self, df: pd.DataFrame, symbol: str, timeframe: Timeframe,
                  train_pct: float = 0.70):
        """Return (in_sample_result, out_of_sample_result). Never mixed."""
        sp = split_in_out(df, train_pct)
        in_res = self.run(sp.train, symbol, timeframe, label="in_sample")
        out_res = self.run(sp.test, symbol, timeframe, label="out_of_sample")
        return in_res, out_res

    # -- internals ----------------------------------------------------------

    def _result(self, symbol, timeframe, label, clean, capital, final_equity,
                trades, portfolio, signal_log, metrics, quality) -> BacktestResult:
        period_start = int(clean["open_time"].iloc[0]) if len(clean) else None
        period_end = int(clean["close_time"].iloc[-1]) if len(clean) else None
        return BacktestResult(
            symbol=symbol, timeframe=timeframe.value, label=label,
            period_start=period_start, period_end=period_end,
            initial_capital=capital, final_equity=final_equity,
            trades=trades, equity_curve=portfolio.equity_curve, signal_log=signal_log,
            metrics=metrics, data_quality=quality.to_dict(), risk_blocked=portfolio.risk_blocked,
        )
