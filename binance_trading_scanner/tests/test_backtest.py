"""Backtest tests — scheduled for Phase 5.

Placeholder so the suite stays green until the Phase 5 implementation lands.
Real cases (per the spec) will cover computation correctness and edge cases:
zero volume, missing/duplicate candles, invalid inputs, extreme values.
"""
import pytest

pytestmark = pytest.mark.skip(reason="backtest implemented in Phase 5")


def test_placeholder():
    assert True
