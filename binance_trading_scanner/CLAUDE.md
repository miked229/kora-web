# CLAUDE.md — Working agreement for this project

**Read this file before modifying anything in `binance_trading_scanner/`.**

## Project overview

A modular Binance **Spot** market scanner and analysis platform. It evolves in
phases from market data → indicators → confluence signals → dashboard →
backtesting → paper trading → (opt-in) Binance Testnet Demo Mode. **Live
trading is out of scope and disabled.**

The purpose is research and education. Nothing in this project may present a
strategy or signal as profitable or guaranteed.

## Architecture

- `core/` — shared vocabulary and validated models. No I/O.
  - `enums.py`, `exceptions.py`, `logger.py`, `models.py`
- `config.py` — env-driven `Settings` (Pydantic). **Never stores secrets.**
- `binance/` — exchange I/O.
  - `client.py` public REST (retries, backoff, rate-limit handling)
  - `market_data.py` validated candles/tickers + DataFrames
  - `exchange_info.py` symbol validation & trading rules
  - `websocket.py`, `demo_trader.py` — scaffolds for later phases
- `data/` — `database.py` (SQLite), `cache.py` (TTL), `candles.py` (incremental)
- `indicators/`, `strategies/`, `signals/`, `risk/`, `backtesting/`,
  `alerts/`, `dashboard/` — one concern per module.
- `tests/` — offline pytest suite (HTTP mocked).

Keep business logic **out** of `dashboard/`. Every module must be importable
and unit-testable in isolation.

## Coding standards

- Python 3.11+, type hints, `from __future__ import annotations`.
- Validate all external data at the boundary via `core/models.py`. Downstream
  code never handles raw Binance dicts.
- Fail with the typed exceptions in `core/exceptions.py`, not bare `Exception`.
- One symbol failing must never abort a scan — catch, log, continue.
- No look-ahead bias: signals/backtests use **closed** candles only
  (`is_closed`, `get_closed_klines`).
- Log via `core/logger.get_logger(...)`; concise, greppable, UTC timestamps.

## Commands

```bash
pip install -r requirements.txt   # install
pytest                            # run tests (offline)
python app.py --check             # connectivity self-check (BTCUSDT/ETHUSDT)
streamlit run app.py              # dashboard
```

## Testing requirements

- Tests must run **offline** — mock the REST client (see `tests/conftest.py`),
  never hit the network in CI.
- Cover edge cases: zero volume, missing/duplicate candle, out-of-order data,
  API timeout, rate limit, invalid symbol, insufficient balance, min order
  size, invalid precision.
- Run `pytest` and confirm green before committing. Add tests with each phase;
  do not delete the future-phase placeholders — replace them.

## Security rules (non-negotiable)

- **Never** hardcode `BINANCE_API_KEY` / `BINANCE_API_SECRET`.
- Secrets come from `.env` (git-ignored) via the environment, read on demand.
- **Never** log, print, render in Streamlit, or store secrets in SQLite.
- Keep `.gitignore` covering `.env*` (except `.env.example`).
- The database layer actively refuses credential-like keys — keep that guard.

## Binance API rules

- Use only **official, currently-supported** REST endpoints and WebSocket
  streams. Before adding or changing an endpoint, consult the current official
  Binance Spot API / WebSocket / Testnet docs; if old and new docs disagree,
  follow the current docs. Do not invent endpoints.
- Handle reconnection, timeouts, rate limits (HTTP 429/418, `Retry-After`),
  disconnects, incomplete data, timestamps and duplicates.
- Assume a WebSocket connection is not permanent (≤24h; expect scheduled
  reconnects and ping/pong).
- Public market data needs no credentials. Account/signed endpoints target the
  **Testnet** only, and only in the opt-in Demo phase.

## No live trading without explicit approval

- There is intentionally **no mainnet order client**. The only order-placing
  client is `binance/testnet_client.BinanceTestnetClient`, which refuses any
  non-testnet host. Do not add a mainnet order client without an explicit,
  written request from the project owner.
- The `trading.SafeExecutor` is the single order gate: idempotency → kill switch
  → safety checks → routing. `TradingState.DISABLED` (default) sends nothing;
  `TESTNET` routes only to Testnet; `LIVE` is blocked (and even fully confirmed
  it raises, because no mainnet client exists).
- `enable_live_trading()` requires `TRADING_LIVE=true` + `ENABLE_LIVE_CONFIRMATION
  =true` in the environment AND a manual confirmation — and even then, no live
  order can be placed in this build.
- Test `tests/test_hardening.py::test_no_mainnet_order_client_exists` guards that
  no code path reaches a mainnet order endpoint; keep it passing.
- `binance/demo_trader.py` raises rather than sending orders.

## Development process

Work phase by phase. After each phase: run tests, check for errors, explain
what was built, and only continue when the phase is functional. Do not attempt
to build everything at once.
