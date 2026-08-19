"""Phase 9 CLI — run the offline LONG+SHORT validation and write VALIDATION_REPORT.md.

    python validate.py                       # default: BTCUSDT,ETHUSDT @ 1h, 1500 bars
    python validate.py --symbols BTCUSDT --timeframes 1h,4h --bars 2000

It attempts REAL Binance public history first; when unreachable (e.g. network
blocked) it falls back to clearly-labelled SYNTHETIC data and says so in the
report. It never evades a block and never places an order. Parameters are FIXED
across TRAIN / VALIDATION / OUT-OF-SAMPLE and every walk-forward window — nothing
is optimised on validation or out-of-sample data.

Headless: imports no Streamlit.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import List, Optional

from backtesting import (
    ValidationConfig,
    detect_overfitting,
    edge_verdict,
    final_table,
    load_history,
    validate_split,
    walk_forward,
)
from core.enums import Timeframe

_MIN_BARS_NEEDED = 900   # need enough for a warmup + 3 segments to produce trades


def _f(x: Optional[float], nd: int = 2) -> str:
    return "N/A" if x is None else f"{x:,.{nd}f}"


def _table_md(rows: List[dict]) -> str:
    head = ("| Direction | Trades | Win % | Profit Factor | Expectancy (R) | "
            "Net PnL | Max DD | Max DD % | Sharpe | Sortino | Avg R |")
    sep = "|" + "---|" * 11
    out = [head, sep]
    for r in rows:
        flag = " ⚠small" if r["small_sample"] else ""
        out.append(
            f"| **{r['direction']}**{flag} | {r['trades']} | {_f(r['win_rate'],1)} | "
            f"{_f(r['profit_factor'])} | {_f(r['expectancy_r'],3)} | {_f(r['net_pnl'])} | "
            f"{_f(r['max_drawdown'])} | {_f(r['max_drawdown_pct'],1)} | {_f(r['sharpe'])} | "
            f"{_f(r['sortino'])} | {_f(r['average_r'],3)} |"
        )
    return "\n".join(out)


def _r_distribution(rs: List[float]) -> str:
    if not rs:
        return "no trades"
    buckets = {"≤-1R": 0, "-1..0R": 0, "0..1R": 0, "1..2R": 0, ">2R": 0}
    for r in rs:
        if r <= -1:
            buckets["≤-1R"] += 1
        elif r < 0:
            buckets["-1..0R"] += 1
        elif r < 1:
            buckets["0..1R"] += 1
        elif r < 2:
            buckets["1..2R"] += 1
        else:
            buckets[">2R"] += 1
    return " · ".join(f"{k}: {v}" for k, v in buckets.items())


def _segment_md(seg, title: str) -> List[str]:
    lines = [f"### {title} ({seg.n_bars} bars)", ""]
    lines.append(_table_md(final_table(seg)))
    bh = seg.buy_hold_return_pct
    lines.append("")
    lines.append(f"- Buy-and-hold over this segment: **{_f(bh, 2)}%** "
                 "(passive baseline for comparison).")
    combined = seg.reports["COMBINED"]
    lines.append(f"- Max exposure observed (COMBINED): {_f(combined.max_exposure_pct, 1)}% of equity.")
    lines.append(f"- Consecutive losses (COMBINED): {combined.consecutive_losses}.")
    lines.append(f"- R-multiple distribution (COMBINED): {_r_distribution(combined.r_multiples)}.")
    return lines


def build_report(entries: List[dict], cfg: ValidationConfig) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L: List[str] = []
    L.append("# VALIDATION REPORT — LONG + SHORT (offline quantitative validation)")
    L.append("")
    L.append("> ⚠️ **Not financial advice. No Mainnet, no real money, no orders placed.** "
             "All figures are observed on a finite historical/simulated sample. Past observed "
             "performance does not indicate future results. This report never claims a strategy "
             "is profitable, safe, guaranteed, or that it will win.")
    L.append("")
    L.append(f"Generated: {now}")
    L.append("")
    L.append("## Method")
    L.append("")
    L.append("- **Same `SignalEngine`** decides LONG and SHORT (no re-deciding, no look-ahead: "
             "`evaluate_at` uses bars 0..i only). LONG / SHORT rows isolate one side via an "
             "execution filter over the *same* signals; COMBINED executes both.")
    L.append("- **Chronological** TRAIN "
             f"({cfg.train_pct:.0%}) / VALIDATION ({cfg.val_pct:.0%}) / OUT-OF-SAMPLE "
             f"({1 - cfg.train_pct - cfg.val_pct:.0%}) — never shuffled.")
    L.append("- **Walk-forward**: rolling windows (train "
             f"{cfg.wf_train} / test {cfg.wf_test} bars); only trades OPENING in the test region "
             "are counted (genuine OOS with warmup).")
    L.append(f"- **Fees** {cfg.fee_rate*100:.3f}%/side (real Binance Spot taker default); "
             f"**slippage** {cfg.slippage_rate*100:.3f}%/side (conservative).")
    L.append("- **Parameters are FIXED** across every segment and window. Nothing is optimised on "
             "VALIDATION or OUT-OF-SAMPLE data.")
    L.append("")
    real = [e for e in entries if e["source"] == "BINANCE"]
    L.append(f"**Data source:** {'REAL Binance history' if real else 'SYNTHETIC (Binance unreachable from this environment)'} "
             f"— {len(entries)} symbol/timeframe run(s).")
    L.append("")

    for e in entries:
        sym, tf = e["symbol"], e["timeframe"]
        L.append("---")
        L.append(f"## {sym} · {tf}  —  source: **{e['source']}**")
        L.append(f"_{e['note']}_")
        L.append("")
        sv = e["split"]
        if sv is None:
            L.append("Insufficient data to validate this symbol/timeframe.")
            L.append("")
            continue
        L.extend(_segment_md(sv.train, "TRAIN"))
        L.append("")
        L.extend(_segment_md(sv.validation, "VALIDATION"))
        L.append("")
        L.extend(_segment_md(sv.out_of_sample, "OUT-OF-SAMPLE (hold-out)"))
        L.append("")

        L.append("#### Out-of-sample edge verdict & overfitting check")
        for d in ("LONG", "SHORT", "COMBINED"):
            v = edge_verdict(sv.out_of_sample.reports[d])
            of = detect_overfitting(sv.train.reports[d], sv.out_of_sample.reports[d])
            L.append(f"- **{d}** — {v}")
            if of["overfitting_suspected"]:
                L.append(f"  - ⚠️ Overfitting suspected: {'; '.join(of['reasons'])}.")
            elif of["reasons"]:
                L.append(f"  - Note: {'; '.join(of['reasons'])}.")
        L.append("")

        wf = e["walk_forward"]
        L.append(f"#### Walk-forward (aggregated over {wf.n_windows} rolling OOS windows)")
        if wf.n_windows == 0:
            L.append("- Not enough bars for a walk-forward schedule at this window size.")
        else:
            L.append("| Direction | Trades | Net PnL | Win % | Profit Factor | Expectancy (R) |")
            L.append("|---|---|---|---|---|---|")
            for d in ("LONG", "SHORT", "COMBINED"):
                a = wf.aggregate[d]
                flag = " ⚠small" if a["small_sample"] else ""
                L.append(f"| **{d}**{flag} | {a['trades']} | {_f(a['net_pnl'])} | "
                         f"{_f(a['win_rate'],1)} | {_f(a['profit_factor'])} | {_f(a['expectancy_r'],3)} |")
        L.append("")

    L.append("---")
    L.append("## Overall reading")
    L.append("")
    L.append(_overall(entries))
    L.append("")
    L.append("## Caveats")
    L.append("")
    L.append("- Confluence weights/thresholds are hand-set on **both** sides and are NOT a proven "
             "edge; they must be validated, not trusted.")
    L.append("- SHORT is simulated with a futures-style margin model; **Spot cannot short** and "
             "no SHORT is ever executed on Spot in this build.")
    L.append("- Risk-adjusted ratios (Sharpe/Sortino) on small samples are unreliable and flagged.")
    L.append("- The economic goal ($50–100/day) is aspirational only; nothing here was tuned to it "
             "and no result should be read as evidence it is achievable.")
    L.append("")
    L.append("_Historical / simulated on a finite sample. No live orders were placed. No Mainnet._")
    return "\n".join(L)


def _overall(entries: List[dict]) -> str:
    """One honest paragraph: is there OOS edge evidence anywhere?"""
    any_edge = False
    total_oos = {"LONG": 0, "SHORT": 0, "COMBINED": 0}
    for e in entries:
        oos = e["split"].out_of_sample.reports
        for d in ("LONG", "SHORT", "COMBINED"):
            total_oos[d] += oos[d].trades
            r = oos[d]
            if (r.trades >= 20 and r.expectancy_r and r.expectancy_r > 0
                    and r.profit_factor and r.profit_factor > 1.0):
                any_edge = True
    counts = ", ".join(f"{d}={n}" for d, n in total_oos.items())
    if not any_edge:
        return (f"Across all runs, the out-of-sample segments do **not** provide sufficient "
                f"statistical evidence of a durable edge for LONG, SHORT or COMBINED "
                f"(out-of-sample trade counts: {counts}). Treat the system as unproven and do "
                f"NOT progress to Futures Testnet on this basis. More real data, more OOS trades, "
                f"and stable paper results are required before any edge claim.")
    return (f"Some out-of-sample segment(s) show a WEAK positive signal (out-of-sample trade "
            f"counts: {counts}). This is NOT proof of a durable edge — it must be reproduced on "
            f"more real data and in live-paper before it can be trusted. Do not raise risk to "
            f"chase a target.")


def run(symbols: List[str], timeframes: List[Timeframe], bars: int,
        prefer_real: bool = True) -> tuple:
    cfg = ValidationConfig()
    entries: List[dict] = []
    for sym in symbols:
        for tf in timeframes:
            data = load_history(sym, tf, bars, prefer_real=prefer_real)
            if len(data.df) < _MIN_BARS_NEEDED:
                entries.append({"symbol": sym, "timeframe": tf.value, "source": data.source,
                                "note": f"{data.note} — insufficient bars ({len(data.df)}) for validation",
                                "split": None, "walk_forward": None})
                continue
            split = validate_split(data.df, sym, tf, cfg, source=data.source)
            wf = walk_forward(data.df, sym, tf, cfg)
            entries.append({"symbol": sym, "timeframe": tf.value, "source": data.source,
                            "note": data.note, "split": split, "walk_forward": wf})
    return entries, cfg


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Offline LONG+SHORT validation (no Mainnet).")
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    p.add_argument("--timeframes", default="1h")
    p.add_argument("--bars", type=int, default=1500)
    p.add_argument("--out", default="VALIDATION_REPORT.md")
    p.add_argument("--synthetic-only", action="store_true",
                   help="skip the real-data attempt entirely")
    args = p.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    timeframes = [Timeframe.from_value(t.strip()) for t in args.timeframes.split(",") if t.strip()]

    print(f"Validating {symbols} @ {[t.value for t in timeframes]} on {args.bars} bars "
          f"({'synthetic only' if args.synthetic_only else 'real-first, synthetic fallback'}) ...")
    entries, cfg = run(symbols, timeframes, args.bars, prefer_real=not args.synthetic_only)
    report = build_report(entries, cfg)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
