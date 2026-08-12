"""Persistent store of submitted orders — idempotency and crash recovery.

Keyed by the logical ``client_order_id`` so the same signal can never create two
orders (spec 13), and so that on restart the local state can be rebuilt and
reconciled against the exchange (spec 15). Stores NO secrets.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_orders (
    client_order_id TEXT PRIMARY KEY,
    environment     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    quantity        REAL,
    status          TEXT,
    executed_qty    REAL DEFAULT 0,
    avg_price       REAL DEFAULT 0,
    fees            REAL DEFAULT 0,
    signal_timestamp INTEGER,
    created_at      INTEGER,
    updated_at      INTEGER,
    raw             TEXT
);
CREATE TABLE IF NOT EXISTS trading_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER, kind TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS kill_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT, emergency_stopped INTEGER, stop_reason TEXT, stopped_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_orders_symbol_status ON live_orders(symbol, status);
CREATE INDEX IF NOT EXISTS idx_orders_signal ON live_orders(signal_timestamp);
CREATE INDEX IF NOT EXISTS idx_events_ts ON trading_events(ts);
"""

# Terminal (fully-resolved) exchange statuses.
TERMINAL = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}


class LiveOrderStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # idempotency -----------------------------------------------------------
    def exists(self, client_order_id: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM live_orders WHERE client_order_id=?", (client_order_id,)
        ).fetchone() is not None

    def known_client_ids(self) -> List[str]:
        return [r["client_order_id"] for r in
                self.conn.execute("SELECT client_order_id FROM live_orders").fetchall()]

    def record_submitted(self, client_order_id: str, environment: str, symbol: str,
                         side: str, quantity: float, signal_timestamp: int,
                         status: str = "NEW", raw: Optional[dict] = None) -> None:
        now = int(time.time() * 1000)
        self.conn.execute(
            "INSERT OR IGNORE INTO live_orders (client_order_id, environment, symbol, side, "
            "quantity, status, signal_timestamp, created_at, updated_at, raw) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (client_order_id, environment, symbol, side, quantity, status,
             signal_timestamp, now, now, json.dumps(raw) if raw else None))
        self.conn.commit()

    def update_from_exchange(self, client_order_id: str, status: str, executed_qty: float,
                             avg_price: float, fees: float, raw: Optional[dict] = None) -> None:
        self.conn.execute(
            "UPDATE live_orders SET status=?, executed_qty=?, avg_price=?, fees=?, updated_at=?, raw=? "
            "WHERE client_order_id=?",
            (status, executed_qty, avg_price, fees, int(time.time() * 1000),
             json.dumps(raw) if raw else None, client_order_id))
        self.conn.commit()

    def get(self, client_order_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM live_orders WHERE client_order_id=?", (client_order_id,)).fetchone()

    def all_orders(self) -> List[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM live_orders ORDER BY created_at DESC").fetchall()]

    def non_terminal_orders(self) -> List[dict]:
        rows = self.conn.execute("SELECT * FROM live_orders").fetchall()
        return [dict(r) for r in rows if (r["status"] or "").upper() not in TERMINAL]

    # events ----------------------------------------------------------------
    def log_event(self, kind: str, detail: str) -> None:
        self.conn.execute("INSERT INTO trading_events (ts, kind, detail) VALUES (?,?,?)",
                          (int(time.time() * 1000), kind, detail))
        self.conn.commit()

    def events(self, limit: int = 200) -> List[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM trading_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    # kill-switch persistence (survives restart) ---------------------------
    def save_kill_state(self, state: str, emergency_stopped: bool,
                        stop_reason: Optional[str], stopped_at: Optional[int]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO kill_state (id, state, emergency_stopped, stop_reason, stopped_at) "
            "VALUES (1, ?, ?, ?, ?)",
            (state, 1 if emergency_stopped else 0, stop_reason, stopped_at))
        self.conn.commit()

    def load_kill_state(self) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM kill_state WHERE id=1").fetchone()
        return dict(row) if row else None
