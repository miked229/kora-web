"""Phase 6 tests: paper engine — parity, persistence, restart, safety.

Deterministic and offline. The headline test is BACKTEST PARITY: the paper
trader and the backtester, fed the same candles, must produce identical trades.
"""
from __future__ import annotations

import pytest

from backtesting import BacktestConfig, BacktestEngine, RiskLimits
from core.enums import ExitReason, Timeframe
from paper_trading import PaperEngine, RESET_TOKEN
from signals import SignalEngine
from tests.conftest import bt_bull, bt_bull_then_crash, bt_flat_range

TF = Timeframe.H1


def _paper(tmp_path, cfg=None, cap=10_000, name="p.db"):
    return PaperEngine(SignalEngine(), cfg or BacktestConfig(capital=cap),
                       str(tmp_path / name), "BTCUSDT", TF, initial_balance=cap)


def _paper_trades(pe):
    # store returns newest-first; reverse to chronological
    return pe.store.trades(2000)[::-1]


# =========================================================================
# BACKTEST PARITY (spec 22) — the same flow must give the same result
# =========================================================================

def _assert_parity(bt_trades, paper_trades):
    assert len(bt_trades) == len(paper_trades)
    for a, b in zip(bt_trades, paper_trades):
        assert a.entry_price == pytest.approx(b["entry_price"])
        assert a.stop_price == pytest.approx(b["stop_price"])
        assert (a.tp1_price, a.tp2_price) == (b["tp1_price"], b["tp2_price"])
        assert a.quantity == pytest.approx(b["quantity"])
        assert a.gross_pnl == pytest.approx(b["gross_pnl"])
        assert a.fees == pytest.approx(b["fees"])
        assert a.slippage == pytest.approx(b["slippage"])
        assert a.net_pnl == pytest.approx(b["net_pnl"])
        assert a.r_multiple == pytest.approx(b["r_multiple"])
        assert a.exit_reason.value == b["exit_reason"]


@pytest.mark.parametrize("scenario", ["bull", "crash"])
def test_backtest_parity(tmp_path, scenario):
    df = bt_bull(360) if scenario == "bull" else bt_bull_then_crash(250, 40)
    cfg = BacktestConfig(capital=10_000)
    bt = BacktestEngine(SignalEngine(), cfg).run(df, "BTCUSDT", TF)
    pe = _paper(tmp_path, cfg)
    pe.process_new_candles(df)
    pe.finalize(float(df["close"].iloc[-1]), int(df["close_time"].iloc[-1]), len(df) - 1)
    _assert_parity(bt.trades, _paper_trades(pe))
    pe.close()


# =========================================================================
# Trade lifecycle
# =========================================================================

def test_tp1_then_tp2_recorded(tmp_path):
    pe = _paper(tmp_path)
    pe.process_new_candles(bt_bull(320))
    trades = _paper_trades(pe)
    tp2 = [t for t in trades if t["exit_reason"] == "TP2" and t["tp1_hit"]]
    assert tp2
    pe.close()


def test_stop_loss_recorded(tmp_path):
    pe = _paper(tmp_path)
    pe.process_new_candles(bt_bull_then_crash(250, 30))
    trades = _paper_trades(pe)
    stops = [t for t in trades if t["exit_reason"] == "STOP_LOSS"]
    assert stops and all(t["net_pnl"] < 0 for t in stops)
    pe.close()


def test_equity_and_journal_recorded(tmp_path):
    df = bt_bull(320)
    pe = _paper(tmp_path)
    pe.process_new_candles(df)
    assert len(pe.store.equity()) == len(df)
    journal = pe.store.journal(5000)
    kinds = {e["event_type"] for e in journal}
    assert "SIGNAL" in kinds and "POSITION_OPEN" in kinds and "EXIT" in kinds
    # ALL signals are journalled (LONG / NEUTRAL / NO_TRADE), not only trades
    signals = [e for e in journal if e["event_type"] == "SIGNAL"]
    assert len(signals) == len(df)
    assert {e["signal"] for e in signals} & {"NO_TRADE", "NEUTRAL"}
    pe.close()


def test_no_trades_still_journals_signals(tmp_path):
    df = bt_flat_range(300)
    pe = _paper(tmp_path)
    pe.process_new_candles(df)
    assert _paper_trades(pe) == []
    signals = [e for e in pe.store.journal(5000) if e["event_type"] == "SIGNAL"]
    assert len(signals) == len(df)
    pe.close()


# =========================================================================
# Only-closed-candles / duplicate protection (spec 17, 18)
# =========================================================================

def test_reprocessing_is_idempotent(tmp_path):
    df = bt_bull(320)
    pe = _paper(tmp_path)
    first = pe.process_new_candles(df)
    trades1 = len(_paper_trades(pe))
    orders1 = len(pe.store.orders(5000))
    second = pe.process_new_candles(df)          # same candles again
    assert first["processed"] == len(df)
    assert second["processed"] == 0              # nothing new -> no duplicates
    assert len(_paper_trades(pe)) == trades1
    assert len(pe.store.orders(5000)) == orders1
    pe.close()


def test_only_processes_new_closed_candles(tmp_path):
    df = bt_bull(320)
    pe = _paper(tmp_path)
    pe.process_new_candles(df.iloc[:200])
    assert pe.cursor == int(df["close_time"].iloc[199])
    signals = [e for e in pe.store.journal(5000) if e["event_type"] == "SIGNAL"]
    # never evaluated a candle beyond the cursor (no future candle usage)
    assert max(e["timestamp"] for e in signals) == pe.cursor
    pe.process_new_candles(df)                   # feed full history; only new ones processed
    assert pe.cursor == int(df["close_time"].iloc[-1])
    pe.close()


# =========================================================================
# Persistence & restart recovery (spec 12, 20)
# =========================================================================

def test_restart_recovery_matches_uninterrupted(tmp_path):
    df = bt_bull(360)
    cfg = BacktestConfig(capital=10_000)

    # Split across a restart
    p1 = _paper(tmp_path, cfg, name="split.db")
    p1.process_new_candles(df.iloc[:180])
    p1.close()                                    # shutdown
    p2 = PaperEngine(SignalEngine(), cfg, str(tmp_path / "split.db"), "BTCUSDT", TF)
    assert p2.cursor == int(df["close_time"].iloc[179])   # state restored
    p2.process_new_candles(df)
    eq_split = p2.account_view(float(df["close"].iloc[-1])).equity
    tr_split = len(_paper_trades(p2))
    p2.close()

    # Uninterrupted
    p3 = _paper(tmp_path, cfg, name="single.db")
    p3.process_new_candles(df)
    eq_single = p3.account_view(float(df["close"].iloc[-1])).equity
    tr_single = len(_paper_trades(p3))
    p3.close()

    assert eq_split == pytest.approx(eq_single)
    assert tr_split == tr_single


def test_open_position_survives_restart(tmp_path):
    # Feed candles up to a point where a position is very likely open, then restart.
    df = bt_bull(360)
    cfg = BacktestConfig(capital=10_000)
    for cut in range(212, 240):
        p = _paper(tmp_path, cfg, name=f"o{cut}.db")
        p.process_new_candles(df.iloc[:cut])
        had_pos = p.sim.position is not None
        p.close()
        if had_pos:
            p2 = PaperEngine(SignalEngine(), cfg, str(tmp_path / f"o{cut}.db"), "BTCUSDT", TF)
            assert p2.sim.position is not None
            assert p2.sim.position.remaining_qty > 0
            p2.close()
            return
    pytest.skip("no open position window found in this synthetic path")


# =========================================================================
# Risk limits & error recovery (spec 10, 19)
# =========================================================================

def test_risk_blocked_recorded(tmp_path):
    cfg = BacktestConfig(limits=RiskLimits(max_daily_loss=0.0002))
    pe = _paper(tmp_path, cfg)
    pe.process_new_candles(bt_bull_then_crash(250, 40))
    assert pe.portfolio.risk_blocked > 0
    blocked = [e for e in pe.store.journal(5000) if e["event_type"] == "RISK_BLOCKED"]
    assert blocked
    pe.close()


def test_error_recovery_keeps_account_consistent(tmp_path, monkeypatch):
    df = bt_bull(360)
    pe = _paper(tmp_path)
    pe.process_new_candles(df.iloc[:150])
    equity_before = pe.account_view(float(df["close"].iloc[149])).equity
    cursor_before = pe.cursor

    def boom(*a, **k):
        raise RuntimeError("simulated market-data failure")

    monkeypatch.setattr(pe.signal_engine, "evaluate_at", boom)
    result = pe.process_new_candles(df)          # should fail gracefully
    assert result["error"] is not None
    # state reverted to the last good snapshot — no corruption
    assert pe.cursor == cursor_before
    assert pe.account_view(float(df["close"].iloc[149])).equity == pytest.approx(equity_before)

    monkeypatch.undo()
    recovered = pe.process_new_candles(df)        # resumes cleanly
    assert recovered["processed"] > 0
    pe.close()


def test_reset_is_safe(tmp_path):
    pe = _paper(tmp_path)
    pe.process_new_candles(bt_bull(320))
    with pytest.raises(ValueError):
        pe.reset("nope")
    pe.reset(RESET_TOKEN)
    assert _paper_trades(pe) == []
    assert pe.cursor == -1
    pe.close()
