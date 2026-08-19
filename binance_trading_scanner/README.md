# Binance Trading Scanner Pro

A modular platform for market scanning, technical analysis, confluence-based
signal generation, backtesting, paper trading and **safe Binance Spot Testnet**
execution — built to evolve carefully toward (future, gated) live trading.

> ⚠️ **Not financial advice. No real-money orders are placed.** Scores describe
> the strength of the system's confluence rules — **not** a probability of
> profit. Backtest/paper/testnet results are historical/simulated and are **not**
> evidence of profitability. Trading crypto carries substantial risk of loss.

---

## Status

| Phase | Scope | Status |
|------:|-------|--------|
| 1 | Skeleton, config, logging, models, public market data | ✅ |
| 2 | Indicators (trend / momentum / volatility / volume / structure) | ✅ |
| 3 | Confluence signal engine + 0–100 scoring | ✅ |
| 4 | Streamlit dashboard | ✅ |
| 5 | Backtesting (fees, slippage, no look-ahead, in/out-of-sample) | ✅ |
| 6 | Paper trading (internal simulator, parity with backtester) | ✅ |
| 7 | Real market data + WebSocket + **Testnet safe execution** | ✅ |
| 8 | Final hardening / production readiness | ✅ |

**Live (mainnet) trading is NOT implemented.** There is intentionally no mainnet
order client, so real-money orders cannot be placed regardless of configuration.

## Architecture

```
binance_trading_scanner/
├── app.py            # Streamlit entry + CLIs: --check / --testnet-check / --live-check
├── config.py         # env-driven settings (secrets never stored on the object)
├── core/             # enums, exceptions, UTC logger (secret redaction), pydantic models
├── binance/          # REST client, market data, exchange info, websocket, testnet client
├── data/             # SQLite, TTL cache, incremental candle store
├── indicators/       # trend / momentum / volatility / volume / structure (causal)
├── signals/          # confluence engine, scoring, filters (single source of signals)
├── backtesting/      # simulator (shared core), engine, execution, portfolio, metrics,
│                     #   data_split, report
├── paper_trading/    # internal simulated account (reuses the backtester's simulator)
├── trading/          # kill switch, safety, testnet client wiring, order store,
│                     #   reconciliation, SafeExecutor, testnet session
└── dashboard/        # Streamlit pages (overview, scanner, chart, signal details,
                      #   paper, execution) + demo data
```

Design principles: one concern per module; the **SignalEngine is the only source
of signals**; the backtester, paper trader and testnet session all drive the
**same `backtesting.Simulator`** so their entry/stop/TP/fee/slippage rules can
never diverge; all market data is validated at the boundary; no look-ahead.

**Symmetric LONG + SHORT.** The engine evaluates LONG and SHORT **independently**
(a lack of a long setup is never a short) and reports a separate `long_score` /
`short_score`. LONG plans have stop < entry and TP > entry; SHORT plans mirror it
(stop > entry, TP < entry). SHORT signals are backtested and paper-traded, but
**Spot cannot short**: an `ExecutionBackend` gate (`SpotTestnetExecution`) refuses
SHORT so it is never sent as a spot SELL order. Real SHORT execution would need a
(future, currently disabled) Futures backend. See `IMPLEMENTATION_REPORT.md`.

## Modes

The dashboard always shows a permanent, unambiguous indicator:

| Indicator | Data | Orders |
|-----------|------|--------|
| 🟢 **DEMO** | synthetic | none |
| 🔵 **LIVE DATA — NO ORDERS** | real Binance market data | none |
| (Paper Trading page) | demo or live data | **internal simulation only** |
| 🟡 **TESTNET** | real/testnet data | **Binance Spot Testnet only** (fake money) |
| 🔴 **LIVE TRADING** | — | **disabled in this build** |

- **Demo** — deterministic synthetic candles; verify the UI/engine offline.
- **Live Data** — real, **closed** candles; verify the SignalEngine on real
  markets with zero orders. `LIVE MARKET DATA ≠ LIVE TRADING`.
- **Paper** — a persistent internal account (balances, orders, fills, positions,
  PnL, equity, drawdown, journal). No Binance orders. Parity-tested against the
  backtester.
- **Testnet** — orders go only to Binance Spot Testnet after passing every
  safety check.

## Installation

Requires **Python 3.11+**.

```bash
cd binance_trading_scanner
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # edit as needed
```

## Running

```bash
streamlit run app.py            # dashboard
# Headless checks (never start Streamlit; cli.py imports no Streamlit at all):
python cli.py --check           # public market-data connectivity self-check
python cli.py --testnet-check   # Testnet readiness (NO orders placed)
python cli.py --live-check      # always prints "LIVE TRADING DISABLED"
python app.py --testnet-check   # same flags also work via app.py (delegates to cli)
pytest                          # full offline test suite
```

## Strategy validation (LONG + SHORT, no Mainnet)

Quantitative, read-only validation of the strategy — chronological
TRAIN/VALIDATION/OUT-OF-SAMPLE, walk-forward, look-ahead-safe, separate LONG /
SHORT / COMBINED results, overfitting detection. It never places orders.

```bash
# REAL STRICT — real Binance history only, NO synthetic fallback. Run this on a
# machine with outbound access to Binance (e.g. your Mac). If Binance is not
# reachable it stops with "REAL DATA VALIDATION FAILED" (writes REAL_VALIDATION_REPORT.md):
python validate.py --real       # BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT @ 4h,1h

# Offline development only (clearly-labelled synthetic data, writes VALIDATION_REPORT.md):
python validate.py --synthetic-only --symbols BTCUSDT --timeframes 1h
```

Each run prints a verdict block: `REAL DATA / LONG EDGE / SHORT EDGE /
OVERFITTING / READY FOR TESTNET` (YES/NO). A result is never called profitable or
guaranteed; when the out-of-sample edge is absent or the sample is too small, the
report says so and does **not** advance to Testnet.

## Security

- Credentials come **only** from environment variables (a git-ignored `.env`).
  They are never hardcoded, logged, printed, shown in the UI, stored in SQLite,
  returned to the frontend, or committed. The testnet client redacts
  signature/auth errors.
- `.gitignore` excludes `.env`, `.env.*` (except `.env.example`) and `*.db`.
- The database layer refuses credential-like keys.

## API permissions (for a future testnet/live trading key)

The trading key must have **READ + SPOT TRADING** and **NO WITHDRAWALS**. Add an
**IP restriction** if available. See `TESTNET_SETUP.md`.

## Risk limits

Configurable and enforced on every order (nothing may violate a limit):

- `MAX_RISK_PER_TRADE`, `MAX_ORDER_NOTIONAL`, `MAX_DAILY_LOSS`,
  `MAX_OPEN_POSITIONS`, `MAX_TOTAL_EXPOSURE`, `SYMBOL_WHITELIST` (default
  BTCUSDT/ETHUSDT). Order safety also validates exchange filters (minQty,
  stepSize, tickSize, minNotional) and balance, and blocks duplicate signals.

## Kill switch & emergency stop

- Global kill switch: `TRADING_DISABLED` (default) / `TRADING_TESTNET` /
  `TRADING_LIVE`. It never changes to LIVE on its own.
- **STOP ALL TRADING** blocks new orders while preserving positions for a
  controlled exit; **Cancel open orders** is a separate action.

## Recovery

State is persisted to SQLite. On restart the app rebuilds account/positions/
orders/journal/equity and reconciles open orders with the exchange, so a crash
never creates a duplicate order. Orders are never assumed filled — status,
executed quantity, average price and fees are read back from the exchange.

## Testing

Fully **offline**: REST/WS/testnet are exercised through mocked transports; no
network or API key is required. Coverage of `trading/`, `backtesting/`,
`paper_trading/` and `binance/` is ~90%. Highlights: no-look-ahead proofs,
backtest↔paper↔testnet parity, intrabar ambiguity, crash recovery, reconciliation,
kill-switch gating, and the guarantee that no path leads from live data to a
mainnet order.

## What is NOT enabled / known limitations

- ❌ Live (mainnet) real-money trading — no mainnet order client exists.
- ❌ Withdrawals.
- Long-only Spot, one position per symbol; no portfolio correlation model yet.
- Signals/scores are not predictions; weights are hand-set and must be validated
  by backtesting, not treated as an edge.
- In this environment Binance is network-blocked, so live/testnet paths are
  validated with deterministic mocks only.

## License / disclaimer

Educational and research use. Provided "as is", without warranty. Not affiliated
with Binance.
