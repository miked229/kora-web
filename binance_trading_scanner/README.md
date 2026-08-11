# Binance Trading Scanner Pro

A modular, professional platform for market scanning, technical analysis,
confluence-based signal generation, backtesting and paper trading on **Binance
Spot** — built to evolve safely from research toward (optional, opt-in) demo
execution.

> ⚠️ **Not financial advice. No live orders are placed.** Scores describe the
> strength of the system's confluence rules — **not** a probability of profit.
> Trading crypto assets carries substantial risk of loss.

---

## What it does

The system is being built in disciplined phases:

| Phase | Scope | Status |
|------:|-------|--------|
| 1 | Skeleton, config, logging, models, **public Binance market data** | ✅ implemented |
| 2 | Indicators (trend / momentum / volatility / volume / structure) | ⏳ scaffolded |
| 3 | Confluence signal engine + 0–100 scoring | ⏳ scaffolded |
| 4 | Streamlit dashboard (overview, scanner, chart, settings) | 🚧 Phase 1 overview live |
| 5 | Backtesting (fees, slippage, no look-ahead, in/out-of-sample) | ⏳ scaffolded |
| 6 | Paper trading (internal simulator) | ⏳ scaffolded |
| 7 | Binance Spot **Testnet / Demo Mode** (opt-in) | ⏳ scaffolded |
| 8 | Testing / hardening | ongoing |

**Live trading is intentionally disabled** and will not be implemented without
explicit approval.

## Architecture

```
binance_trading_scanner/
├── app.py                  # Streamlit entry + headless self-check
├── config.py               # env-driven, validated settings (no secrets stored)
├── core/                   # enums, exceptions, logger, pydantic models
├── binance/                # REST client, market data, exchange info, ws/demo (scaffold)
├── data/                   # SQLite database, TTL cache, incremental candle store
├── indicators/             # trend / momentum / volatility / volume / structure
├── strategies/             # base + trend / breakout / mean-reversion / confluence
├── signals/                # signal engine, scoring, filters
├── risk/                   # position sizing, stop-loss, take-profit, risk manager
├── backtesting/            # engine, metrics, trade, report
├── alerts/                 # notifier (Streamlit/logs now, Telegram later)
├── dashboard/              # per-page Streamlit modules
└── tests/                  # pytest suite (offline; mocked HTTP)
```

Design principles: each concern is an isolated, testable module; all market
data is validated at the boundary (`core/models.py`); the dashboard holds no
business logic.

## Installation

Requires **Python 3.11+**.

```bash
cd binance_trading_scanner
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit as needed
```

## Environment variables

See `.env.example`. Public market data (Phase 1) needs **no credentials**.

| Variable | Purpose | Default |
|----------|---------|---------|
| `BINANCE_ENV` | `mainnet` or `testnet` | `mainnet` |
| `BINANCE_REST_BASE` | REST base URL (use `https://data-api.binance.vision` if `api.binance.com` is blocked) | `https://api.binance.com` |
| `APP_MODE` | `BACKTEST` / `PAPER` / `BINANCE_DEMO` / `LIVE_DISABLED` | `PAPER` |
| `CAPITAL`, `RISK_PER_TRADE` | risk sizing | `10000`, `0.01` |
| `FEE_RATE`, `SLIPPAGE_RATE` | backtest cost model | `0.001`, `0.0005` |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | **only** for Testnet/Demo (later) | empty |

Secrets are read from the environment on demand and are **never** logged,
rendered in the UI, or written to the database. `.env` is git-ignored.

## Running

Launch the dashboard:

```bash
streamlit run app.py
```

Headless connectivity self-check (prints BTCUSDT / ETHUSDT, no Streamlit
needed):

```bash
python app.py --check
```

## Testing

```bash
pytest
```

The suite is fully **offline** — the Binance REST client is exercised through a
mocked HTTP transport, so no network (or API key) is required. It covers model
validation, OHLC integrity, duplicate/gap detection, retry/rate-limit handling,
exchange-info symbol validation, scoring buckets, logging redaction and the
database secret guard.

## Modes (roadmap)

- **Backtest** — replay historical candles with fees, slippage and no
  look-ahead; separate in-sample vs out-of-sample.
- **Paper** — internal simulator: balances, fills, fees, PnL, drawdown. No real
  orders.
- **Binance Demo** — Binance Spot **Testnet** only, opt-in, credentials via
  `.env`.
- **Live** — disabled.

## Risk & limitations

- Signals and scores are **not** predictions or guarantees.
- Backtest results are hypothetical and subject to look-ahead, survivorship and
  overfitting biases; the engine mitigates but cannot eliminate them.
- Market data can be delayed, incomplete or wrong; validate before acting.
- You are solely responsible for any decisions made with this software.

## License / disclaimer

For educational and research purposes. Provided “as is”, without warranty of
any kind. Not affiliated with Binance.
