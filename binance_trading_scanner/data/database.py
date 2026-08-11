"""SQLite persistence layer.

Stores non-secret application data: candle metadata, signals, paper trades,
backtest runs, settings and performance snapshots. API secrets are NEVER stored
here.

The schema is created lazily on first connection. SQLite is the initial choice;
the thin repository API below keeps callers decoupled from the storage engine so
it can be swapped later.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from core.logger import get_logger

logger = get_logger("data.database")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles_meta (
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    first_open  INTEGER,
    last_open   INTEGER,
    count       INTEGER,
    updated_at  INTEGER,
    PRIMARY KEY (symbol, timeframe)
);

CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    signal      TEXT NOT NULL,
    score       REAL NOT NULL,
    score_class TEXT,
    entry       REAL,
    stop        REAL,
    take_profits TEXT,
    risk_reward REAL,
    reasons     TEXT,
    result      TEXT,
    pnl         REAL
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol, timeframe);

CREATE TABLE IF NOT EXISTS paper_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at   TEXT NOT NULL,
    closed_at   TEXT,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,
    qty         REAL NOT NULL,
    entry       REAL NOT NULL,
    exit        REAL,
    fees        REAL DEFAULT 0,
    pnl         REAL,
    status      TEXT NOT NULL DEFAULT 'OPEN'
);

CREATE TABLE IF NOT EXISTS backtests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    params      TEXT,
    metrics     TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT
);

CREATE TABLE IF NOT EXISTS performance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    mode        TEXT,
    equity      REAL,
    drawdown    REAL
);
"""


class Database:
    """Thin SQLite wrapper with a small repository API."""

    def __init__(self, db_path: str = "data/scanner.db") -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- settings (non-secret key/value) -----------------------------------

    def set_setting(self, key: str, value: Any) -> None:
        if _looks_like_secret(key):
            raise ValueError("Refusing to store a credential-like key in the database")
        self._conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        self._conn.commit()

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    # -- signals -----------------------------------------------------------

    def insert_signal(self, signal_row: dict) -> int:
        cols = (
            "created_at", "symbol", "timeframe", "signal", "score", "score_class",
            "entry", "stop", "take_profits", "risk_reward", "reasons", "result", "pnl",
        )
        values = [
            _jsonify(signal_row.get(c)) if c in ("take_profits", "reasons") else signal_row.get(c)
            for c in cols
        ]
        cur = self._conn.execute(
            f"INSERT INTO signals ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            values,
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def recent_signals(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    # -- generic -----------------------------------------------------------

    def execute(self, sql: str, params: Iterable = ()) -> sqlite3.Cursor:
        cur = self._conn.execute(sql, tuple(params))
        self._conn.commit()
        return cur


def _jsonify(value: Optional[Any]) -> Optional[str]:
    return None if value is None else json.dumps(value)


def _looks_like_secret(key: str) -> bool:
    k = key.lower()
    return any(h in k for h in ("secret", "api_key", "apikey", "password", "token"))
