"""Headless CLI entry point — NO Streamlit.

    python cli.py --testnet-check     # Testnet readiness (places NO orders)
    python cli.py --live-check        # always "LIVE TRADING DISABLED"
    python cli.py --check             # public market-data connectivity self-check

This module never imports Streamlit, so these commands are guaranteed headless.
``app.py`` also honours the same flags (delegating here) before it ever touches
Streamlit, but ``cli.py`` is the recommended way to run the checks.
"""
from __future__ import annotations

import sys
from typing import List, Optional

_USAGE = "usage: python cli.py [--check | --testnet-check | --live-check]"


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--testnet-check" in argv:
        from binance.readiness import testnet_check
        return testnet_check()

    if "--live-check" in argv:
        from binance.readiness import live_check
        return live_check()

    if "--check" in argv:
        # Public market-data connectivity self-check (also headless).
        from binance.connectivity import connectivity_check
        return connectivity_check()

    print(_USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
