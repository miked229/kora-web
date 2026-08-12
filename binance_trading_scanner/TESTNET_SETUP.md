# Binance Spot Testnet — Safe Setup

This guide gets the scanner running against **Binance Spot Testnet** (fake money).
It never touches real funds. **No mainnet order client exists in this build, so
real-money orders cannot be placed regardless of configuration.**

> ⚠️ Do NOT paste API keys into chat, code, commits, or issues. Keys live only in
> a local `.env` file, which is git-ignored.

## 1. Create testnet API keys

1. Go to the official Binance Spot Testnet: <https://testnet.binance.vision>.
2. Log in (GitHub) and generate an **HMAC-SHA256** API key/secret.
3. Testnet keys are for the testnet only — they are unrelated to your real
   account and carry no real funds.

Recommended key settings for a **real** trading key later (not needed on
testnet, but the code assumes these): **READ + SPOT TRADING**, **NO
WITHDRAWALS**, and an **IP restriction** if available.

## 2. Configure `.env`

Copy the template and fill in the testnet key/secret:

```bash
cp .env.example .env
```

```dotenv
BINANCE_ENV=testnet
BINANCE_API_KEY=your_testnet_key
BINANCE_API_SECRET=your_testnet_secret

# Safety (leave at the safe defaults)
TRADING_STATE=TRADING_DISABLED     # switch to TRADING_TESTNET only when ready
TRADING_LIVE=false
ENABLE_LIVE_CONFIRMATION=false
SYMBOL_WHITELIST=BTCUSDT,ETHUSDT
MAX_ORDER_NOTIONAL=1000
```

`.env`, `.env.*` and `*.db` are already in `.gitignore`. Verify:

```bash
git check-ignore .env            # prints ".env" => ignored
```

## 3. Run the readiness check (places NO orders)

```bash
python app.py --testnet-check
```

It verifies configuration, credential availability, the testnet endpoint,
connectivity, `exchangeInfo`/account permissions, symbol filters and time
synchronization — **without sending any order**. It prints PASS/FAIL per item.

Confirm live trading is disabled:

```bash
python app.py --live-check       # always prints "LIVE TRADING DISABLED"
```

## 4. Verify the engine on real market data first (no orders)

Use **LIVE DATA** mode in the dashboard (Data source → Live). This evaluates the
SignalEngine on real, **closed** candles with **zero orders**. `LIVE MARKET DATA
≠ LIVE TRADING`.

```bash
streamlit run app.py
```

## 5. Enable Testnet execution (fake money)

1. In the dashboard's **Live / Execution** page, set the kill switch to
   `TRADING_TESTNET`.
2. Orders are placed only on Testnet, and only after passing every safety check
   (whitelist, quantity/step/tick, min-notional, balance, risk-per-trade, max
   exposure, max open positions, max daily loss, duplicate protection).
3. The **STOP ALL TRADING** button blocks new orders while preserving positions;
   **Cancel open orders** is a separate action.

The automated testnet loop (`trading.TestnetSession` / `run_testnet_session`) is
**disabled by default** and only runs when explicitly enabled AND the kill switch
is `TRADING_TESTNET`.

## 6. Crash recovery

State (orders, fills, positions, journal, equity) is persisted to SQLite. On
restart the app reconstructs local state and reconciles open orders against the
exchange, so a crash never creates a duplicate order.

## What is NOT enabled

- ❌ Mainnet / real-money orders (no mainnet order client exists).
- ❌ Withdrawals (never used; the trading key must not have the permission).
- ❌ Any automatic switch to live trading.

## Troubleshooting

- **`--testnet-check` says credentials missing** — set `BINANCE_API_KEY` /
  `BINANCE_API_SECRET` in `.env` (testnet keys).
- **Connectivity fails** — your network may block Binance; testnet requires
  outbound access to `testnet.binance.vision`.
- **Order blocked** — read the exact reason in the journal (whitelist, filters,
  balance, risk limit, or duplicate). Fix the input; the safety layer will not
  send an invalid order.
