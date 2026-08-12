"""Anti-overtrading protection (spec: cooldown, separation, caps, loss streaks).

The stateless :func:`trading.safety.check_order` guards a SINGLE order (filters,
notional, balance, duplicate). Overtrading protection is different: it is
stateful across candles and directions, so it lives here and is consulted before
a new entry is scheduled.

Rules (all opt-in; a 0 disables the rule):
  * ``cooldown_bars`` — minimum bars between two entries.
  * ``min_signal_separation_ms`` — minimum wall-clock gap between entries.
  * ``max_trades_per_day`` — cap on entries opened per UTC day.
  * ``max_consecutive_losses`` — stop opening new trades after N losing trades in
    a row (until a winner resets the streak, or the guard is reset).

This applies equally to LONG and SHORT — a SHORT counts toward the same caps.
Deterministic and side-effect free except for its own counters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple


@dataclass
class OvertradingConfig:
    cooldown_bars: int = 0
    min_signal_separation_ms: int = 0
    max_trades_per_day: int = 0        # 0 == unlimited
    max_consecutive_losses: int = 0    # 0 == disabled


def _day_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass
class OvertradingGuard:
    """Stateful gate. Ask :meth:`allow_entry` before scheduling; then record."""

    cfg: OvertradingConfig = field(default_factory=OvertradingConfig)
    last_entry_bar: Optional[int] = None
    last_entry_time: Optional[int] = None
    trades_per_day: Dict[str, int] = field(default_factory=dict)
    consecutive_losses: int = 0

    def allow_entry(self, bar_index: int, now_ms: int) -> Tuple[bool, str]:
        """Return (allowed, reason). ``reason`` is empty when allowed."""
        c = self.cfg
        if c.max_consecutive_losses and self.consecutive_losses >= c.max_consecutive_losses:
            return False, (f"consecutive_loss_protection: {self.consecutive_losses} "
                           f">= {c.max_consecutive_losses} losses")
        if c.cooldown_bars and self.last_entry_bar is not None:
            if bar_index - self.last_entry_bar < c.cooldown_bars:
                return False, (f"cooldown: {bar_index - self.last_entry_bar} < "
                               f"{c.cooldown_bars} bars since last entry")
        if c.min_signal_separation_ms and self.last_entry_time is not None:
            if now_ms - self.last_entry_time < c.min_signal_separation_ms:
                return False, "min_signal_separation not met"
        if c.max_trades_per_day:
            if self.trades_per_day.get(_day_key(now_ms), 0) >= c.max_trades_per_day:
                return False, f"max_trades_per_day {c.max_trades_per_day} reached"
        return True, ""

    def record_entry(self, bar_index: int, now_ms: int) -> None:
        self.last_entry_bar = bar_index
        self.last_entry_time = now_ms
        key = _day_key(now_ms)
        self.trades_per_day[key] = self.trades_per_day.get(key, 0) + 1

    def record_result(self, net_pnl: float) -> None:
        """Update the loss streak from a CLOSED trade's realised net PnL."""
        if net_pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def reset(self) -> None:
        self.last_entry_bar = None
        self.last_entry_time = None
        self.trades_per_day.clear()
        self.consecutive_losses = 0
