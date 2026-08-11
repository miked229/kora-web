"""Phase 1 core tests: config, models, scoring buckets, logging, database."""
from __future__ import annotations

import logging

import pytest

from config import Settings, load_settings
from core.enums import ScoreClass, SignalType, Timeframe, TradingMode
from core.logger import configure_logging, get_logger
from core.models import Signal
from data.database import Database


def test_score_class_buckets():
    assert ScoreClass.from_score(0) is ScoreClass.NO_TRADE
    assert ScoreClass.from_score(39) is ScoreClass.NO_TRADE
    assert ScoreClass.from_score(40) is ScoreClass.WEAK
    assert ScoreClass.from_score(60) is ScoreClass.MODERATE
    assert ScoreClass.from_score(75) is ScoreClass.STRONG
    assert ScoreClass.from_score(85) is ScoreClass.VERY_STRONG
    assert ScoreClass.from_score(100) is ScoreClass.VERY_STRONG


def test_signal_score_class_synced():
    s = Signal(symbol="BTCUSDT", timeframe=Timeframe.M15, signal=SignalType.LONG, score=82)
    assert s.score_class is ScoreClass.STRONG


def test_signal_score_out_of_range_rejected():
    with pytest.raises(ValueError):
        Signal(symbol="BTCUSDT", timeframe=Timeframe.M15, signal=SignalType.LONG, score=150)


def test_settings_risk_bounds():
    with pytest.raises(ValueError):
        Settings(risk_per_trade=0.0)
    with pytest.raises(ValueError):
        Settings(risk_per_trade=0.9)
    s = Settings(risk_per_trade=0.02)
    assert s.risk_per_trade == 0.02


def test_settings_symbols_normalised():
    s = Settings(symbols=["btcusdt", " ethusdt ", ""])
    assert s.symbols == ["BTCUSDT", "ETHUSDT"]


def test_load_settings_defaults(monkeypatch):
    for var in ("BINANCE_ENV", "APP_MODE", "BINANCE_REST_BASE"):
        monkeypatch.delenv(var, raising=False)
    s = load_settings()
    assert s.mode is TradingMode.PAPER
    assert s.rest_base.startswith("https://")
    assert "BTCUSDT" in s.symbols


def test_credentials_never_on_settings_object():
    # Secrets must not be attributes that could be logged/rendered.
    s = Settings()
    assert not hasattr(s, "api_key")
    assert not hasattr(s, "api_secret")


def test_logger_redacts_credential_like_messages(caplog):
    configure_logging("DEBUG")
    log = get_logger("test.redact")
    with caplog.at_level(logging.INFO):
        log.info("api_secret=SUPERSECRETVALUE")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "SUPERSECRETVALUE" not in joined
    assert "REDACTED" in joined


def test_database_roundtrip_and_secret_guard():
    db = Database(":memory:")
    try:
        db.set_setting("risk_per_trade", 0.02)
        assert db.get_setting("risk_per_trade") == 0.02

        sid = db.insert_signal({
            "created_at": "2026-08-11T00:00:00Z", "symbol": "BTCUSDT",
            "timeframe": "15m", "signal": "LONG", "score": 82,
            "score_class": "STRONG", "entry": 100.0, "stop": 98.0,
            "take_profits": [102.0, 104.0], "risk_reward": 2.0,
            "reasons": ["trend up"], "result": None, "pnl": None,
        })
        assert sid == 1
        assert db.recent_signals()[0]["symbol"] == "BTCUSDT"

        # The DB must refuse credential-like keys.
        with pytest.raises(ValueError):
            db.set_setting("BINANCE_API_SECRET", "x")
    finally:
        db.close()
