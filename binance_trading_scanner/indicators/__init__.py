"""Indicators package.

Isolated, causal, individually-testable technical indicators. Every function
works on pandas Series/DataFrames and never uses future data. For signal/backtest
use, feed only CLOSED candles (see ``binance.market_data.get_closed_klines``).
"""
from .momentum import macd, rsi, stoch_rsi
from .structure import (
    StructureState,
    SupportResistance,
    breakout_detection,
    market_structure,
    support_resistance,
    swing_highs,
    swing_lows,
)
from .trend import adx, ema, ema_20, ema_50, ema_200, sma, sma_200
from .volatility import atr, bollinger_band_width, bollinger_bands, true_range
from .volume import obv, relative_volume, rolling_vwap, volume_sma, vwap

__all__ = [
    # trend
    "ema", "sma", "ema_20", "ema_50", "ema_200", "sma_200", "adx",
    # momentum
    "rsi", "macd", "stoch_rsi",
    # volatility
    "true_range", "atr", "bollinger_bands", "bollinger_band_width",
    # volume
    "volume_sma", "relative_volume", "obv", "vwap", "rolling_vwap",
    # structure
    "swing_highs", "swing_lows", "market_structure", "StructureState",
    "breakout_detection", "support_resistance", "SupportResistance",
]
