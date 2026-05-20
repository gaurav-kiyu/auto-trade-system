"""
Expiry-Day Strategy Controller (Phase 2).

Strategy-aware expiry-day controls:
- Conditionally blocks based on strategy type
- Time-based warnings for high-risk periods
- Premium decay estimation for theta strategies
- gamma risk warnings for short options
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from datetime import time as dt_time
from core.datetime_ist import now_ist
from enum import Enum

log = logging.getLogger(__name__)


class StrategyType(str, Enum):
    DIRECTIONAL = "DIRECTIONAL"
    SPREAD = "SPREAD"
    STRADDLE = "STRADDLE"
    IRON_CONDOR = "IRON_CONDOR"
    OPTIONS_SELLING = "OPTIONS_SELLING"
    UNKNOWN = "UNKNOWN"


class ExpirySession(str, Enum):
    MORNING = "MORNING"
    MIDDAY = "MIDDAY"
    CAUTION = "CAUTION"
    BLOCKED = "BLOCKED"


@dataclass
class ExpiryControlResult:
    allowed: bool
    session: ExpirySession
    reason: str
    risk_level: str
    warnings: list[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class ExpiryDayController:
    """
    Strategy-aware expiry-day trading controls.

    Provides intelligent controls based on:
    - Strategy type (directional vs spread vs selling)
    - Time of day
    - Position type (long vs short options)
    - Market conditions
    """

    CAUTION_START = dt_time(12, 30)
    BLOCK_AFTER = dt_time(13, 0)
    CLOSE_ALL_BY = dt_time(14, 30)

    def __init__(
        self,
        strategy_type: StrategyType = StrategyType.DIRECTIONAL,
        enable_controls: bool = True,
        caution_start: dt_time = None,
        block_after: dt_time = None,
    ):
        self._strategy_type = strategy_type
        self._enable_controls = enable_controls
        self._caution_start = caution_start or self.CAUTION_START
        self._block_after = block_after or self.BLOCK_AFTER

    def set_strategy_type(self, strategy_type: StrategyType) -> None:
        """Update strategy type."""
        self._strategy_type = strategy_type

    def can_enter_position(self, now: datetime | None = None) -> ExpiryControlResult:
        """
        Check if new position entry is allowed on expiry day.

        Returns:
            ExpiryControlResult with permission and details
        """
        if not self._enable_controls:
            return ExpiryControlResult(
                allowed=True,
                session=ExpirySession.MORNING,
                reason="Expiry controls disabled",
                risk_level="LOW",
            )

        if now is None:
            now = now_ist()

        current_time = now.time()
        warnings = []

        if current_time >= self._block_after:
            return ExpiryControlResult(
                allowed=False,
                session=ExpirySession.BLOCKED,
                reason=f"Entry blocked after {self._block_after}",
                risk_level="HIGH",
                warnings=["Expiry day entry window closed"],
            )

        if current_time >= self._caution_start:
            session = ExpirySession.CAUTION
            risk_level = self._get_caution_risk_level()
            warnings.append(f"Caution period started at {self._caution_start}")

            if self._strategy_type == StrategyType.OPTIONS_SELLING:
                warnings.append("High gamma risk for short options")
                return ExpiryControlResult(
                    allowed=False,
                    session=session,
                    reason="Options selling blocked in caution period",
                    risk_level="HIGH",
                    warnings=warnings,
                )

            if self._strategy_type == StrategyType.IRON_CONDOR:
                warnings.append("Iron condor risky in caution - consider closing")

            return ExpiryControlResult(
                allowed=True,
                session=session,
                reason="Entry allowed with caution",
                risk_level=risk_level,
                warnings=warnings,
            )

        session = ExpirySession.MORNING if current_time < dt_time(12, 0) else ExpirySession.MIDDAY
        return ExpiryControlResult(
            allowed=True,
            session=session,
            reason="Entry allowed in morning/midday",
            risk_level="LOW",
        )

    def should_close_positions(self, now: datetime | None = None) -> tuple[bool, str]:
        """Check if all positions should be closed before expiry close."""
        if now is None:
            now = now_ist()

        current_time = now.time()

        if current_time >= self.CLOSE_ALL_BY:
            return True, f"Close all positions before {self.CLOSE_ALL_BY}"

        return False, ""

    def get_closing_warning_time(self, now: datetime | None = None) -> datetime | None:
        """Get time when closing warning should be issued."""
        if now is None:
            now = now_ist()

        from datetime import timedelta
        warning_time = now.replace(
            hour=self.CLOSE_ALL_BY.hour,
            minute=self.CLOSE_ALL_BY.minute,
        ) - timedelta(minutes=30)

        return warning_time if warning_time > now else None

    def estimate_premium_decay(self, premium: float, dte: int, hours_remaining: float) -> float:
        """
        Estimate theta decay for remaining hours.

        Args:
            premium: Current option premium
            dte: Days to expiry
            hours_remaining: Hours until market close

        Returns:
            Estimated decayed premium
        """
        if dte <= 0 or hours_remaining <= 0:
            return 0.0

        daily_decay_rate = 0.07
        hourly_decay = daily_decay_rate / 6.5

        decay_factor = 1 - (hourly_decay * hours_remaining / 24)
        return max(0, premium * decay_factor)

    def _get_caution_risk_level(self) -> str:
        """Get risk level based on strategy type during caution period."""
        if self._strategy_type in (
            StrategyType.OPTIONS_SELLING,
            StrategyType.IRON_CONDOR,
            StrategyType.SPREAD,
        ):
            return "HIGH"
        elif self._strategy_type == StrategyType.STRADDLE:
            return "MEDIUM"
        return "LOW"

    def is_expiry_day(self, date: datetime | None = None) -> bool:
        """Check if given date is an expiry day (Thursday)."""
        if date is None:
            date = now_ist()
        return date.weekday() == 3

    def get_expiry_week_type(self, date: datetime | None = None) -> str:
        """Get expiry week type (monthly/weekly/normal)."""
        if date is None:
            date = now_ist()

        if date.day >= 25:
            return "MONTHLY"
        elif date.day >= 18:
            return "WEEKLY_3"
        elif date.day >= 11:
            return "WEEKLY_2"
        else:
            return "WEEKLY_1"


def create_expiry_controller(
    strategy_type: StrategyType = StrategyType.DIRECTIONAL,
    enable_controls: bool = True,
) -> ExpiryDayController:
    """Factory function to create expiry controller."""
    return ExpiryDayController(
        strategy_type=strategy_type,
        enable_controls=enable_controls,
    )
