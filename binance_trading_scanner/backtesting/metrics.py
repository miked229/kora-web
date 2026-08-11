"""Backtest metrics — computed honestly, with None/NaN where undefined.

Nothing here is invented: when a statistic cannot be computed in a
statistically meaningful way (no trades, no losing trades, too few return
observations, zero volatility) the value is ``None`` and a plain-language reason
is added to ``warnings`` (spec 17, 18, 20). Profit factor is never reported as
infinity.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from core.enums import Timeframe

from .portfolio import EquityPoint
from .trade import Trade

_MS_PER_YEAR = 365.25 * 24 * 3600 * 1000
_MIN_RETURNS_FOR_RATIOS = 30   # below this, Sharpe/Sortino are flagged unreliable


@dataclass
class Metrics:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Optional[float] = None
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    net_return_pct: Optional[float] = None
    average_trade: Optional[float] = None
    average_win: Optional[float] = None
    average_loss: Optional[float] = None
    profit_factor: Optional[float] = None
    expectancy_usdt: Optional[float] = None   # units: quote currency per trade
    expectancy_r: Optional[float] = None       # units: R per trade
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    calmar: Optional[float] = None
    average_r: Optional[float] = None
    median_r: Optional[float] = None
    largest_win: Optional[float] = None
    largest_loss: Optional[float] = None
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    average_trade_duration_bars: Optional[float] = None
    # documentation of assumptions / why a metric is None
    return_frequency: Optional[str] = None
    annualization_bars_per_year: Optional[float] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def compute_metrics(
    trades: List[Trade],
    equity_curve: List[EquityPoint],
    initial_capital: float,
    timeframe: Timeframe,
    final_equity: Optional[float] = None,
) -> Metrics:
    m = Metrics()
    tf_ms = timeframe.milliseconds
    m.annualization_bars_per_year = _MS_PER_YEAR / tf_ms
    m.return_frequency = f"per-{timeframe.value}-bar equity returns"

    if final_equity is None:
        final_equity = equity_curve[-1].equity if equity_curve else initial_capital
    if initial_capital > 0:
        m.net_return_pct = (final_equity / initial_capital - 1.0) * 100.0

    # Drawdown from the equity curve
    if equity_curve:
        m.max_drawdown = max(p.drawdown for p in equity_curve)
        m.max_drawdown_pct = max(p.drawdown_pct for p in equity_curve)

    m.total_trades = len(trades)
    if not trades:
        m.warnings.append("No trades: trade-based metrics are undefined for this sample.")
        _ratios_from_equity(m, equity_curve)
        return m

    nets = [t.net_pnl for t in trades]
    rs = [t.r_multiple for t in trades]
    winners = [t for t in trades if t.net_pnl > 0]
    losers = [t for t in trades if t.net_pnl < 0]

    m.winning_trades = len(winners)
    m.losing_trades = len(losers)
    m.win_rate = len(winners) / len(trades) * 100.0
    m.gross_pnl = sum(t.gross_pnl for t in trades)
    m.net_pnl = sum(nets)
    m.fees = sum(t.fees for t in trades)
    m.slippage = sum(t.slippage for t in trades)
    m.average_trade = statistics.fmean(nets)
    m.average_win = statistics.fmean([t.net_pnl for t in winners]) if winners else None
    m.average_loss = statistics.fmean([t.net_pnl for t in losers]) if losers else None
    m.largest_win = max(nets) if nets else None
    m.largest_loss = min(nets) if nets else None
    m.average_r = statistics.fmean(rs)
    m.median_r = statistics.median(rs)
    m.expectancy_usdt = statistics.fmean(nets)
    m.expectancy_r = statistics.fmean(rs)
    m.average_trade_duration_bars = statistics.fmean([t.duration_bars for t in trades])

    # Profit factor — never infinity.
    gross_profit = sum(t.net_pnl for t in winners)
    gross_loss = -sum(t.net_pnl for t in losers)
    if gross_loss > 0:
        m.profit_factor = gross_profit / gross_loss
    else:
        m.profit_factor = None
        m.warnings.append("Profit factor undefined: no losing trades in this sample (not infinity).")

    m.consecutive_wins, m.consecutive_losses = _streaks(trades)
    _ratios_from_equity(m, equity_curve)
    return m


def _streaks(trades: List[Trade]) -> tuple[int, int]:
    best_w = best_l = cur_w = cur_l = 0
    for t in trades:
        if t.net_pnl > 0:
            cur_w += 1
            cur_l = 0
        elif t.net_pnl < 0:
            cur_l += 1
            cur_w = 0
        else:
            cur_w = cur_l = 0
        best_w = max(best_w, cur_w)
        best_l = max(best_l, cur_l)
    return best_w, best_l


def _ratios_from_equity(m: Metrics, equity_curve: List[EquityPoint]) -> None:
    """Sharpe / Sortino / Calmar from per-bar equity returns, with caveats."""
    if len(equity_curve) < 2:
        m.warnings.append("Too few equity points for risk-adjusted ratios.")
        return
    eq = [p.equity for p in equity_curve]
    returns = [(eq[i] / eq[i - 1] - 1.0) for i in range(1, len(eq)) if eq[i - 1] > 0]
    if len(returns) < 2:
        m.warnings.append("Too few return observations for Sharpe/Sortino.")
        return

    bpy = m.annualization_bars_per_year or 1.0
    mean = statistics.fmean(returns)
    stdev = statistics.pstdev(returns)
    if stdev > 0:
        m.sharpe = mean / stdev * math.sqrt(bpy)
    else:
        m.warnings.append("Sharpe undefined: zero return volatility in sample.")

    downside = [min(r, 0.0) for r in returns]
    dd = math.sqrt(statistics.fmean([d * d for d in downside]))
    if dd > 0:
        m.sortino = mean / dd * math.sqrt(bpy)
    else:
        m.warnings.append("Sortino undefined: no downside volatility in sample.")

    # Calmar = annualised return / |max drawdown %|
    if m.max_drawdown_pct > 0 and eq[0] > 0:
        n = len(eq) - 1
        cagr = (eq[-1] / eq[0]) ** (bpy / n) - 1.0 if n > 0 else 0.0
        m.calmar = (cagr * 100.0) / m.max_drawdown_pct
    else:
        m.warnings.append("Calmar undefined: zero drawdown in sample.")

    if len(returns) < _MIN_RETURNS_FOR_RATIOS:
        m.warnings.append(
            f"Risk-adjusted ratios are based on {len(returns)} observations; "
            "treat Sharpe/Sortino/Calmar as unreliable for such a small sample. "
            "Equity includes flat (no-position) bars, which is deliberately conservative."
        )
