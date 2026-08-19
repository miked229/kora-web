"""Performance benchmark for the signal/backtest hot path (no trading, no network).

Measures the prepared per-bar evaluation vs the legacy per-bar recompute, and a
full backtest at several bar counts, so the O(n^2) -> O(n) hardening is visible
and regressions are easy to spot.

    python benchmark.py            # default bar counts
    python benchmark.py --bars 600,1500,4000
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import List

from backtesting import BacktestConfig, BacktestEngine, synthetic_history
from core.enums import Timeframe
from signals import SignalEngine

TF = Timeframe.H1


def _bench_eval(bars: int) -> dict:
    eng = SignalEngine()
    df = synthetic_history(bars, TF, seed=7)

    t0 = time.perf_counter()
    for i in range(len(df)):
        eng.evaluate_at(df, i, "BTCUSDT", TF)
    recompute = time.perf_counter() - t0

    t0 = time.perf_counter()
    prep = eng.prepare(df)
    for i in range(len(df)):
        prep.signal_at(i, "BTCUSDT", TF)
    prepared = time.perf_counter() - t0

    return {"bars": bars, "recompute_s": recompute, "prepared_s": prepared,
            "speedup": (recompute / prepared) if prepared else float("inf")}


def _bench_backtest(bars: int) -> dict:
    df = synthetic_history(bars, TF, seed=7)
    t0 = time.perf_counter()
    r = BacktestEngine(config=BacktestConfig()).run(df, "BTCUSDT", TF)
    return {"bars": bars, "backtest_s": time.perf_counter() - t0, "trades": len(r.trades)}


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Signal/backtest performance benchmark.")
    p.add_argument("--bars", default="600,1500")
    p.add_argument("--with-recompute", action="store_true",
                   help="also time the legacy per-bar recompute (slow at high bar counts)")
    args = p.parse_args(argv)
    counts = [int(x) for x in args.bars.split(",") if x.strip()]

    print("=== per-bar evaluation (prepared vs legacy recompute) ===")
    if args.with_recompute:
        for n in counts:
            r = _bench_eval(n)
            print(f"  {r['bars']:>5} bars: recompute {r['recompute_s']:7.2f}s | "
                  f"prepared {r['prepared_s']:6.2f}s | speedup {r['speedup']:5.1f}x")
    else:
        print("  (pass --with-recompute to time the legacy path; it is O(n^2))")

    print("=== full backtest (prepared path) ===")
    for n in counts:
        r = _bench_backtest(n)
        print(f"  {r['bars']:>5} bars: {r['backtest_s']:6.2f}s  ({r['trades']} trades)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
