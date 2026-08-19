"""Phase 9 — professional, offline quantitative validation of LONG + SHORT.

Everything here is **read-only analysis**: it drives the existing
``BacktestEngine`` (the SAME ``SignalEngine`` for LONG and SHORT, no look-ahead)
over chronological TRAIN / VALIDATION / OUT-OF-SAMPLE segments and rolling
walk-forward windows, then reports honest statistics **separately for LONG,
SHORT and COMBINED**. Parameters are FIXED across every segment — nothing is
tuned on the validation or out-of-sample data.

No orders, no Mainnet, no real money. Language is strictly statistical: this
module never calls a result "profitable", "guaranteed", "safe" or "winning".
When the sample is too small or the out-of-sample edge is absent, it says so.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from core.enums import Timeframe

from signals import SignalEngine

from .data_split import walk_forward_windows
from .engine import BacktestConfig, BacktestEngine, BacktestResult, clean_frame
from .execution import ExecutionConfig
from .metrics import Metrics
from .portfolio import RiskLimits

# Directions we report on. COMBINED executes both; LONG/SHORT isolate one side
# using the SAME signals (execution filter only — see BacktestConfig).
LONG = frozenset({"LONG"})
SHORT = frozenset({"SHORT"})
COMBINED = frozenset({"LONG", "SHORT"})

_MIN_TRADES_FOR_EDGE = 20     # below this, no reliable edge claim is possible


@dataclass
class ValidationConfig:
    capital: float = 10_000.0
    risk_per_trade: float = 0.01
    fee_rate: float = 0.001          # real Binance Spot taker default (0.10%/side)
    slippage_rate: float = 0.0005    # conservative (0.05%/side)
    train_pct: float = 0.50          # TRAIN = first 50%
    val_pct: float = 0.25            # VALIDATION = next 25%; OOS = final 25%
    wf_train: int = 400              # walk-forward train window (bars)
    wf_test: int = 150               # walk-forward test window (bars)
    min_bars: Optional[int] = None

    def backtest_config(self, directions: frozenset) -> BacktestConfig:
        return BacktestConfig(
            capital=self.capital,
            risk_per_trade=self.risk_per_trade,
            limits=RiskLimits(risk_per_trade=self.risk_per_trade),
            execution=ExecutionConfig(fee_rate=self.fee_rate, slippage_rate=self.slippage_rate),
            min_bars=self.min_bars,
            allowed_directions=directions,
        )


@dataclass
class DirectionReport:
    """Per-direction result on one data segment."""
    direction: str                       # "LONG" | "SHORT" | "COMBINED"
    trades: int
    win_rate: Optional[float]
    profit_factor: Optional[float]
    expectancy_usdt: Optional[float]
    expectancy_r: Optional[float]
    net_pnl: float
    net_return_pct: Optional[float]
    max_drawdown: float
    max_drawdown_pct: float
    sharpe: Optional[float]
    sortino: Optional[float]
    average_win: Optional[float]
    average_loss: Optional[float]
    average_r: Optional[float]
    median_r: Optional[float]
    consecutive_losses: int
    max_exposure_pct: float
    r_multiples: List[float] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    small_sample: bool = False

    @classmethod
    def from_result(cls, direction: str, result: BacktestResult) -> "DirectionReport":
        m: Metrics = result.metrics
        rs = [round(t.r_multiple, 3) for t in result.trades]
        return cls(
            direction=direction,
            trades=m.total_trades,
            win_rate=m.win_rate,
            profit_factor=m.profit_factor,
            expectancy_usdt=m.expectancy_usdt,
            expectancy_r=m.expectancy_r,
            net_pnl=m.net_pnl,
            net_return_pct=m.net_return_pct,
            max_drawdown=m.max_drawdown,
            max_drawdown_pct=m.max_drawdown_pct,
            sharpe=m.sharpe,
            sortino=m.sortino,
            average_win=m.average_win,
            average_loss=m.average_loss,
            average_r=m.average_r,
            median_r=m.median_r,
            consecutive_losses=m.consecutive_losses,
            max_exposure_pct=peak_exposure_pct(result.equity_curve),
            r_multiples=rs,
            warnings=list(m.warnings),
            small_sample=m.total_trades < _MIN_TRADES_FOR_EDGE,
        )


@dataclass
class SegmentValidation:
    label: str                           # "TRAIN" | "VALIDATION" | "OUT_OF_SAMPLE"
    symbol: str
    timeframe: str
    n_bars: int
    buy_hold_return_pct: Optional[float]
    reports: dict                        # {"LONG": DirectionReport, ...}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def buy_and_hold_return_pct(df: pd.DataFrame) -> Optional[float]:
    """Passive baseline: percentage change of close over the segment."""
    if df is None or len(df) < 2:
        return None
    first = float(df["close"].iloc[0])
    last = float(df["close"].iloc[-1])
    if first <= 0:
        return None
    return (last / first - 1.0) * 100.0


def peak_exposure_pct(equity_curve) -> float:
    """Observed peak deployed-capital fraction, from the equity curve.

    ``equity - cash`` is the (signed) mark-to-market value of the open position;
    its magnitude over equity is the fraction of capital at work. Flat bars are 0.
    """
    peak = 0.0
    for p in equity_curve:
        if p.equity > 0:
            peak = max(peak, abs(p.equity - p.cash) / p.equity * 100.0)
    return peak


def precompute_signals(engine: SignalEngine, df: pd.DataFrame, symbol: str,
                       timeframe: Timeframe) -> list:
    """Compute the signal for every (cleaned) bar ONCE.

    The signal never depends on which directions are executed, so LONG/SHORT/
    COMBINED runs over the same bars can share this list instead of recomputing
    identical snapshots three times. Aligned to ``clean_frame(df)`` — exactly what
    ``BacktestEngine.run`` iterates over."""
    clean = clean_frame(df)
    prep = engine.prepare(clean)
    return [prep.signal_at(i, symbol, timeframe) for i in range(len(clean))]


def run_segment(df: pd.DataFrame, symbol: str, timeframe: Timeframe,
                cfg: ValidationConfig, label: str,
                signal_engine=None) -> SegmentValidation:
    """Run LONG-only, SHORT-only and COMBINED backtests on one segment.

    Signals are computed once and reused across the three direction runs (they
    only differ in execution, not in the signal)."""
    eng = signal_engine or SignalEngine()
    signals = precompute_signals(eng, df, symbol, timeframe) if len(df) else None
    reports = {}
    for name, directions in (("LONG", LONG), ("SHORT", SHORT), ("COMBINED", COMBINED)):
        engine = BacktestEngine(eng, cfg.backtest_config(directions))
        res = engine.run(df, symbol, timeframe, label=f"{label}:{name}", signals=signals)
        reports[name] = DirectionReport.from_result(name, res)
    return SegmentValidation(
        label=label, symbol=symbol, timeframe=timeframe.value, n_bars=len(df),
        buy_hold_return_pct=buy_and_hold_return_pct(df), reports=reports,
    )


# --------------------------------------------------------------------------
# Chronological TRAIN / VALIDATION / OUT-OF-SAMPLE
# --------------------------------------------------------------------------

@dataclass
class SplitValidation:
    symbol: str
    timeframe: str
    source: str
    train: SegmentValidation
    validation: SegmentValidation
    out_of_sample: SegmentValidation


def validate_split(df: pd.DataFrame, symbol: str, timeframe: Timeframe,
                   cfg: ValidationConfig, source: str = "SYNTHETIC",
                   signal_engine=None) -> SplitValidation:
    """Chronological TRAIN / VALIDATION / OOS split (never shuffled)."""
    n = len(df)
    train_cut = int(n * cfg.train_pct)
    val_cut = int(n * (cfg.train_pct + cfg.val_pct))
    train_df = df.iloc[:train_cut].reset_index(drop=True)
    val_df = df.iloc[train_cut:val_cut].reset_index(drop=True)
    oos_df = df.iloc[val_cut:].reset_index(drop=True)
    return SplitValidation(
        symbol=symbol, timeframe=timeframe.value, source=source,
        train=run_segment(train_df, symbol, timeframe, cfg, "TRAIN", signal_engine),
        validation=run_segment(val_df, symbol, timeframe, cfg, "VALIDATION", signal_engine),
        out_of_sample=run_segment(oos_df, symbol, timeframe, cfg, "OUT_OF_SAMPLE", signal_engine),
    )


# --------------------------------------------------------------------------
# Walk-forward validation (rolling OOS windows; parameters FIXED)
# --------------------------------------------------------------------------

@dataclass
class WalkForwardReport:
    symbol: str
    timeframe: str
    n_windows: int
    aggregate: dict                      # {"LONG": DirectionReport-like dict, ...}
    per_window: List[dict] = field(default_factory=list)


def walk_forward(df: pd.DataFrame, symbol: str, timeframe: Timeframe,
                 cfg: ValidationConfig, signal_engine=None) -> WalkForwardReport:
    """Rolling walk-forward with the SAME fixed parameters (no optimisation on any
    window). Each window runs the engine over TRAIN+TEST together so the test
    region has proper warmup, then counts ONLY the trades that OPEN inside the
    test region — a genuine, causal out-of-sample slice with no look-ahead."""
    windows = walk_forward_windows(len(df), cfg.wf_train, cfg.wf_test)
    per_window: List[dict] = []
    agg_trades = {"LONG": [], "SHORT": [], "COMBINED": []}
    agg_net = {"LONG": 0.0, "SHORT": 0.0, "COMBINED": 0.0}

    eng = signal_engine or SignalEngine()
    for w in windows:
        combined = df.iloc[w.train_start:w.test_end].reset_index(drop=True)
        # First open_time of the TEST region: trades entering at/after it are OOS.
        test_open_time = int(df["open_time"].iloc[w.test_start])
        row = {"window": w.index, "test_bars": w.test_end - w.test_start}
        signals = precompute_signals(eng, combined, symbol, timeframe)
        for name, directions in (("LONG", LONG), ("SHORT", SHORT), ("COMBINED", COMBINED)):
            engine = BacktestEngine(eng, cfg.backtest_config(directions))
            res = engine.run(combined, symbol, timeframe, label=f"WF{w.index}:{name}", signals=signals)
            oos_trades = [t for t in res.trades if t.entry_timestamp >= test_open_time]
            net = sum(t.net_pnl for t in oos_trades)
            rs = [t.r_multiple for t in oos_trades]
            row[name] = {"trades": len(oos_trades), "net_pnl": round(net, 2),
                         "expectancy_r": (statistics.fmean(rs) if rs else None)}
            agg_trades[name].extend(oos_trades)
            agg_net[name] += net
        per_window.append(row)

    aggregate = {}
    for name in ("LONG", "SHORT", "COMBINED"):
        rs = [t.r_multiple for t in agg_trades[name]]
        wins = [t for t in agg_trades[name] if t.net_pnl > 0]
        losers = [t for t in agg_trades[name] if t.net_pnl < 0]
        gp = sum(t.net_pnl for t in wins)
        gl = -sum(t.net_pnl for t in losers)
        aggregate[name] = {
            "trades": len(agg_trades[name]),
            "net_pnl": round(agg_net[name], 2),
            "win_rate": (len(wins) / len(agg_trades[name]) * 100.0) if agg_trades[name] else None,
            "profit_factor": (gp / gl) if gl > 0 else None,
            "expectancy_r": statistics.fmean(rs) if rs else None,
            "average_r": statistics.fmean(rs) if rs else None,
            "small_sample": len(agg_trades[name]) < _MIN_TRADES_FOR_EDGE,
        }
    return WalkForwardReport(symbol=symbol, timeframe=timeframe.value,
                             n_windows=len(windows), aggregate=aggregate, per_window=per_window)


# --------------------------------------------------------------------------
# Overfitting detection & edge verdict (conservative language only)
# --------------------------------------------------------------------------

def detect_overfitting(train: DirectionReport, oos: DirectionReport) -> dict:
    """Compare TRAIN vs OUT-OF-SAMPLE for one direction. Heuristic, not proof."""
    reasons: List[str] = []
    flag = False
    te, oe = train.expectancy_r, oos.expectancy_r
    if te is not None and oe is not None:
        if te > 0 and oe <= 0:
            flag = True
            reasons.append(f"expectancy flips from +{te:.3f}R (train) to {oe:.3f}R (OOS)")
        elif te > 0 and oe < 0.5 * te:
            flag = True
            reasons.append(f"expectancy degrades >50% ({te:.3f}R → {oe:.3f}R)")
    tpf, opf = train.profit_factor, oos.profit_factor
    if tpf is not None and tpf > 1.2 and (opf is None or opf < 1.0):
        flag = True
        reasons.append(f"profit factor collapses ({tpf:.2f} train → "
                       f"{'N/A' if opf is None else f'{opf:.2f}'} OOS)")
    if oos.small_sample:
        reasons.append(f"OOS has only {oos.trades} trades — degradation cannot be assessed reliably")
    return {"overfitting_suspected": flag, "reasons": reasons}


def edge_verdict(oos: DirectionReport) -> str:
    """Conservative statement about out-of-sample edge evidence."""
    if oos.trades < _MIN_TRADES_FOR_EDGE:
        return (f"INSUFFICIENT EVIDENCE — only {oos.trades} out-of-sample trades "
                f"(need ≥ {_MIN_TRADES_FOR_EDGE}); no edge can be claimed.")
    pf = oos.profit_factor
    er = oos.expectancy_r
    if er is None or er <= 0 or pf is None or pf <= 1.0:
        return ("NO POSITIVE EDGE in the out-of-sample segment "
                f"(expectancy {('N/A' if er is None else f'{er:.3f}R')}, "
                f"profit factor {('N/A' if pf is None else f'{pf:.2f}')}).")
    return ("WEAK POSITIVE SIGNAL out-of-sample "
            f"(expectancy {er:.3f}R, profit factor {pf:.2f}). This is NOT proof of "
            "a durable edge; validate on more data and live-paper before trusting it.")


# --------------------------------------------------------------------------
# Final LONG / SHORT / COMBINADO table
# --------------------------------------------------------------------------

_TABLE_COLUMNS = [
    "trades", "win_rate", "profit_factor", "expectancy_r", "net_pnl",
    "max_drawdown", "sharpe", "sortino", "average_r",
]


def final_table(segment: SegmentValidation) -> List[dict]:
    """The required LONG / SHORT / COMBINADO summary table for one segment."""
    rows = []
    for name, es in (("LONG", "LONG"), ("SHORT", "SHORT"), ("COMBINADO", "COMBINED")):
        r: DirectionReport = segment.reports[es]
        rows.append({
            "direction": name,
            "trades": r.trades,
            "win_rate": r.win_rate,
            "profit_factor": r.profit_factor,
            "expectancy_r": r.expectancy_r,
            "net_pnl": r.net_pnl,
            "max_drawdown": r.max_drawdown,
            "max_drawdown_pct": r.max_drawdown_pct,
            "sharpe": r.sharpe,
            "sortino": r.sortino,
            "average_r": r.average_r,
            "small_sample": r.small_sample,
        })
    return rows
