"""Signal Engine Domain Models - Trading signal generation and scoring.

Models all signal-related data structures:
  - TradingSignal: Generated trade signal with strength/direction/quality
  - MarketData: OHLCV candle data for analysis
  - TechnicalIndicators: SMA, EMA, MACD, RSI, Bollinger, ATR, ADX, etc.
  - SignalService: Core signal generation engine
  - MarketConditions, OrderFlowData, SentimentData: Market context models

Usage:
    from core.domains.signal_engine import (
        TradingSignal, MarketData, Candle,
        TechnicalIndicators, SignalQuality, SignalService
    )
"""
from core.domains.signal_engine.model import (
    Candle,
    MarketConditions as MarketConditionsModel,
    MarketData,
    OrderFlowData,
    PriceLevel,
    SentimentData,
    SignalQuality,
    TechnicalIndicators,
    TimeFrame,
    TradingSignal,
    VolumeProfile,
)
from core.domains.signal_engine.service import SignalService, create_signal_service

__all__ = [
    "Candle",
    "MarketConditionsModel",
    "MarketData",
    "OrderFlowData",
    "PriceLevel",
    "SentimentData",
    "SignalQuality",
    "SignalService",
    "TechnicalIndicators",
    "TimeFrame",
    "TradingSignal",
    "VolumeProfile",
    "create_signal_service",
]
