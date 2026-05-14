"""
FINNIFTY Specific Filter - Additional filters for FINNIFTY underperformance
"""
from __future__ import annotations
from dataclasses import dataclass
import logging

_log = logging.getLogger(__name__)


@dataclass
class FINNIFTYFilterConfig:
    enabled: bool = True
    min_score_offset: int = 5
    min_iv_rank: float = 25.0
    require_trending_regime: bool = True


class FINNIFTYFilter:
    def __init__(self, config: FINNIFTYFilterConfig):
        self.config = config
        self._default_min_score = 60

    def should_allow_entry(
        self,
        index_name: str,
        score: int,
        iv_rank: float,
        regime: str,
    ) -> tuple[bool, str]:
        if not self.config.enabled:
            return True, ""

        if index_name != "FINNIFTY":
            return True, ""

        adjusted_min_score = self._default_min_score + self.config.min_score_offset
        if score < adjusted_min_score:
            return False, f"FINNIFTY score {score} below adjusted threshold {adjusted_min_score}"

        if iv_rank < self.config.min_iv_rank:
            return False, f"FINNIFTY IV rank {iv_rank} below minimum {self.config.min_iv_rank}"

        if self.config.require_trending_regime and regime.upper() not in ["TRENDING", "BULLISH"]:
            return False, f"FINNIFTY requires TRENDING regime, current: {regime}"

        _log.info(f"FINNIFTY passed enhanced filters: score={score}, IV={iv_rank}, regime={regime}")
        return True, ""

    def get_adjusted_threshold(self) -> int:
        if self.config.enabled:
            return self._default_min_score + self.config.min_score_offset
        return self._default_min_score


def create_finnifty_filter(config: dict) -> FINNIFTYFilter:
    cfg = FINNIFTYFilterConfig(
        enabled=config.get("FINNIFTY_SPECIFIC_ENABLED", True),
        min_score_offset=config.get("FINNIFTY_MIN_SCORE_OFFSET", 5),
        min_iv_rank=config.get("FINNIFTY_MIN_IV_RANK", 25.0),
        require_trending_regime=config.get("FINNIFTY_REGIME_REQUIRE_TRENDING", True),
    )
    return FINNIFTYFilter(cfg)