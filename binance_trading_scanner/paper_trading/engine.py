"""Paper trading engine — a fully-internal simulated account.

Drives the SAME ``backtesting.Simulator`` the backtester uses (so the two can
never diverge), but incrementally: it processes newly-closed candles one at a
time, persists all state to SQLite, and can be rebuilt after a restart.

Guarantees:
  * CERO real orders / API keys / live trading — everything is internal.
  * Signals come only from the SignalEngine (``evaluate_at`` on closed candles).
  * Entry timing, fees, slippage, stops, TPs and risk limits are the backtester's
    — reused, never re-implemented.
  * Only CLOSED candles are processed, each exactly once (cursor + logical id).
  * State survives restarts; a failure never corrupts the account (on error the
    in-memory state is reloaded from the last persisted snapshot).

Real-time note: when fed live closed candles, "signal at candle close -> entry
at next candle open" means the fill happens at the open of the next closed
candle. This is the documented, conservative market-like assumption.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Optional

import pandas as pd

from backtesting.engine import BacktestConfig
from backtesting.portfolio import Portfolio
from backtesting.simulator import Simulator, StepResult
from backtesting.trade import Leg, Position
from core.enums import ExitReason, Timeframe
from core.logger import get_logger
from core.models import Signal

from .account import AccountView, build_account_view
from .journal import JournalEventType
from .orders import Order, OrderSide, OrderStatus, OrderType
from .positions import PositionView, build_position_view

logger = get_logger("paper_trading.engine")

RESET_TOKEN = "RESET"


# --------------------------------------------------------------------------
# (De)serialisation of the open position
# --------------------------------------------------------------------------

def _pos_to_json(pos: Optional[Position]) -> Optional[str]:
    if pos is None:
        return None
    d = {
        "symbol": pos.symbol, "timeframe": pos.timeframe, "signal_time": pos.signal_time,
        "entry_time": pos.entry_time, "entry_raw": pos.entry_raw, "entry_eff": pos.entry_eff,
        "stop": pos.stop, "tp1": pos.tp1, "tp2": pos.tp2,
        "original_qty": pos.original_qty, "remaining_qty": pos.remaining_qty,
        "tp1_alloc": pos.tp1_alloc, "tp2_alloc": pos.tp2_alloc,
        "direction": pos.direction,
        "entry_fee": pos.entry_fee, "entry_slippage": pos.entry_slippage,
        "fees_paid": pos.fees_paid, "slippage_paid": pos.slippage_paid,
        "realized_pnl": pos.realized_pnl, "tp1_done": pos.tp1_done,
        "mfe_r": pos.mfe_r, "mae_r": pos.mae_r,
        "entry_bar_index": getattr(pos, "entry_bar_index", 0),
        "legs": [
            {"timestamp": leg.timestamp, "qty": leg.qty, "price": leg.price,
             "reason": leg.reason.value, "gross_pnl": leg.gross_pnl, "fees": leg.fees,
             "slippage": leg.slippage, "net_pnl": leg.net_pnl}
            for leg in pos.legs
        ],
    }
    return json.dumps(d)


def _pos_from_json(text: Optional[str]) -> Optional[Position]:
    if not text:
        return None
    d = json.loads(text)
    pos = Position(
        symbol=d["symbol"], timeframe=d["timeframe"], signal_time=d["signal_time"],
        entry_time=d["entry_time"], entry_raw=d["entry_raw"], entry_eff=d["entry_eff"],
        stop=d["stop"], tp1=d["tp1"], tp2=d["tp2"],
        original_qty=d["original_qty"], remaining_qty=d["remaining_qty"],
        tp1_alloc=d["tp1_alloc"], tp2_alloc=d["tp2_alloc"],
        direction=d.get("direction", "LONG"),
        entry_fee=d["entry_fee"], entry_slippage=d["entry_slippage"],
        fees_paid=d["fees_paid"], slippage_paid=d["slippage_paid"],
        realized_pnl=d["realized_pnl"], tp1_done=d["tp1_done"],
        mfe_r=d["mfe_r"], mae_r=d["mae_r"],
    )
    pos.legs = [
        Leg(timestamp=l["timestamp"], qty=l["qty"], price=l["price"],
            reason=ExitReason(l["reason"]), gross_pnl=l["gross_pnl"], fees=l["fees"],
            slippage=l["slippage"], net_pnl=l["net_pnl"])
        for l in d.get("legs", [])
    ]
    pos.entry_bar_index = d.get("entry_bar_index", 0)  # type: ignore[attr-defined]
    return pos


# --------------------------------------------------------------------------
# SQLite persistence
# --------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    symbol TEXT, timeframe TEXT, initial_balance REAL, cash REAL,
    realized_pnl REAL, fees REAL, slippage REAL, peak_equity REAL,
    max_drawdown REAL, max_drawdown_pct REAL, risk_blocked INTEGER,
    trade_id INTEGER, cursor INTEGER, daily_realized TEXT,
    position TEXT, pending TEXT, pending_order_signal_time INTEGER, updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS paper_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, signal_time INTEGER, symbol TEXT,
    side TEXT, type TEXT, quantity REAL, requested_price REAL, filled_price REAL,
    status TEXT, created_at INTEGER, filled_at INTEGER, fees REAL, slippage REAL, reason TEXT
);
CREATE TABLE IF NOT EXISTS paper_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, symbol TEXT, qty REAL,
    price REAL, fees REAL, slippage REAL, timestamp INTEGER, reason TEXT
);
CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY, data TEXT
);
CREATE TABLE IF NOT EXISTS paper_equity (
    timestamp INTEGER, cash REAL, equity REAL, drawdown REAL, drawdown_pct REAL
);
CREATE TABLE IF NOT EXISTS paper_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER, symbol TEXT, timeframe TEXT,
    event_type TEXT, signal TEXT, setup TEXT, raw_score REAL, final_score REAL,
    blocked_by TEXT, detail TEXT
);
"""


class PaperStore:
    """Thin SQLite store for the paper account. Stores no secrets."""

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

    # account ---------------------------------------------------------------
    def load_account(self) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()

    def save_account(self, s: dict) -> None:
        cols = ("symbol", "timeframe", "initial_balance", "cash", "realized_pnl", "fees",
                "slippage", "peak_equity", "max_drawdown", "max_drawdown_pct", "risk_blocked",
                "trade_id", "cursor", "daily_realized", "position", "pending",
                "pending_order_signal_time", "updated_at")
        placeholders = ", ".join(["?"] * (len(cols) + 1))
        self.conn.execute(
            f"INSERT OR REPLACE INTO paper_account (id, {', '.join(cols)}) VALUES ({placeholders})",
            [1] + [s.get(c) for c in cols],
        )
        self.conn.commit()

    # orders / fills --------------------------------------------------------
    def insert_order(self, o: Order) -> int:
        r = o.to_row()
        cur = self.conn.execute(
            "INSERT INTO paper_orders (signal_time, symbol, side, type, quantity, "
            "requested_price, filled_price, status, created_at, filled_at, fees, slippage, reason) "
            "VALUES (:signal_time,:symbol,:side,:type,:quantity,:requested_price,:filled_price,"
            ":status,:created_at,:filled_at,:fees,:slippage,:reason)", r)
        self.conn.commit()
        return int(cur.lastrowid)

    def update_order(self, order_id: int, **fields) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE paper_orders SET {sets} WHERE id=?",
                          list(fields.values()) + [order_id])
        self.conn.commit()

    def find_pending_buy(self, signal_time: int) -> Optional[int]:
        row = self.conn.execute(
            "SELECT id FROM paper_orders WHERE signal_time=? AND side='BUY' AND status='PENDING' "
            "ORDER BY id DESC LIMIT 1", (signal_time,)).fetchone()
        return int(row["id"]) if row else None

    def insert_fill(self, order_id: Optional[int], symbol: str, qty: float, price: float,
                    fees: float, slippage: float, timestamp: int, reason: str) -> None:
        self.conn.execute(
            "INSERT INTO paper_fills (order_id, symbol, qty, price, fees, slippage, timestamp, reason) "
            "VALUES (?,?,?,?,?,?,?,?)", (order_id, symbol, qty, price, fees, slippage, timestamp, reason))
        self.conn.commit()

    # trades / equity / journal --------------------------------------------
    def insert_trade(self, trade_dict: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO paper_trades (id, data) VALUES (?, ?)",
                          (trade_dict["id"], json.dumps(trade_dict)))
        self.conn.commit()

    def insert_equity(self, timestamp: int, cash: float, equity: float,
                      drawdown: float, drawdown_pct: float) -> None:
        self.conn.execute("INSERT INTO paper_equity VALUES (?,?,?,?,?)",
                          (timestamp, cash, equity, drawdown, drawdown_pct))
        self.conn.commit()

    def insert_journal(self, timestamp: int, symbol: str, timeframe: str, event_type: str,
                       signal=None, setup=None, raw_score=None, final_score=None,
                       blocked_by=None, detail=None) -> None:
        self.conn.execute(
            "INSERT INTO paper_journal (timestamp, symbol, timeframe, event_type, signal, setup, "
            "raw_score, final_score, blocked_by, detail) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (timestamp, symbol, timeframe, event_type, signal, setup, raw_score, final_score,
             json.dumps(blocked_by) if blocked_by is not None else None, detail))
        self.conn.commit()

    # reads for display -----------------------------------------------------
    def orders(self, limit=200) -> List[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM paper_orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def trades(self, limit=200) -> List[dict]:
        rows = self.conn.execute("SELECT data FROM paper_trades ORDER BY id DESC LIMIT ?",
                                 (limit,)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def equity(self, limit=5000) -> List[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM paper_equity ORDER BY timestamp ASC LIMIT ?", (limit,)).fetchall()]

    def journal(self, limit=300) -> List[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM paper_journal ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def reset(self) -> None:
        for t in ("paper_account", "paper_orders", "paper_fills", "paper_trades",
                  "paper_equity", "paper_journal"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()


# --------------------------------------------------------------------------
# Paper engine
# --------------------------------------------------------------------------

class PaperEngine:
    """Incremental, persistent paper trader for one symbol/timeframe."""

    def __init__(self, signal_engine, config: BacktestConfig, db_path: str,
                 symbol: str, timeframe: Timeframe, initial_balance: Optional[float] = None) -> None:
        self.signal_engine = signal_engine
        self.config = config
        self.symbol = symbol.upper()
        self.timeframe = timeframe
        self.store = PaperStore(db_path)
        self._pending_order_signal_time: Optional[int] = None
        self.cursor = -1
        row = self.store.load_account()
        if row is None:
            self.initial_balance = float(initial_balance if initial_balance is not None else config.capital)
            self.portfolio = Portfolio(self.initial_balance, config.limits)
            self.sim = Simulator(config, self.portfolio, self.symbol, timeframe.value)
            self._persist_state()
        else:
            self._reconstruct(row)

    # -- reconstruction (restart recovery) ----------------------------------

    def _reconstruct(self, row=None) -> None:
        row = row or self.store.load_account()
        self.initial_balance = float(row["initial_balance"])
        p = Portfolio(self.initial_balance, self.config.limits)
        p.cash = row["cash"]
        p.realized_pnl = row["realized_pnl"]
        p.fees_total = row["fees"]
        p.slippage_total = row["slippage"]
        p.peak_equity = row["peak_equity"]
        p.max_drawdown = row["max_drawdown"]
        p.max_drawdown_pct = row["max_drawdown_pct"]
        p.risk_blocked = row["risk_blocked"]
        p._daily_realized = json.loads(row["daily_realized"]) if row["daily_realized"] else {}
        pos = _pos_from_json(row["position"])
        if pos is not None:
            p.positions = [pos]
        self.portfolio = p
        self.sim = Simulator(self.config, p, self.symbol, self.timeframe.value)
        self.sim.position = pos
        self.sim.pending = json.loads(row["pending"]) if row["pending"] else None
        self.sim.trade_id = int(row["trade_id"])
        self.cursor = int(row["cursor"])
        self._pending_order_signal_time = row["pending_order_signal_time"]

    def _persist_state(self) -> None:
        p, sim = self.portfolio, self.sim
        self.store.save_account({
            "symbol": self.symbol, "timeframe": self.timeframe.value,
            "initial_balance": self.initial_balance, "cash": p.cash,
            "realized_pnl": p.realized_pnl, "fees": p.fees_total, "slippage": p.slippage_total,
            "peak_equity": p.peak_equity, "max_drawdown": p.max_drawdown,
            "max_drawdown_pct": p.max_drawdown_pct, "risk_blocked": p.risk_blocked,
            "trade_id": sim.trade_id, "cursor": self.cursor,
            "daily_realized": json.dumps(p._daily_realized),
            "position": _pos_to_json(sim.position), "pending": json.dumps(sim.pending),
            "pending_order_signal_time": self._pending_order_signal_time,
            "updated_at": int(self.cursor),
        })

    # -- processing ---------------------------------------------------------

    def process_new_candles(self, df: pd.DataFrame) -> dict:
        """Process only newly-CLOSED candles (close_time > cursor). Never raises."""
        if df is None or len(df) == 0:
            return {"processed": 0, "new_trades": 0, "error": None}
        df = df.sort_values("open_time").drop_duplicates("close_time", keep="first").reset_index(drop=True)
        o = df["open"].to_numpy(); h = df["high"].to_numpy()
        l = df["low"].to_numpy(); c = df["close"].to_numpy()
        ot = df["open_time"].to_numpy(); ct = df["close_time"].to_numpy()
        processed = 0
        new_trades = 0
        error = None
        for i in range(len(df)):
            close_time = int(ct[i])
            if close_time <= self.cursor:
                continue                                  # already processed / duplicate
            try:
                sig = self.signal_engine.evaluate_at(df, i, self.symbol, self.timeframe)
                self._journal_signal(sig, close_time)
                res = self.sim.process_candle(float(o[i]), float(h[i]), float(l[i]), float(c[i]),
                                              int(ot[i]), close_time, sig, i)
                self._record_step(res, close_time)
                self.cursor = close_time
                self._persist_state()
                processed += 1
                new_trades += len(res.closed_trades)
            except Exception as exc:  # keep the account consistent (spec 19)
                logger.error("paper step failed at %d: %s", i, exc,
                             extra={"symbol": self.symbol, "timeframe": self.timeframe.value})
                self._reconstruct()                        # revert to last persisted snapshot
                self.store.insert_journal(close_time, self.symbol, self.timeframe.value,
                                          JournalEventType.ERROR.value, detail=str(exc))
                error = str(exc)
                break
        return {"processed": processed, "new_trades": new_trades, "error": error}

    def finalize(self, last_close: float, last_close_time: int, bar_index: int) -> None:
        """Force-close a residual position (parity / end-of-session utility)."""
        trade = self.sim.force_close(last_close, last_close_time, bar_index)
        if trade is not None:
            self.store.insert_trade(trade.to_dict())
            self.store.insert_journal(last_close_time, self.symbol, self.timeframe.value,
                                      JournalEventType.EXIT.value, detail=f"END_OF_TEST net={trade.net_pnl:.4f}")
            self._persist_state()

    # -- recording helpers --------------------------------------------------

    def _journal_signal(self, sig: Signal, ts: int) -> None:
        self.store.insert_journal(
            ts, self.symbol, self.timeframe.value, JournalEventType.SIGNAL.value,
            signal=sig.direction.value, setup=sig.setup_type.value if sig.setup_type else None,
            raw_score=round(sig.raw_score, 2), final_score=round(sig.score, 2),
            blocked_by=list(sig.blocked_by))

    def _record_step(self, res: StepResult, ts: int) -> None:
        # Direction of the position this step concerns (for correct order sides):
        # a SHORT opens with a SELL and covers with a BUY (the mirror of a LONG).
        step_dir = "LONG"
        if res.opened is not None:
            step_dir = res.opened.direction
        elif self.sim.position is not None:
            step_dir = self.sim.position.direction
        elif res.closed_trades:
            step_dir = res.closed_trades[0].direction
        entry_side = OrderSide.SELL if step_dir == "SHORT" else OrderSide.BUY
        exit_side = OrderSide.BUY if step_dir == "SHORT" else OrderSide.SELL

        # a pending entry scheduled for the NEXT candle -> PENDING order
        if res.scheduled_signal_time is not None:
            sched_dir = (self.sim.pending.get("direction", "LONG") if self.sim.pending else "LONG")
            sched_side = OrderSide.SELL if sched_dir == "SHORT" else OrderSide.BUY
            oid = self.store.insert_order(Order(
                id=None, symbol=self.symbol, side=sched_side, type=OrderType.MARKET,
                quantity=0.0, requested_price=self.sim.pending["stop"] if self.sim.pending else None,
                filled_price=None, status=OrderStatus.PENDING, created_at=res.scheduled_signal_time,
                filled_at=None, reason="entry", signal_time=res.scheduled_signal_time))
            self._pending_order_signal_time = res.scheduled_signal_time

        # entry filled at this candle's open
        if res.opened is not None:
            pos = res.opened
            oid = self.store.find_pending_buy(pos.signal_time)
            if oid is not None:
                self.store.update_order(oid, status=OrderStatus.FILLED.value,
                                        quantity=pos.original_qty, filled_price=pos.entry_eff,
                                        requested_price=pos.entry_raw, filled_at=pos.entry_time,
                                        fees=pos.entry_fee, slippage=pos.entry_slippage)
            else:
                oid = self.store.insert_order(Order(
                    id=None, symbol=self.symbol, side=entry_side, type=OrderType.MARKET,
                    quantity=pos.original_qty, requested_price=pos.entry_raw,
                    filled_price=pos.entry_eff, status=OrderStatus.FILLED,
                    created_at=pos.signal_time, filled_at=pos.entry_time,
                    fees=pos.entry_fee, slippage=pos.entry_slippage,
                    reason="entry", signal_time=pos.signal_time))
            self.store.insert_fill(oid, self.symbol, pos.original_qty, pos.entry_eff,
                                   pos.entry_fee, pos.entry_slippage, pos.entry_time, "entry")
            self.store.insert_journal(pos.entry_time, self.symbol, self.timeframe.value,
                                      JournalEventType.POSITION_OPEN.value,
                                      detail=f"{pos.direction} qty={pos.original_qty:.6f} "
                                             f"entry={pos.entry_eff:.6f} stop={pos.stop:.6f}")
            self._pending_order_signal_time = None

        # entry blocked (risk / sizing)
        if res.entry_blocked_reason is not None:
            if self._pending_order_signal_time is not None:
                oid = self.store.find_pending_buy(self._pending_order_signal_time)
                if oid is not None:
                    self.store.update_order(oid, status=OrderStatus.REJECTED.value,
                                            reason=res.entry_blocked_reason)
            self.store.insert_journal(ts, self.symbol, self.timeframe.value,
                                      JournalEventType.RISK_BLOCKED.value, detail=res.entry_blocked_reason)
            self._pending_order_signal_time = None

        # exit legs -> closing fills (SELL for a long, BUY to cover a short)
        for leg in res.exit_legs:
            oid = self.store.insert_order(Order(
                id=None, symbol=self.symbol, side=exit_side, type=OrderType.MARKET,
                quantity=leg.qty, requested_price=None, filled_price=leg.price,
                status=OrderStatus.FILLED, created_at=leg.timestamp, filled_at=leg.timestamp,
                fees=leg.fees, slippage=leg.slippage, reason=leg.reason.value))
            self.store.insert_fill(oid, self.symbol, leg.qty, leg.price, leg.fees,
                                   leg.slippage, leg.timestamp, leg.reason.value)

        # closed trades
        for t in res.closed_trades:
            self.store.insert_trade(t.to_dict())
            self.store.insert_journal(t.exit_timestamp, self.symbol, self.timeframe.value,
                                      JournalEventType.EXIT.value,
                                      detail=f"{t.exit_reason.value} net={t.net_pnl:.4f} R={t.r_multiple:.3f}")

        # equity snapshot
        ep = res.equity_point
        if ep is not None:
            self.store.insert_equity(ep.timestamp, ep.cash, ep.equity, ep.drawdown, ep.drawdown_pct)

    # -- reset --------------------------------------------------------------

    def reset(self, confirm: str) -> None:
        """Wipe and recreate the paper account. Requires confirm == RESET_TOKEN."""
        if confirm != RESET_TOKEN:
            raise ValueError(f"reset requires explicit confirmation token '{RESET_TOKEN}'")
        self.store.reset()
        self.portfolio = Portfolio(self.initial_balance, self.config.limits)
        self.sim = Simulator(self.config, self.portfolio, self.symbol, self.timeframe.value)
        self.cursor = -1
        self._pending_order_signal_time = None
        self._persist_state()
        self.store.insert_journal(0, self.symbol, self.timeframe.value,
                                  JournalEventType.RESET.value, detail="paper account reset")

    # -- views --------------------------------------------------------------

    def account_view(self, price: Optional[float]) -> AccountView:
        return build_account_view(self.portfolio, self.sim.position, price, self.initial_balance)

    def open_position_view(self, price: float, now_ms: int) -> Optional[PositionView]:
        if self.sim.position is None or not self.sim.position.is_open:
            return None
        return build_position_view(self.sim.position, price, now_ms)

    def close(self) -> None:
        self.store.close()
