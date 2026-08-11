"""Backtest reporting: structured summary, distributions and curves.

Language is deliberately statistical (spec 36). This module NEVER labels a result
"profitable", "guaranteed", "safe" or "high probability". It describes observed,
historical, in-sample / out-of-sample performance on a sample, with drawdown.
"""
from __future__ import annotations

from typing import List, Optional

from .engine import BacktestResult
from .trade import Trade

_DISCLAIMER = (
    "Historical, in-sample simulation on a finite sample. Past observed "
    "performance does not indicate future results. No live orders were placed."
)


def _fmt(x: Optional[float], nd: int = 2) -> str:
    return "N/A" if x is None else f"{x:,.{nd}f}"


def summary_dict(result: BacktestResult) -> dict:
    m = result.metrics
    return {
        "Symbol": result.symbol,
        "Timeframe": result.timeframe,
        "Sample": result.label,
        "Period start (ms)": result.period_start,
        "Period end (ms)": result.period_end,
        "Initial Capital": result.initial_capital,
        "Final Equity": result.final_equity,
        "Net Return %": m.net_return_pct,
        "Total Trades": m.total_trades,
        "Win Rate %": m.win_rate,
        "Profit Factor": m.profit_factor,
        "Expectancy (quote/trade)": m.expectancy_usdt,
        "Expectancy (R/trade)": m.expectancy_r,
        "Max Drawdown": m.max_drawdown,
        "Max Drawdown %": m.max_drawdown_pct,
        "Sharpe": m.sharpe,
        "Sortino": m.sortino,
        "Calmar": m.calmar,
        "Fees": m.fees,
        "Slippage": m.slippage,
        "Risk-blocked entries": result.risk_blocked,
    }


def drawdown_curve(result: BacktestResult) -> List[dict]:
    return [{"timestamp": p.timestamp, "equity": p.equity,
             "drawdown": p.drawdown, "drawdown_pct": p.drawdown_pct}
            for p in result.equity_curve]


def equity_curve(result: BacktestResult) -> List[dict]:
    return [{"timestamp": p.timestamp, "cash": p.cash, "equity": p.equity}
            for p in result.equity_curve]


def trade_distribution(trades: List[Trade]) -> dict:
    """R / PnL / win-loss / duration distributions (spec 30)."""
    if not trades:
        return {"r": [], "pnl": [], "wins": 0, "losses": 0, "breakeven": 0, "durations": []}
    wins = sum(1 for t in trades if t.net_pnl > 0)
    losses = sum(1 for t in trades if t.net_pnl < 0)
    breakeven = len(trades) - wins - losses
    return {
        "r": [round(t.r_multiple, 3) for t in trades],
        "pnl": [round(t.net_pnl, 4) for t in trades],
        "wins": wins, "losses": losses, "breakeven": breakeven,
        "durations": [t.duration_bars for t in trades],
        "exit_reasons": _count([t.exit_reason.value for t in trades]),
    }


def signal_stats(result: BacktestResult) -> dict:
    """Signal-log analytics: how many signals, blocked, and strong-but-blocked."""
    log = result.signal_log
    directions = _count([e["direction"] for e in log])
    blocked = [e for e in log if e["blocked_by"]]
    strong_blocked = sum(1 for e in blocked if e["raw_score"] and e["raw_score"] > 80)
    executed = sum(1 for e in log if e["executed"])
    return {
        "total_signals": len(log),
        "by_direction": directions,
        "blocked_signals": len(blocked),
        "executed_signals": executed,
        "raw_score_gt_80_but_blocked": strong_blocked,
    }


def _count(items: List[str]) -> dict:
    out: dict = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return out


def format_report(result: BacktestResult) -> str:
    m = result.metrics
    s = summary_dict(result)
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("BACKTEST SUMMARY (observed / historical — not advice)")
    lines.append("=" * 60)
    lines.append(f"Symbol:            {s['Symbol']}  {s['Timeframe']}  [{s['Sample']}]")
    lines.append(f"Initial Capital:   {_fmt(result.initial_capital)}")
    lines.append(f"Final Equity:      {_fmt(result.final_equity)}")
    lines.append(f"Net Return:        {_fmt(m.net_return_pct)}%")
    lines.append(f"Total Trades:      {m.total_trades}")
    lines.append(f"Win Rate:          {_fmt(m.win_rate)}%")
    lines.append(f"Profit Factor:     {_fmt(m.profit_factor)}")
    lines.append(f"Expectancy:        {_fmt(m.expectancy_usdt)} quote/trade "
                 f"({_fmt(m.expectancy_r)} R/trade)")
    lines.append(f"Max Drawdown:      {_fmt(m.max_drawdown)} ({_fmt(m.max_drawdown_pct)}%)")
    lines.append(f"Sharpe:            {_fmt(m.sharpe)}   Sortino: {_fmt(m.sortino)}   "
                 f"Calmar: {_fmt(m.calmar)}")
    lines.append(f"Fees:              {_fmt(m.fees)}")
    lines.append(f"Slippage:          {_fmt(m.slippage)}")
    lines.append(f"Risk-blocked:      {result.risk_blocked}")
    if m.warnings:
        lines.append("-" * 60)
        lines.append("NOTES / CAVEATS:")
        for w in m.warnings:
            lines.append(f"  • {w}")
    ss = signal_stats(result)
    lines.append("-" * 60)
    lines.append(f"Signals: {ss['total_signals']} total, "
                 f"{ss['executed_signals']} executed, {ss['blocked_signals']} blocked, "
                 f"{ss['raw_score_gt_80_but_blocked']} with raw score > 80 but blocked.")
    dq = result.data_quality
    if dq.get("messages"):
        lines.append("-" * 60)
        lines.append("DATA QUALITY:")
        for msg in dq["messages"]:
            lines.append(f"  • {msg}")
    lines.append("-" * 60)
    lines.append(_DISCLAIMER)
    lines.append("=" * 60)
    return "\n".join(lines)
