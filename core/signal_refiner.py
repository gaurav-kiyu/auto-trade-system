"""
Signal Refiner - Multi-indicator confirmation and false signal filtering
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

_log = logging.getLogger(__name__)


@dataclass
class SignalRefinerConfig:
    enabled: bool = True
    rsi_confirm_threshold: float = 45.0
    macd_confirm_required: bool = False
    adx_confirm_min: float = 20.0
    iv_block_threshold: float = 28.0
    regime_aware_thresholds: bool = True
    threshold_trending_adjust: int = -2
    threshold_sideways_adjust: int = 2
    threshold_range_adjust: int = 3
    false_signal_filter: bool = True
    false_signal_min_score_block: int = 75
    false_signal_iv_threshold: float = 26.0


class SignalRefiner:
    def __init__(self, config: SignalRefinerConfig):
        self.config = config

    def should_block_signal(
        self,
        score: int,
        regime: str,
        iv_rank: float,
        rsi: float | None = None,
        macd: str | None = None,
        adx: float | None = None,
        vix: float | None = None,
    ) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, ""

        if self.config.false_signal_filter:
            if score >= self.config.false_signal_min_score_block and iv_rank >= self.config.false_signal_iv_threshold:
                reason = f"BLOCKED: High score ({score}) but IV rank ({iv_rank:.1f}) above threshold"
                _log.warning(f"False signal filter blocked: {reason}")
                return True, reason

        if self.config.enabled and rsi is not None:
            if abs(rsi - 50) < self.config.rsi_confirm_threshold:
                reason = f"BLOCKED: RSI ({rsi:.1f}) too close to neutral (50)"
                _log.info(f"RSI confirmation blocked: {reason}")
                return True, reason

        if self.config.macd_confirm_required and macd:
            if macd not in ["BULLISH", "BEARISH"]:
                reason = f"BLOCKED: MACD ({macd}) not confirming direction"
                _log.info(f"MACD confirmation blocked: {reason}")
                return True, reason

        if self.config.adx_confirm_min > 0 and adx is not None:
            if adx < self.config.adx_confirm_min:
                reason = f"BLOCKED: ADX ({adx:.1f}) below confirmation threshold ({self.config.adx_confirm_min})"
                _log.info(f"ADX confirmation blocked: {reason}")
                return True, reason

        if vix and vix > self.config.iv_block_threshold:
            reason = f"BLOCKED: VIX ({vix:.1f}) above IV block threshold ({self.config.iv_block_threshold})"
            _log.warning(f"Volatility block: {reason}")
            return True, reason

        return False, ""

    def get_regime_adjusted_threshold(self, base_threshold: int, regime: str) -> int:
        if not self.config.regime_aware_thresholds:
            return base_threshold

        if regime == "TRENDING":
            return base_threshold + self.config.threshold_trending_adjust
        elif regime == "SIDEWAYS":
            return base_threshold + self.config.threshold_sideways_adjust
        elif regime == "RANGE":
            return base_threshold + self.config.threshold_range_adjust
        return base_threshold


def create_signal_refiner(config: dict) -> SignalRefiner:
    cfg = SignalRefinerConfig(
        enabled=config.get("VOLATILITY_CONFIRMATION_ENABLED", True),
        rsi_confirm_threshold=config.get("VOLATILITY_RSI_CONFIRM_THRESHOLD", 45.0),
        macd_confirm_required=config.get("VOLATILITY_MACD_CONFIRM_REQUIRED", False),
        adx_confirm_min=config.get("VOLATILITY_ADX_CONFIRM_MIN", 20.0),
        iv_block_threshold=config.get("VOLATILITY_IV_BLOCK_THRESHOLD", 28.0),
        regime_aware_thresholds=config.get("REGIME_AWARE_THRESHOLDS_ENABLED", True),
        threshold_trending_adjust=config.get("REGIME_THRESHOLD_TRENDING_ADJUST", -2),
        threshold_sideways_adjust=config.get("REGIME_THRESHOLD_SIDEWAYS_ADJUST", 2),
        threshold_range_adjust=config.get("REGIME_THRESHOLD_RANGE_ADJUST", 3),
        false_signal_filter=config.get("FALSE_SIGNAL_FILTER_ENABLED", True),
        false_signal_min_score_block=config.get("FALSE_SIGNAL_MIN_SCORE_BLOCK", 75),
        false_signal_iv_threshold=config.get("FALSE_SIGNAL_IV_THRESHOLD_BLOCK", 26.0),
    )
    return SignalRefiner(cfg)
