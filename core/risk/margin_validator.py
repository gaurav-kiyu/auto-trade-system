"""
Margin Validator - CRITICAL FIX #2
Fixed to validate using ACTUAL intended quantity, not test quantity.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple
import logging

_log = logging.getLogger(__name__)


@dataclass
class MarginValidationResult:
    """Result of margin validation"""
    allowed: bool
    required_margin: float
    available_margin: float
    post_trade_buffer: float
    safety_reserve: float
    error_message: Optional[str] = None
    warning_message: Optional[str] = None


class MarginValidator:
    """
    Validates margin requirements using ACTUAL intended quantity.
    FIXED: Was using test quantity before, now uses actual trade quantity.
    """

    def __init__(
        self,
        config: dict = None,
    ):
        self._config = config or {}
        self._safety_reserve_pct = self._config.get("MARGIN_SAFETY_RESERVE_PCT", 0.05)
        self._warn_margin_pct = self._config.get("MARGIN_WARNING_PCT", 0.80)

    def validate(
        self,
        available_margin: float,
        required_margin_per_lot: float,
        intended_quantity: int,  # FIXED: Now uses actual intended quantity
        price_per_lot: float,
        instrument_name: str = "UNKNOWN",
    ) -> MarginValidationResult:
        """
        Validate margin using actual intended quantity.

        Args:
            available_margin: Current available margin in account
            required_margin_per_lot: Margin required per lot (from risk engine)
            intended_quantity: ACTUAL number of lots to trade (NOT test quantity!)
            price_per_lot: Price per lot for the instrument
            instrument_name: For logging

        Returns:
            MarginValidationResult with allow/reject decision
        """
        if intended_quantity <= 0:
            return MarginValidationResult(
                allowed=False,
                required_margin=0,
                available_margin=available_margin,
                post_trade_buffer=0,
                safety_reserve=0,
                error_message="Invalid quantity: must be positive",
            )

        # Calculate actual required margin using INTENDED quantity
        actual_required_margin = required_margin_per_lot * intended_quantity

        # Calculate post-trade buffer
        post_trade_margin = available_margin - actual_required_margin

        # Calculate safety reserve (5% of available margin by default)
        safety_reserve = available_margin * self._safety_reserve_pct

        # Check if margin is sufficient with safety reserve
        if post_trade_margin < safety_reserve:
            return MarginValidationResult(
                allowed=False,
                required_margin=actual_required_margin,
                available_margin=available_margin,
                post_trade_buffer=post_trade_margin,
                safety_reserve=safety_reserve,
                error_message=(
                    f"MARGIN INSUFFICIENT for {instrument_name}: "
                    f"Need {actual_required_margin:.2f}, "
                    f"Have {available_margin:.2f}, "
                    f"Post-trade buffer {post_trade_margin:.2f} below safety reserve {safety_reserve:.2f}"
                ),
            )

        # Warning if using >80% of available margin
        margin_usage_pct = actual_required_margin / available_margin if available_margin > 0 else 0
        warning = None
        if margin_usage_pct > self._warn_margin_pct:
            warning = (
                f"MARGIN WARNING for {instrument_name}: "
                f"Using {margin_usage_pct:.1%} of available margin "
                f"({actual_required_margin:.2f} of {available_margin:.2f})"
            )
            _log.warning(warning)

        return MarginValidationResult(
            allowed=True,
            required_margin=actual_required_margin,
            available_margin=available_margin,
            post_trade_buffer=post_trade_margin,
            safety_reserve=safety_reserve,
            warning_message=warning,
        )

    def validate_with_position(
        self,
        available_margin: float,
        existing_position_margin: float,
        additional_margin_per_lot: float,
        additional_quantity: int,
        price_per_lot: float,
        instrument_name: str = "UNKNOWN",
    ) -> MarginValidationResult:
        """
        Validate margin for adding to existing position.
        Considers both existing and new positions.
        """
        # Total required margin = existing + additional
        total_required_margin = existing_position_margin + (additional_margin_per_lot * additional_quantity)

        post_trade_margin = available_margin - total_required_margin
        safety_reserve = available_margin * self._safety_reserve_pct

        if post_trade_margin < safety_reserve:
            return MarginValidationResult(
                allowed=False,
                required_margin=total_required_margin,
                available_margin=available_margin,
                post_trade_buffer=post_trade_margin,
                safety_reserve=safety_reserve,
                error_message=(
                    f"MARGIN INSUFFICIENT for {instrument_name} (with existing position): "
                    f"Need {total_required_margin:.2f}, "
                    f"Have {available_margin:.2f}"
                ),
            )

        # Warning for high usage
        margin_usage_pct = total_required_margin / available_margin if available_margin > 0 else 0
        warning = None
        if margin_usage_pct > self._warn_margin_pct:
            warning = f"MARGIN WARNING: Using {margin_usage_pct:.1%} of available margin"
            _log.warning(warning)

        return MarginValidationResult(
            allowed=True,
            required_margin=total_required_margin,
            available_margin=available_margin,
            post_trade_buffer=post_trade_margin,
            safety_reserve=safety_reserve,
            warning_message=warning,
        )


# Singleton
_margin_validator: Optional[MarginValidator] = None


def get_margin_validator(config: dict = None) -> MarginValidator:
    global _margin_validator
    if _margin_validator is None:
        _margin_validator = MarginValidator(config)
    return _margin_validator