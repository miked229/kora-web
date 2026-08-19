# VALIDATION REPORT — LONG + SHORT (offline quantitative validation)

> ⚠️ **Not financial advice. No Mainnet, no real money, no orders placed.** All figures are observed on a finite historical/simulated sample. Past observed performance does not indicate future results. This report never claims a strategy is profitable, safe, guaranteed, or that it will win.

Generated: 2026-08-19 01:38 UTC

## Method

- **Same `SignalEngine`** decides LONG and SHORT (no re-deciding, no look-ahead: `evaluate_at` uses bars 0..i only). LONG / SHORT rows isolate one side via an execution filter over the *same* signals; COMBINED executes both.
- **Chronological** TRAIN (50%) / VALIDATION (25%) / OUT-OF-SAMPLE (25%) — never shuffled.
- **Walk-forward**: rolling windows (train 400 / test 150 bars); only trades OPENING in the test region are counted (genuine OOS with warmup).
- **Fees** 0.100%/side (real Binance Spot taker default); **slippage** 0.050%/side (conservative).
- **Parameters are FIXED** across every segment and window. Nothing is optimised on VALIDATION or OUT-OF-SAMPLE data.

**Data source:** SYNTHETIC (Binance unreachable from this environment) — 2 symbol/timeframe run(s).

---
## BTCUSDT · 1h  —  source: **SYNTHETIC**
_real data unavailable (BinanceConnectionError: Network error after 4 attempts: 403 Forbidden); using synthetic_

### TRAIN (750 bars)

| Direction | Trades | Win % | Profit Factor | Expectancy (R) | Net PnL | Max DD | Max DD % | Sharpe | Sortino | Avg R |
|---|---|---|---|---|---|---|---|---|---|---|
| **LONG** ⚠small | 14 | 42.9 | 0.73 | -0.269 | -123.32 | 298.90 | 3.0 | -2.01 | -2.56 | -0.269 |
| **SHORT** ⚠small | 0 | N/A | N/A | N/A | 0.00 | 0.00 | 0.0 | N/A | N/A | N/A |
| **COMBINADO** ⚠small | 14 | 42.9 | 0.73 | -0.269 | -123.32 | 298.90 | 3.0 | -2.01 | -2.56 | -0.269 |

- Buy-and-hold over this segment: **167.58%** (passive baseline for comparison).
- Max exposure observed (COMBINED): 50.3% of equity.
- Consecutive losses (COMBINED): 2.
- R-multiple distribution (COMBINED): ≤-1R: 7 · -1..0R: 1 · 0..1R: 3 · 1..2R: 3 · >2R: 0.

### VALIDATION (375 bars)

| Direction | Trades | Win % | Profit Factor | Expectancy (R) | Net PnL | Max DD | Max DD % | Sharpe | Sortino | Avg R |
|---|---|---|---|---|---|---|---|---|---|---|
| **LONG** ⚠small | 0 | N/A | N/A | N/A | 0.00 | 0.00 | 0.0 | N/A | N/A | N/A |
| **SHORT** ⚠small | 15 | 86.7 | 10.21 | 0.955 | 1,545.42 | 140.99 | 1.3 | 23.16 | 69.20 | 0.955 |
| **COMBINADO** ⚠small | 15 | 86.7 | 10.21 | 0.955 | 1,545.42 | 140.99 | 1.3 | 23.16 | 69.20 | 0.955 |

- Buy-and-hold over this segment: **-71.47%** (passive baseline for comparison).
- Max exposure observed (COMBINED): 50.2% of equity.
- Consecutive losses (COMBINED): 1.
- R-multiple distribution (COMBINED): ≤-1R: 2 · -1..0R: 0 · 0..1R: 0 · 1..2R: 13 · >2R: 0.

### OUT-OF-SAMPLE (hold-out) (375 bars)

| Direction | Trades | Win % | Profit Factor | Expectancy (R) | Net PnL | Max DD | Max DD % | Sharpe | Sortino | Avg R |
|---|---|---|---|---|---|---|---|---|---|---|
| **LONG** ⚠small | 13 | 0.0 | 0.00 | -1.024 | -1,253.19 | 1,311.38 | 13.0 | -18.45 | -19.71 | -1.024 |
| **SHORT** ⚠small | 0 | N/A | N/A | N/A | 0.00 | 0.00 | 0.0 | N/A | N/A | N/A |
| **COMBINADO** ⚠small | 13 | 0.0 | 0.00 | -1.024 | -1,253.19 | 1,311.38 | 13.0 | -18.45 | -19.71 | -1.024 |

- Buy-and-hold over this segment: **178.39%** (passive baseline for comparison).
- Max exposure observed (COMBINED): 45.8% of equity.
- Consecutive losses (COMBINED): 13.
- R-multiple distribution (COMBINED): ≤-1R: 12 · -1..0R: 1 · 0..1R: 0 · 1..2R: 0 · >2R: 0.

#### Out-of-sample edge verdict & overfitting check
- **LONG** — INSUFFICIENT EVIDENCE — only 13 out-of-sample trades (need ≥ 20); no edge can be claimed.
  - Note: OOS has only 13 trades — degradation cannot be assessed reliably.
- **SHORT** — INSUFFICIENT EVIDENCE — only 0 out-of-sample trades (need ≥ 20); no edge can be claimed.
  - Note: OOS has only 0 trades — degradation cannot be assessed reliably.
- **COMBINED** — INSUFFICIENT EVIDENCE — only 13 out-of-sample trades (need ≥ 20); no edge can be claimed.
  - Note: OOS has only 13 trades — degradation cannot be assessed reliably.

#### Walk-forward (aggregated over 7 rolling OOS windows)
| Direction | Trades | Net PnL | Win % | Profit Factor | Expectancy (R) |
|---|---|---|---|---|---|
| **LONG** | 21 | -823.11 | 28.6 | 0.30 | -0.424 |
| **SHORT** | 30 | 1,725.59 | 70.0 | 3.42 | 0.470 |
| **COMBINED** | 51 | 845.16 | 52.9 | 1.43 | 0.102 |

---
## ETHUSDT · 1h  —  source: **SYNTHETIC**
_real data unavailable (BinanceConnectionError: Network error after 4 attempts: 403 Forbidden); using synthetic_

### TRAIN (750 bars)

| Direction | Trades | Win % | Profit Factor | Expectancy (R) | Net PnL | Max DD | Max DD % | Sharpe | Sortino | Avg R |
|---|---|---|---|---|---|---|---|---|---|---|
| **LONG** ⚠small | 13 | 53.8 | 1.33 | -0.132 | 93.46 | 158.82 | 1.5 | 1.71 | 2.61 | -0.132 |
| **SHORT** ⚠small | 0 | N/A | N/A | N/A | 0.00 | 0.00 | 0.0 | N/A | N/A | N/A |
| **COMBINADO** ⚠small | 13 | 53.8 | 1.33 | -0.132 | 93.46 | 158.82 | 1.5 | 1.71 | 2.61 | -0.132 |

- Buy-and-hold over this segment: **167.58%** (passive baseline for comparison).
- Max exposure observed (COMBINED): 50.3% of equity.
- Consecutive losses (COMBINED): 2.
- R-multiple distribution (COMBINED): ≤-1R: 6 · -1..0R: 0 · 0..1R: 2 · 1..2R: 5 · >2R: 0.

### VALIDATION (375 bars)

| Direction | Trades | Win % | Profit Factor | Expectancy (R) | Net PnL | Max DD | Max DD % | Sharpe | Sortino | Avg R |
|---|---|---|---|---|---|---|---|---|---|---|
| **LONG** ⚠small | 0 | N/A | N/A | N/A | 0.00 | 0.00 | 0.0 | N/A | N/A | N/A |
| **SHORT** ⚠small | 14 | 92.9 | 11.59 | 0.940 | 1,229.28 | 131.76 | 1.3 | 19.29 | 42.74 | 0.940 |
| **COMBINADO** ⚠small | 14 | 92.9 | 11.59 | 0.940 | 1,229.28 | 131.76 | 1.3 | 19.29 | 42.74 | 0.940 |

- Buy-and-hold over this segment: **-71.46%** (passive baseline for comparison).
- Max exposure observed (COMBINED): 50.8% of equity.
- Consecutive losses (COMBINED): 1.
- R-multiple distribution (COMBINED): ≤-1R: 1 · -1..0R: 0 · 0..1R: 3 · 1..2R: 10 · >2R: 0.

### OUT-OF-SAMPLE (hold-out) (375 bars)

| Direction | Trades | Win % | Profit Factor | Expectancy (R) | Net PnL | Max DD | Max DD % | Sharpe | Sortino | Avg R |
|---|---|---|---|---|---|---|---|---|---|---|
| **LONG** ⚠small | 15 | 6.7 | 0.10 | -0.808 | -1,151.26 | 1,151.26 | 11.5 | -15.90 | -17.83 | -0.808 |
| **SHORT** ⚠small | 0 | N/A | N/A | N/A | 0.00 | 0.00 | 0.0 | N/A | N/A | N/A |
| **COMBINADO** ⚠small | 15 | 6.7 | 0.10 | -0.808 | -1,151.26 | 1,151.26 | 11.5 | -15.90 | -17.83 | -0.808 |

- Buy-and-hold over this segment: **182.63%** (passive baseline for comparison).
- Max exposure observed (COMBINED): 50.2% of equity.
- Consecutive losses (COMBINED): 9.
- R-multiple distribution (COMBINED): ≤-1R: 12 · -1..0R: 2 · 0..1R: 0 · 1..2R: 1 · >2R: 0.

#### Out-of-sample edge verdict & overfitting check
- **LONG** — INSUFFICIENT EVIDENCE — only 15 out-of-sample trades (need ≥ 20); no edge can be claimed.
  - ⚠️ Overfitting suspected: profit factor collapses (1.33 train → 0.10 OOS); OOS has only 15 trades — degradation cannot be assessed reliably.
- **SHORT** — INSUFFICIENT EVIDENCE — only 0 out-of-sample trades (need ≥ 20); no edge can be claimed.
  - Note: OOS has only 0 trades — degradation cannot be assessed reliably.
- **COMBINED** — INSUFFICIENT EVIDENCE — only 15 out-of-sample trades (need ≥ 20); no edge can be claimed.
  - ⚠️ Overfitting suspected: profit factor collapses (1.33 train → 0.10 OOS); OOS has only 15 trades — degradation cannot be assessed reliably.

#### Walk-forward (aggregated over 7 rolling OOS windows)
| Direction | Trades | Net PnL | Win % | Profit Factor | Expectancy (R) |
|---|---|---|---|---|---|
| **LONG** ⚠small | 16 | -677.37 | 25.0 | 0.24 | -0.551 |
| **SHORT** | 31 | 1,497.73 | 71.0 | 2.56 | 0.556 |
| **COMBINED** | 47 | 802.84 | 55.3 | 1.43 | 0.180 |

---
## Overall reading

Across all runs, the out-of-sample segments do **not** provide sufficient statistical evidence of a durable edge for LONG, SHORT or COMBINED (out-of-sample trade counts: LONG=28, SHORT=0, COMBINED=28). Treat the system as unproven and do NOT progress to Futures Testnet on this basis. More real data, more OOS trades, and stable paper results are required before any edge claim.

## Caveats

- Confluence weights/thresholds are hand-set on **both** sides and are NOT a proven edge; they must be validated, not trusted.
- SHORT is simulated with a futures-style margin model; **Spot cannot short** and no SHORT is ever executed on Spot in this build.
- Risk-adjusted ratios (Sharpe/Sortino) on small samples are unreliable and flagged.
- The economic goal ($50–100/day) is aspirational only; nothing here was tuned to it and no result should be read as evidence it is achievable.

_Historical / simulated on a finite sample. No live orders were placed. No Mainnet._
