"""Layer 1: Market Regime Engine with Hysteresis (v6.0 Production).

5 Discrete States:
1. TRENDING_BULLISH
2. TRENDING_BEARISH
3. RANGE_BOUND_CHOPPY
4. VOLATILITY_EXPANSION_ANOMALY
5. TRANSITIONAL_UNCERTAIN
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.logging import get_logger

_log = get_logger("QUANT_REGIME")


@dataclass
class RegimeState:
    regime: str  # TRENDING_BULLISH, TRENDING_BEARISH, RANGE_BOUND_CHOPPY, VOLATILITY_EXPANSION_ANOMALY, TRANSITIONAL_UNCERTAIN
    confidence: float  # 0.0 to 1.0
    adx: float
    vix_zscore: float
    trend_direction: str  # BULLISH, BEARISH, NEUTRAL
    details: dict[str, Any]


class MarketRegimeEngine:
    """Institutional Market Regime Detection Engine with Hysteresis."""

    def __init__(
        self,
        trend_enter_adx: float = 26.0,
        trend_exit_adx: float = 22.0,
        range_max_adx: float = 19.0,
        vix_anomaly_zscore: float = 2.0,
    ) -> None:
        self._trend_enter_adx = trend_enter_adx
        self._trend_exit_adx = trend_exit_adx
        self._range_max_adx = range_max_adx
        self._vix_anomaly_zscore = vix_anomaly_zscore
        self._last_regime: str = "TRANSITIONAL_UNCERTAIN"

    def detect_regime(
        self,
        adx: float,
        price: float,
        vwap: float,
        supertrend_dir: str = "BULLISH",
        vix_zscore: float = 0.0,
        rsi: float = 50.0,
    ) -> RegimeState:
        """Detect current market regime with hysteresis dampening."""
        details: dict[str, Any] = {
            "adx": adx,
            "vwap_diff_pct": ((price - vwap) / vwap * 100.0) if vwap > 0 else 0.0,
            "supertrend_dir": supertrend_dir,
            "vix_zscore": vix_zscore,
            "previous_regime": self._last_regime,
        }

        # 1. Volatility Expansion Anomaly Check
        if vix_zscore >= self._vix_anomaly_zscore:
            current_regime = "VOLATILITY_EXPANSION_ANOMALY"
            confidence = min(0.98, 0.75 + (vix_zscore - 2.0) * 0.1)
            self._last_regime = current_regime
            return RegimeState(current_regime, confidence, adx, vix_zscore, "NEUTRAL", details)

        # 2. Trending Regime with Hysteresis
        is_currently_trending = self._last_regime in ("TRENDING_BULLISH", "TRENDING_BEARISH")
        trend_threshold = self._trend_exit_adx if is_currently_trending else self._trend_enter_adx

        if adx >= trend_threshold:
            if price >= vwap and supertrend_dir == "BULLISH":
                current_regime = "TRENDING_BULLISH"
                direction = "BULLISH"
            elif price < vwap and supertrend_dir == "BEARISH":
                current_regime = "TRENDING_BEARISH"
                direction = "BEARISH"
            else:
                current_regime = "TRANSITIONAL_UNCERTAIN"
                direction = "NEUTRAL"

            confidence = min(0.95, 0.60 + (adx / 50.0) * 0.35)
            self._last_regime = current_regime
            return RegimeState(current_regime, confidence, adx, vix_zscore, direction, details)

        # 3. Range Bound Choppy Regime
        if adx <= self._range_max_adx:
            current_regime = "RANGE_BOUND_CHOPPY"
            confidence = min(0.90, 0.65 + ((20.0 - adx) / 20.0) * 0.25)
            self._last_regime = current_regime
            return RegimeState(current_regime, confidence, adx, vix_zscore, "NEUTRAL", details)

        # 4. Transitional / Uncertain (Default)
        current_regime = "TRANSITIONAL_UNCERTAIN"
        confidence = 0.50
        self._last_regime = current_regime
        return RegimeState(current_regime, confidence, adx, vix_zscore, "NEUTRAL", details)
