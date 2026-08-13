# IMPLEMENTATION REPORT — Symmetric LONG + SHORT

> This documents the extension of the **existing** Binance Trading Scanner from a
> LONG-only system to a professional **symmetric LONG + SHORT** system. The engine
> was extended in place — there is **no second bot, no duplicated SignalEngine /
> RiskEngine / scoring, and no second backtester**. The LONG code path is
> byte-identical to before (proven by the pre-existing test suite staying green).

> ⚠️ **Not financial advice. No real-money orders. No Mainnet.** Scores measure the
> strength of the system's confluence rules — **not** a probability of profit.
> Backtest / paper / testnet results are historical or simulated and are **not**
> evidence of profitability.

---

## 1. Architecture & signal flow (unchanged shape)

```
MARKET DATA → INDICATORS (causal) → SIGNAL ENGINE
   → { LONG blocks , SHORT blocks }  (evaluated INDEPENDENTLY)
   → LONG / SHORT / NEUTRAL / NO_TRADE
   → FILTERS (direction-aware) → RISK (direction-aware plan + R:R)
   → BACKTEST ↔ PAPER (same Simulator) → BINANCE SPOT TESTNET (LONG only)
   → [future] FUTURES backend for real SHORT
```

The `SignalEngine` remains the **only** source of signals; the backtester, paper
trader and testnet session all drive the **same `backtesting.Simulator`**.

## 2. How LONG works

Unchanged. The seven confluence blocks (Trend 25 / Structure 20 / Momentum 15 /
Volume 15 / Volatility 10 / Setup 10 / Risk 5) score bullish conditions; a long
setup produces a plan with **stop < entry**, **TP1/TP2 > entry**, and R:R capped
by the nearest resistance. If `long_score ≥ min_score_long` and no filter vetoes
it → `LONG`.

## 3. How SHORT works (new, independent of LONG)

SHORT is the **mirror**, evaluated **independently** ("no LONG" is never a SHORT):

- **Trend**: price < EMA200, EMA20 < EMA50 < EMA200, ADX strong with **−DI > +DI**.
- **Momentum**: **MACD negative** (line < signal & hist < 0); RSI healthy-bearish
  zone (default 30–55) *in a non-bullish context*; StochRSI %K turning down from
  the upper half. RSI is confluence, never an isolated "RSI<30 = trade".
- **Structure**: BEARISH_STRUCTURE (LH/LL), confirmed **breakdown**, price below
  the nearest **resistance** (a short leans on resistance / swing highs — support
  is never reused as a short stop).
- **Volume/OBV/VWAP**: RVOL confirming a **down** candle, **OBV falling**, price
  **below VWAP**.
- **Volatility**: identical protection both sides (extreme ATR% blocks either).
- **Setup**: bearish trend-continuation / rally-into-EMA20 pullback / breakdown /
  range-breakdown.
- **Plan**: **stop > entry** (swing high or ATR), **TP1 = entry − 1R**,
  **TP2 = entry − 2R**, R:R capped by nearest **support**.

If `short_score ≥ min_score_short` and no filter vetoes it → `SHORT`. `long_score`
and `short_score` are stored **separately** on every `Signal`.

## 4. How NO_TRADE / NEUTRAL work

- `NEUTRAL` — no qualifying setup in **either** direction.
- `NO_TRADE` — a setup existed but was rejected: low score, **ambiguous direction**
  (both sides qualify within `direction_ambiguity_margin` → NO_TRADE), invalid
  structure, HTF conflict, extreme volatility, poor R:R, invalid entry/stop/TP,
  low liquidity, bad filters, invalid risk. `raw_score` is always preserved for
  auditing even when the trade is blocked.

## 5. How Risk works (direction-aware)

- Risk-per-unit `= abs(entry − stop)` with the stop enforced on the correct side.
- Position sizing (`backtesting.portfolio.position_size(side=…)`): `qty =
  (capital · risk%) / risk_per_unit`, capped by exposure, cash and **exchange
  filters** (stepSize/minQty/minNotional), rounded then re-validated; failure →
  no trade.
- **Critical invariants** (asserted by tests): LONG never `stop ≥ entry` or
  `TP ≤ entry`; SHORT never `stop ≤ entry` or `TP ≥ entry`.

## 6. How Backtest works (same engine, both directions)

`backtesting.Simulator` opens/closes LONG or SHORT: direction-aware intrabar
resolution (`resolve_candle` — SHORT stop hit by highs, TPs by lows, gap-up fills
the stop at the open), direction-aware `leg_pnl`, signed portfolio `market_value`
(long-only equity byte-identical), and direction-aware cash flows. No look-ahead
(`evaluate_at` uses bars 0..i). TRAIN / OUT-OF-SAMPLE split unchanged. Metrics
report total/win-rate/PF/expectancy/net PnL/fees/avg win-loss/max DD/equity curve.

## 7. How Paper works

The paper trader drives the **same Simulator**, so LONG **and** SHORT are
identical to the backtest — proven by `test_backtest_parity` over bull, crash,
**bear** and **pump** scenarios. Position `direction` is persisted across
restarts; order sides are labelled correctly (SHORT opens SELL / covers BUY).

## 8. What runs on Spot Testnet (this phase)

- **LONG**: signalled → risk/safety checked → **executed** on Binance Spot
  Testnet (fake money) via `SafeExecutor`.
- **SHORT**: signalled, backtested and paper-traded, but **NOT executed**. The
  `SpotTestnetExecution` backend refuses SHORT ("SHORT EXECUTION BACKEND NOT
  ENABLED FOR SPOT"); the session journals `EXECUTION_SKIPPED` and **never sends a
  spot SELL-to-open order**. `BINANCE_ENV=testnet` and `--testnet-check` are
  unchanged (still place no orders).

## 9. What needs Futures for real SHORT

`FuturesTestnetExecution` is the abstraction for the future short-capable path
(`supports_short=True`) but is **deliberately `available=False`** in this build,
so it refuses every direction — the mirror of "no mainnet order client exists".
Enabling real SHORT execution requires implementing a Futures Testnet order
client and wiring it behind the same `SafeExecutor` gate. **Not done here.**

## 10. Anti-overtrading

`trading.OvertradingGuard`: cooldown bars, min signal separation, **max trades /
day**, and **consecutive-loss protection** — applied to LONG and SHORT alike.
Existing gates kept: max open positions, max daily loss, max total exposure,
per-order notional, whitelist, duplicate-signal (idempotent `client_order_id`).

## 11. Idempotency & recovery

Unchanged and still enforced: deterministic `client_order_id` (side+tag → no
BUY/SELL collision), reconcile-before-assume, crash recovery from SQLite. Paper
position serialization now includes `direction`.

## 12. Files ADDED

- `trading/execution_backend.py` — `ExecutionBackend`, `SpotTestnetExecution`,
  `FuturesTestnetExecution`, `ExecutionDecision`.
- `trading/overtrading.py` — `OvertradingConfig`, `OvertradingGuard`.
- `IMPLEMENTATION_REPORT.md` — this file.

## 13. Files MODIFIED

- `core/enums.py` — `SignalType.SHORT` (+ `is_directional`, `sign`).
- `core/models.py` — `Signal.long_score` / `short_score` (additive, 0..100).
- `signals/scoring.py` — SHORT mirror block evaluators + direction-aware
  `evaluate_risk` + `min_score_short` / ambiguity margin / bear RSI thresholds.
- `signals/signal_filters.py` — direction-aware (HTF conflict inverts per side).
- `signals/signal_engine.py` — evaluate both sides independently, decide with
  ambiguity → NO_TRADE, direction-aware plan, `format_signal` shows both scores.
- `backtesting/trade.py`, `execution.py`, `portfolio.py`, `simulator.py` —
  direction-aware position, intrabar resolution, sizing, accounting.
- `paper_trading/engine.py` — persist `direction`, direction-aware order sides.
- `trading/testnet_session.py` — backend gate + overtrading guard + direction-
  aware entry/exit (defence in depth).
- `dashboard/_ui.py`, `signal_details.py`, `chart.py`, `scanner.py`,
  `service.py`, `execution.py` — LONG/SHORT scores, SHORT plans, backend status.
- `tests/…` — SHORT signal, backtest, execution, paper parity, trading tests.

## 14. Files KEPT (unchanged, reused as-is)

`indicators/*` (already emit `breakout_down`, resistance, bearish classes),
`binance/*`, `data/*`, `backtesting/metrics.py` / `report.py` / `data_split.py`,
`trading/executor.py` / `kill_switch.py` / `safety.py` / `reconciliation.py` /
`store.py`, `config.py`, `core/logger.py` / `exceptions.py`.

## 15. Tests run / passed / failed

- Full offline suite: **283 passed, 1 skipped** (`pytest`, fully offline).
- Baseline before this work: 260 passed / 1 skipped → **+23 new SHORT tests**,
  added across `test_signals`, `test_backtest`, `test_execution`,
  `test_paper_engine`, `test_trading`. LONG paths unchanged / byte-identical.
- Critical-invariant tests included: LONG never `stop≥entry`/`TP≤entry`; SHORT
  never `stop≤entry`/`TP≥entry`; a downtrend yields SHORTs and **never** a LONG;
  a bear scenario places **zero** exchange orders while surfacing the SHORT.
- **Failed: none** (suite green at commit time).

## 16. Warnings & pending risks

- **Weights/thresholds are hand-set**, now on **both** sides — they are NOT a
  statistical edge and must be validated by backtesting/OOS before any belief in
  profitability. The SHORT thresholds are the mirror of the LONG defaults and are
  equally unvalidated.
- SHORT accounting in the backtest uses a **futures-style** margin model (short
  sells at open, buys to cover); this is a *simulation* only — Spot cannot short.
- In this environment Binance is network-blocked; live/testnet paths are
  validated with deterministic mocks only.
- The economic goal ($50–100/day) is **aspirational only**. Nothing here was
  tuned to fake it; risk was not raised to chase it. Statistical edge,
  consistency, drawdown control, expectancy and OOS robustness must be
  established first.

## 17. Next step

1. Run a **symmetric backtest** (LONG+SHORT) with TRAIN/VALIDATION/OOS on real
   history and review PF / expectancy / max DD / consecutive losses **per side**.
2. Run **paper** in parallel for stability, then **LONG-only** Spot Testnet.
3. Only if a real, robust edge is demonstrated: implement the Futures Testnet
   order client behind `SafeExecutor` to enable **SHORT execution** — still
   Testnet, still no Mainnet, still no real money.
