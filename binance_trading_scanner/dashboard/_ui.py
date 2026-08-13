"""Small presentation helpers shared by dashboard pages.

Pure formatting only — no analysis logic lives here.
"""
from __future__ import annotations

from typing import Optional

from core.enums import SignalType

# Colour-blind-friendly palette (teal for long, red for short, grey for none).
SIGNAL_COLORS = {
    SignalType.LONG.value: "#0e9f6e",       # green
    SignalType.SHORT.value: "#e02424",      # red
    SignalType.NEUTRAL.value: "#8a8f98",    # grey
    SignalType.NO_TRADE.value: "#6b7280",   # slate
}


def fmt_price(x: Optional[float]) -> str:
    if x is None:
        return "—"
    ax = abs(x)
    if ax >= 1000:
        return f"{x:,.2f}"
    if ax >= 1:
        return f"{x:,.4f}"
    return f"{x:.6f}"


def fmt_pct(x: Optional[float], plus: bool = True) -> str:
    if x is None:
        return "—"
    sign = "+" if (plus and x >= 0) else ""
    return f"{sign}{x:.2f}%"


def fmt_num(x: Optional[float], nd: int = 1) -> str:
    if x is None:
        return "—"
    return f"{x:,.{nd}f}"


def signal_color(signal: Optional[str]) -> str:
    return SIGNAL_COLORS.get(signal or "", "#6b7280")


def signal_badge_html(signal: str) -> str:
    color = signal_color(signal)
    return (
        f"<span style='background:{color};color:white;padding:2px 10px;"
        f"border-radius:10px;font-weight:600;font-size:0.85rem'>{signal}</span>"
    )
