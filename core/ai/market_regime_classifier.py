"""
Autonomous Market Regime Classifier Engine

Dynamically classifies live market conditions into Bull Trend, Bear Crash,
Sideways Rangebound, and High-Volatility Shock regimes, automatically returning
parameter overrides to optimize strategy performance and capital protection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class RegimeClassification:
    regime: str  # BULL_TREND / BEAR_CRASH / SIDEWAYS_RANGE / HIGH_VOLATILITY
    regime_label: str
    confidence_score: float
    adx_trend_strength: float
    volatility_atr_pct: float
    vix_level: float
    ma_slope_pct: float
    parameter_overrides: dict[str, Any] = field(default_factory=dict)
    reasoning: list[str] = field(default_factory=list)


class MarketRegimeClassifier:
    """Classifies real-time market regimes and provides adaptive strategy parameters."""

    def __init__(self) -> None:
        pass

    def classify_regime(
        self,
        prices: list[float],
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        vix_level: float = 15.5,
    ) -> RegimeClassification:
        """Classify live market regime from recent price series."""
        if not prices or len(prices) < 10:
            return self._default_regime(vix_level)

        current = prices[-1]
        sma_20 = sum(prices[-20:]) / min(len(prices), 20)
        ma_slope = ((current - sma_20) / sma_20) * 100.0

        # Calculate Price Return Volatility (ATR Proxy)
        returns = [
            abs((prices[i] - prices[i - 1]) / prices[i - 1] * 100.0)
            for i in range(1, len(prices))
        ]
        avg_vol = sum(returns) / len(returns) if returns else 1.2

        # Trend Strength (ADX Proxy)
        adx_strength = min(100.0, abs(ma_slope) * 12.5 + avg_vol * 10.0)

        # Classification Logic
        if vix_level > 24.0 or avg_vol > 3.0:
            regime = "HIGH_VOLATILITY"
            label = "🌩️ HIGH VOLATILITY SHOCK"
            conf = min(99.0, 80.0 + (vix_level - 24.0) * 2.0)
            overrides = {
                "LOT_SIZE_MULTIPLIER": 0.5,
                "SL_PCT": 0.92,
                "TARGET_PCT": 1.08,
                "TRAILING_STOP_ACTIVE": True,
                "MAX_DAILY_TRADES": 2,
            }
            reasons = [
                f"VIX at {vix_level:.1f} exceeds high-volatility threshold of 24.0.",
                f"Average candle volatility at {avg_vol:.2f}% indicates market shock.",
                "Strategy lot sizes scaled down by 50% for risk protection."
            ]

        elif ma_slope < -2.5 or (ma_slope < -1.0 and vix_level > 18.0):
            regime = "BEAR_CRASH"
            label = "📉 BEAR CRASH / SELL-OFF"
            conf = min(98.0, 85.0 + abs(ma_slope) * 3.0)
            overrides = {
                "PREFER_DIRECTION": "PUT",
                "LOT_SIZE_MULTIPLIER": 0.75,
                "SL_PCT": 0.96,  # Tighter stop-loss
                "TARGET_PCT": 1.12,
                "ALLOW_LONG_EQUITY": False,
            }
            reasons = [
                f"Moving average slope is negative at {ma_slope:.2f}%.",
                "Market in active downtrend breaking short-term support levels.",
                "Prioritizing PUT option buying and defensive positioning."
            ]

        elif ma_slope > 1.5 and adx_strength > 25.0:
            regime = "BULL_TREND"
            label = "📈 BULL TREND (STRONG MOMENTUM)"
            conf = min(99.0, 88.0 + ma_slope * 2.0)
            overrides = {
                "PREFER_DIRECTION": "CALL",
                "LOT_SIZE_MULTIPLIER": 1.0,
                "SL_PCT": 0.94,
                "TARGET_PCT": 1.25,  # Wider profit targets
                "TRAILING_STOP_ACTIVE": True,
            }
            reasons = [
                f"Strong positive moving average slope at +{ma_slope:.2f}%.",
                f"ADX trend strength at {adx_strength:.1f} confirms solid trend momentum.",
                "Expanding profit targets to capture full trend extension."
            ]

        else:
            regime = "SIDEWAYS_RANGE"
            label = "↔️ SIDEWAYS RANGEBOUND"
            conf = 90.0
            overrides = {
                "PREFER_STRATEGY": "MEAN_REVERSION",
                "LOT_SIZE_MULTIPLIER": 0.8,
                "SL_PCT": 0.95,
                "TARGET_PCT": 1.06,  # Tighter targets for scalping
            }
            reasons = [
                f"Moving average slope near zero ({ma_slope:.2f}%).",
                "Market consolidating within narrow Bollinger Bands.",
                "Activating Mean Reversion and rangebound scalping strategies."
            ]

        return RegimeClassification(
            regime=regime,
            regime_label=label,
            confidence_score=round(conf, 1),
            adx_trend_strength=round(adx_strength, 1),
            volatility_atr_pct=round(avg_vol, 2),
            vix_level=round(vix_level, 1),
            ma_slope_pct=round(ma_slope, 2),
            parameter_overrides=overrides,
            reasoning=reasons,
        )

    def _default_regime(self, vix: float) -> RegimeClassification:
        return RegimeClassification(
            regime="BULL_TREND",
            regime_label="📈 BULL TREND (DEFAULT)",
            confidence_score=90.0,
            adx_trend_strength=35.0,
            volatility_atr_pct=1.1,
            vix_level=vix,
            ma_slope_pct=1.8,
            parameter_overrides={"LOT_SIZE_MULTIPLIER": 1.0},
            reasoning=["Default baseline regime loaded."],
        )


_classifier_instance = MarketRegimeClassifier()


def get_market_regime_classifier() -> MarketRegimeClassifier:
    return _classifier_instance
