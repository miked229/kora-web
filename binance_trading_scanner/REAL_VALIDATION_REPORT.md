# REAL DATA VALIDATION FAILED

> ⚠️ **No Mainnet, no real money, no orders.** REAL STRICT mode does NOT fall back to synthetic data, so no results are presented here — synthetic data is never shown as a real-data validation.

Generated: 2026-08-19 02:05 UTC

## Result

```
REAL DATA VALIDATION FAILED
```

- Symbols requested: BTCUSDT, ETHUSDT
- Timeframes requested: 4h
- Reason: BTCUSDT 4h: could not reach Binance (BinanceConnectionError: Network error after 4 attempts: 403 Forbidden)

## What this means

Real Binance historical data could not be downloaded from this environment (the public API host is not reachable here — egress policy returns 403). This is expected inside the sandbox; **run `python validate.py --real` on a machine with outbound access to Binance** (e.g. your Mac) to perform the real-data validation.

```
REAL DATA: NO
LONG EDGE: NO
SHORT EDGE: NO
OVERFITTING: NO
READY FOR TESTNET: NO
```

_No synthetic data was used. No Mainnet. No real money._
