"""Signal filters.

Filters are the second gate after raw scoring. A filter can veto a candidate
LONG and turn it into NO_TRADE **regardless of how high the raw score is**
(spec section 15). Keeping them separate from scoring means we can later analyse
*why* strong-looking setups were rejected.

Each filter is a small pure function over :class:`FilterContext`; ``apply``
runs them all and returns the blocks and warnings. Nothing here places orders or
touches the network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core.enums import SetupType, SignalType, StructureClass, TrendClass


@dataclass
class FilterContext:
    n_bars: int
    min_bars: int
    candidate: bool                       # a qualifying setup exists in ``direction``
    atr_pct: Optional[float]
    atr_pct_extreme: float
    rvol: Optional[float]
    vol_sma: Optional[float]
    quote_volume: Optional[float]
    min_quote_volume: Optional[float]
    structure_class: StructureClass
    setup: SetupType
    risk_reward: Optional[float]
    min_rr: float
    htf_trend: Optional[TrendClass]
    volume_confirmed: bool
    direction: SignalType = SignalType.LONG   # side being evaluated (LONG/SHORT)


@dataclass
class FilterResult:
    name: str
    passed: bool
    severity: str        # "block" | "warn"
    reason: str = ""


@dataclass
class FilterOutcome:
    blocked: bool
    blocks: List[FilterResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def block_names(self) -> List[str]:
        return [b.name for b in self.blocks]


# -- individual filters -----------------------------------------------------

def _insufficient_data(ctx: FilterContext) -> FilterResult:
    ok = ctx.n_bars >= ctx.min_bars
    return FilterResult(
        "insufficient_data", ok, "block",
        "" if ok else f"Only {ctx.n_bars} bars (need >= {ctx.min_bars})",
    )


def _low_liquidity(ctx: FilterContext) -> FilterResult:
    # Absolute floor if the caller provided one; otherwise a volume-presence proxy.
    if ctx.min_quote_volume is not None and ctx.quote_volume is not None:
        ok = ctx.quote_volume >= ctx.min_quote_volume
        return FilterResult("low_liquidity", ok, "block",
                            "" if ok else f"Quote volume {ctx.quote_volume:.0f} below floor")
    ok = ctx.vol_sma is not None and ctx.vol_sma > 0
    return FilterResult("low_liquidity", ok, "block",
                        "" if ok else "No/negligible traded volume")


def _extreme_volatility(ctx: FilterContext) -> FilterResult:
    if ctx.atr_pct is None:
        return FilterResult("extreme_volatility", True, "block")
    ok = ctx.atr_pct <= ctx.atr_pct_extreme
    return FilterResult("extreme_volatility", ok, "block",
                        "" if ok else f"ATR {ctx.atr_pct*100:.1f}% of price is extreme")


def _invalid_structure(ctx: FilterContext) -> FilterResult:
    if not ctx.candidate:
        return FilterResult("invalid_structure", True, "block")
    ok = ctx.structure_class != StructureClass.TRANSITION
    return FilterResult("invalid_structure", ok, "block",
                        "" if ok else "Structure in transition (no confirmed swings)")


def _poor_risk_reward(ctx: FilterContext) -> FilterResult:
    if not ctx.candidate or ctx.risk_reward is None:
        return FilterResult("poor_risk_reward", True, "block")
    ok = ctx.risk_reward >= ctx.min_rr
    return FilterResult("poor_risk_reward", ok, "block",
                        "" if ok else f"R:R {ctx.risk_reward:.2f} below {ctx.min_rr}")


def _conflicting_htf(ctx: FilterContext) -> FilterResult:
    if not ctx.candidate or ctx.htf_trend is None:
        return FilterResult("conflicting_higher_timeframe", True, "block")
    # A LONG conflicts with a bearish HTF; a SHORT conflicts with a bullish HTF.
    if ctx.direction is SignalType.SHORT:
        ok = not ctx.htf_trend.is_bullish
    else:
        ok = not ctx.htf_trend.is_bearish
    return FilterResult("conflicting_higher_timeframe", ok, "block",
                        "" if ok else f"Higher timeframe is {ctx.htf_trend.value}")


def _no_volume_confirmation(ctx: FilterContext) -> FilterResult:
    # Only breakouts/breakdowns strictly require volume confirmation.
    is_breakout = ctx.setup in (SetupType.BREAKOUT, SetupType.RANGE_BREAKOUT)
    if not ctx.candidate or not is_breakout:
        return FilterResult("no_volume_confirmation", True, "block")
    ok = ctx.volume_confirmed
    return FilterResult("no_volume_confirmation", ok, "block",
                        "" if ok else "Breakout without volume confirmation")


_FILTERS = [
    _insufficient_data,
    _low_liquidity,
    _extreme_volatility,
    _invalid_structure,
    _poor_risk_reward,
    _conflicting_htf,
    _no_volume_confirmation,
]


def apply(ctx: FilterContext) -> FilterOutcome:
    """Run every filter; collect the ones that veto the signal."""
    blocks: List[FilterResult] = []
    warnings: List[str] = []
    for f in _FILTERS:
        r = f(ctx)
        if not r.passed:
            blocks.append(r)
            if r.reason:
                warnings.append(f"[{r.name}] {r.reason}")
    return FilterOutcome(blocked=bool(blocks), blocks=blocks, warnings=warnings)
