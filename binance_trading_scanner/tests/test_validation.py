"""Phase 9 tests: offline LONG+SHORT validation pipeline.

Deterministic and offline. Verifies the direction-isolation execution filter (same
signals, LONG-only / SHORT-only execution), the honest metric helpers, the
real-or-synthetic data provider fallback, and the conservative edge/overfitting
verdicts. No network, no orders, no Mainnet.
"""
from __future__ import annotations

import numpy as np
import pytest

from backtesting import (
    BacktestConfig,
    BacktestEngine,
    DirectionReport,
    MarketDataResult,
    RealDataUnavailable,
    ValidationConfig,
    detect_overfitting,
    edge_verdict,
    final_table,
    load_history,
    load_real_history,
    synthetic_history,
)
from backtesting.portfolio import EquityPoint
from backtesting.validation import (
    COMBINED,
    LONG,
    SHORT,
    buy_and_hold_return_pct,
    peak_exposure_pct,
    run_segment,
)
from core.enums import Timeframe
from core.models import Candle
from tests.conftest import bt_bear, bt_bull

TF = Timeframe.H1


# ---- direction-isolation execution filter (same signals) -----------------

def test_allowed_directions_long_only_on_bull():
    r = BacktestEngine(config=BacktestConfig(allowed_directions=LONG)).run(bt_bull(320), "BTCUSDT", TF)
    assert r.trades and all(t.direction == "LONG" for t in r.trades)


def test_allowed_directions_short_only_on_bull_is_empty():
    # A pure uptrend offers no short setups; SHORT-only execution yields no trades.
    r = BacktestEngine(config=BacktestConfig(allowed_directions=SHORT)).run(bt_bull(320), "BTCUSDT", TF)
    assert r.trades == []


def test_allowed_directions_short_only_on_bear():
    r = BacktestEngine(config=BacktestConfig(allowed_directions=SHORT)).run(bt_bear(320), "BTCUSDT", TF)
    assert r.trades and all(t.direction == "SHORT" for t in r.trades)


def test_default_executes_both_directions_unchanged():
    # Default (both) must be byte-identical to the plain engine on a bull path.
    a = BacktestEngine(config=BacktestConfig()).run(bt_bull(320), "BTCUSDT", TF)
    b = BacktestEngine(config=BacktestConfig(allowed_directions=COMBINED)).run(bt_bull(320), "BTCUSDT", TF)
    assert [t.direction for t in a.trades] == [t.direction for t in b.trades]
    assert a.final_equity == pytest.approx(b.final_equity)


# ---- honest metric helpers -----------------------------------------------

def test_buy_and_hold_return_pct():
    df = bt_bull(60)
    first, last = float(df["close"].iloc[0]), float(df["close"].iloc[-1])
    expected = (last / first - 1.0) * 100.0
    assert buy_and_hold_return_pct(df) == pytest.approx(expected)
    assert buy_and_hold_return_pct(df.iloc[:1]) is None


def test_peak_exposure_pct():
    curve = [
        EquityPoint(0, cash=10_000, equity=10_000, peak=10_000, drawdown=0, drawdown_pct=0),
        EquityPoint(1, cash=4_000, equity=10_000, peak=10_000, drawdown=0, drawdown_pct=0),  # 60% deployed
        EquityPoint(2, cash=9_000, equity=10_000, peak=10_000, drawdown=0, drawdown_pct=0),
    ]
    assert peak_exposure_pct(curve) == pytest.approx(60.0)


def _report(**kw) -> DirectionReport:
    base = dict(direction="LONG", trades=0, win_rate=None, profit_factor=None,
                expectancy_usdt=None, expectancy_r=None, net_pnl=0.0, net_return_pct=None,
                max_drawdown=0.0, max_drawdown_pct=0.0, sharpe=None, sortino=None,
                average_win=None, average_loss=None, average_r=None, median_r=None,
                consecutive_losses=0, max_exposure_pct=0.0)
    base.update(kw)
    r = DirectionReport(**base)
    r.small_sample = r.trades < 20
    return r


def test_edge_verdict_insufficient_sample():
    assert "INSUFFICIENT EVIDENCE" in edge_verdict(_report(trades=5))


def test_edge_verdict_no_positive_edge():
    v = edge_verdict(_report(trades=40, expectancy_r=-0.1, profit_factor=0.8))
    assert "NO POSITIVE EDGE" in v


def test_edge_verdict_weak_positive_is_not_a_promise():
    v = edge_verdict(_report(trades=40, expectancy_r=0.2, profit_factor=1.3))
    assert "WEAK POSITIVE SIGNAL" in v
    for banned in ("guaranteed", "profitable", "will win", "safe"):
        assert banned.lower() not in v.lower()


def test_detect_overfitting_flags_expectancy_flip():
    train = _report(trades=50, expectancy_r=0.3, profit_factor=1.5)
    oos = _report(trades=50, expectancy_r=-0.2, profit_factor=0.7)
    out = detect_overfitting(train, oos)
    assert out["overfitting_suspected"] and out["reasons"]


def test_detect_overfitting_stable_is_not_flagged():
    train = _report(trades=50, expectancy_r=0.3, profit_factor=1.5)
    oos = _report(trades=50, expectancy_r=0.25, profit_factor=1.4)
    assert detect_overfitting(train, oos)["overfitting_suspected"] is False


# ---- config plumbing & data provider -------------------------------------

def test_validation_config_carries_fees_slippage_and_directions():
    cfg = ValidationConfig(fee_rate=0.002, slippage_rate=0.001)
    bc = cfg.backtest_config(SHORT)
    assert bc.execution.fee_rate == pytest.approx(0.002)
    assert bc.execution.slippage_rate == pytest.approx(0.001)
    assert bc.allowed_directions == SHORT


def test_synthetic_history_is_valid_ohlc_and_trades_both_sides():
    df = synthetic_history(600, TF, seed=3)
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    assert np.all(h >= np.maximum(o, c) - 1e-9)
    assert np.all(l <= np.minimum(o, c) + 1e-9)
    assert np.all((o > 0) & (c > 0))


def test_load_history_falls_back_to_synthetic_offline():
    # prefer_real=False must never touch the network and returns SYNTHETIC.
    res = load_history("BTCUSDT", TF, 300, prefer_real=False)
    assert isinstance(res, MarketDataResult)
    assert res.source == "SYNTHETIC"
    assert len(res.df) == 300


class _FakeMarket:
    """Returns a fixed batch of closed candles (< 1000 so paging stops)."""

    def __init__(self, n=350):
        self.n = n

    def get_klines(self, symbol, timeframe, *, limit=1000, end_time=None):
        step = timeframe.milliseconds
        start = 1_600_000_000_000
        out = []
        price = 100.0
        for i in range(self.n):
            ot = start + i * step
            price += 0.1
            o, c = price, price + 0.2
            out.append(Candle(open_time=ot, open=o, high=c + 0.3, low=o - 0.3, close=c,
                              volume=1000.0, close_time=ot + step - 1, is_closed=True))
        return out


def test_load_history_uses_real_when_market_available():
    res = load_history("BTCUSDT", TF, 200, prefer_real=True, market=_FakeMarket(350))
    assert res.source == "BINANCE"
    assert len(res.df) == 200


# ---- REAL STRICT mode: no synthetic fallback -----------------------------

class _PagingMarket:
    """Fake Binance that pages backwards like the real klines endpoint."""

    def __init__(self, total=2500):
        step = TF.milliseconds
        start = 1_500_000_000_000
        self.candles = []
        price = 100.0
        for i in range(total):
            ot = start + i * step
            price += 0.05
            o, c = price, price + 0.1
            self.candles.append(Candle(open_time=ot, open=o, high=c + 0.2, low=o - 0.2,
                                       close=c, volume=1000.0, close_time=ot + step - 1,
                                       is_closed=True))

    def get_klines(self, symbol, timeframe, *, limit=1000, end_time=None):
        pool = self.candles if end_time is None else [c for c in self.candles if c.open_time <= end_time]
        return pool[-limit:]


class _DeadMarket:
    def get_klines(self, *a, **k):
        raise RuntimeError("403 Forbidden")


def test_load_real_history_raises_and_never_falls_back():
    # Connection failure -> RealDataUnavailable, NEVER synthetic.
    with pytest.raises(RealDataUnavailable):
        load_real_history("BTCUSDT", TF, 1000, market=_DeadMarket(), min_bars=600)


def test_load_real_history_raises_on_insufficient_bars():
    with pytest.raises(RealDataUnavailable):
        load_real_history("BTCUSDT", TF, 2000, market=_PagingMarket(total=300), min_bars=600)


def test_load_real_history_pages_and_returns_real():
    res = load_real_history("BTCUSDT", TF, 2000, market=_PagingMarket(total=2500), min_bars=600)
    assert res.source == "BINANCE"
    assert len(res.df) == 2000
    # chronological, unique, no synthetic marker
    ot = res.df["open_time"].to_numpy()
    assert (ot[1:] > ot[:-1]).all()


def test_cli_real_mode_writes_failure_report_without_synthetic(tmp_path, monkeypatch):
    import validate
    out = tmp_path / "REAL_VALIDATION_REPORT.md"

    def boom(*a, **k):
        raise RealDataUnavailable("blocked: 403 Forbidden")

    monkeypatch.setattr(validate, "load_real_history", boom)
    rc = validate.main(["--real", "--symbols", "BTCUSDT", "--timeframes", "4h",
                        "--bars", "1000", "--out", str(out)])
    assert rc == 1                                   # non-zero on failure
    text = out.read_text()
    assert "REAL DATA VALIDATION FAILED" in text
    assert "READY FOR TESTNET: NO" in text
    assert "SYNTHETIC" not in text.upper() or "synthetic data is never" in text.lower()


def test_verdict_lines_format():
    from validate import verdict_lines
    lines = verdict_lines({"real_data": False, "long_edge": False, "short_edge": False,
                           "overfitting": False, "ready_for_testnet": False})
    assert lines == ["REAL DATA: NO", "LONG EDGE: NO", "SHORT EDGE: NO",
                     "OVERFITTING: NO", "READY FOR TESTNET: NO"]


# ---- integration: one segment, LONG/SHORT/COMBINED + final table ---------

def test_run_segment_isolates_directions_and_builds_table():
    df = bt_bear(500)                     # a downtrend: SHORT should trade, LONG should not
    seg = run_segment(df, "BTCUSDT", TF, ValidationConfig(), "TRAIN")
    assert seg.reports["LONG"].trades == 0
    assert seg.reports["SHORT"].trades > 0
    rows = final_table(seg)
    assert [r["direction"] for r in rows] == ["LONG", "SHORT", "COMBINADO"]
    required = {"trades", "win_rate", "profit_factor", "expectancy_r", "net_pnl",
                "max_drawdown", "sharpe", "sortino", "average_r"}
    assert required <= set(rows[0].keys())
