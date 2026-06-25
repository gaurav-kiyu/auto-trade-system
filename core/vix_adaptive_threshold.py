"""
VIX Adaptive Threshold Engine - Adjusts signal thresholds based on volatility
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

_log = logging.getLogger(__name__)


@dataclass
class VIXAdaptiveConfig:
    enabled: bool = True
    vix_low_threshold: float = 15.0
    vix_low_bonus: int = -2
    vix_high_threshold: float = 25.0
    vix_high_penalty: int = 5
    vix_block_threshold: float = 30.0


class VIXAdaptiveThreshold:
    def __init__(self, config: VIXAdaptiveConfig):
        self.config = config
        self._current_vix = None

    def update_vix(self, vix: float):
        self._current_vix = vix
        _log.debug(f"Updated VIX: {vix}")

    def get_adjusted_threshold(self, base_threshold: int) -> int:
        if not self.config.enabled or self._current_vix is None:
            return base_threshold

        if self._current_vix >= self.config.vix_block_threshold:
            _log.warning(f"VIX {self._current_vix} above block threshold {self.config.vix_block_threshold}")
            return base_threshold + 100

        if self._current_vix < self.config.vix_low_threshold:
            adjusted = base_threshold + self.config.vix_low_bonus
            _log.info(f"VIX {self._current_vix} below low threshold - relaxed by {self.config.vix_low_bonus}")
            return max(50, adjusted)

        if self._current_vix > self.config.vix_high_threshold:
            adjusted = base_threshold + self.config.vix_high_penalty
            _log.info(f"VIX {self._current_vix} above high threshold - tightened by {self.config.vix_high_penalty}")
            return min(100, adjusted)

        return base_threshold

    def should_block_entry(self) -> tuple[bool, str]:
        if not self.config.enabled or self._current_vix is None:
            return False, ""
        if self._current_vix >= self.config.vix_block_threshold:
            return True, f"VIX {self._current_vix} exceeds block threshold {self.config.vix_block_threshold}"
        return False, ""


def create_vix_adaptive_threshold(config: dict) -> VIXAdaptiveThreshold:
    cfg = VIXAdaptiveConfig(
        enabled=config.get("VIX_ADAPTIVE_THRESHOLDS_ENABLED", True),
        vix_low_threshold=config.get("VIX_LOW_THRESHOLD", 15.0),
        vix_low_bonus=config.get("VIX_LOW_BONUS", -2),
        vix_high_threshold=config.get("VIX_HIGH_THRESHOLD", 25.0),
        vix_high_penalty=config.get("VIX_HIGH_PENALTY", 5),
        vix_block_threshold=config.get("VIX_BLOCK_THRESHOLD", 30.0),
    )
    return VIXAdaptiveThreshold(cfg)


__all__ = [
    "VIXAdaptiveConfig",
    "VIXAdaptiveThreshold",
    "create_vix_adaptive_threshold",
]

