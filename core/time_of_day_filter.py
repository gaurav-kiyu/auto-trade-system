"""
Time-of-Day Filter - Blocks or restricts trading during low liquidity periods
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)


@dataclass
class TimeOfDayConfig:
    enabled: bool = True
    block_start_hour: int = 14
    block_end_hour: int = 15
    allow_trending_only: bool = True


class TimeOfDayFilter:
    def __init__(self, config: TimeOfDayConfig):
        self.config = config

    def should_allow_entry(self, regime: str = None) -> tuple[bool, str]:
        if not self.config.enabled:
            return True, ""

        now = now_ist()
        hour = now.hour

        in_blocked_period = (
            self.config.block_start_hour <= hour < self.config.block_end_hour
        )

        if in_blocked_period:
            if self.config.allow_trending_only and regime:
                if regime.upper() in ["TRENDING", "BULLISH"]:
                    return True, "Blocked hour but allowing TRENDING regime"
                return False, f"Blocked hour ({hour}) for non-TRENDING regime"
            return False, f"Blocked trading hours: {self.config.block_start_hour}-{self.config.block_end_hour} IST"

        return True, ""

    def get_restriction_level(self) -> str:
        if not self.config.enabled:
            return "NONE"
        now = now_ist()
        hour = now.hour
        if self.config.block_start_hour <= hour < self.config.block_end_hour:
            return "BLOCKED"
        return "ALLOWED"


def create_time_of_day_filter(config: dict) -> TimeOfDayFilter:
    cfg = TimeOfDayConfig(
        enabled=config.get("TIME_OF_DAY_FILTER_ENABLED", True),
        block_start_hour=config.get("TIME_OF_DAY_BLOCK_START_HOUR", 14),
        block_end_hour=config.get("TIME_OF_DAY_BLOCK_END_HOUR", 15),
        allow_trending_only=config.get("TIME_OF_DAY_ALLOW_TRENDING_ONLY", True),
    )
    return TimeOfDayFilter(cfg)
