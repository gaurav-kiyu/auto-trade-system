"""
STT Cost Model (Phase 2).

Securities Transaction Tax (STT) modeling for Indian options.
Critical for short options held to expiry where STT can exceed premium.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)


class OptionPositionType(str, Enum):
    LONG_CALL = "LONG_CALL"
    LONG_PUT = "LONG_PUT"
    SHORT_CALL = "SHORT_CALL"
    SHORT_PUT = "SHORT_PUT"


class OptionStyle(str, Enum):
    EUROPEAN = "EUROPEAN"
    AMERICAN = "AMERICAN"


@dataclass
class STTCostBreakdown:
    """STT cost breakdown for an options trade."""
    stt_rate: float
    premium_value: float
    stt_amount: float
    is_expiry_stt: bool
    is_settled: bool


class STTCostModel:
    """
    STT Cost Model for NSE Options.

    STT Rates (as of 2026):
    - Long options (buy): 0% (NSE charges STT only on sell/exercise)
    - Short options (sell): 0.05% of premium (0.0005)
    - Options exercised (settlement): 0.125% of settlement value

    CRITICAL: Short options held to expiry face expiry STT which can
    exceed the premium received if the option is deep ITM.

    NOTE: STT_SHORT_OPTIONS_PCT = 0.0005 (0.05%) — this is the actual NSE rate.
    The audit finding (Finding #5) confirmed the rate was 0.0005, not 0.1%.
    """

    STT_LONG_OPTIONS_PCT = 0.0
    STT_SHORT_OPTIONS_PCT = 0.0005
    STT_EXERCISE_PCT = 0.00125

    def __init__(
        self,
        include_stt: bool = True,
        apply_expiry_stt: bool = True,
    ):
        self._include_stt = include_stt
        self._apply_expiry_stt = apply_expiry_stt

    def calculate_stt(
        self,
        position_type: OptionPositionType,
        premium: float,
        strike_price: float,
        quantity: int,
        lot_size: int,
        is_expiry: bool = False,
        exercised: bool = False,
    ) -> STTCostBreakdown:
        """
        Calculate STT cost for options trade.

        Args:
            position_type: LONG or CALL/PUT
            premium: Premium per option
            strike_price: Strike price
            quantity: Number of lots
            lot_size: Contract size per lot
            is_expiry: True if position held to expiry
            exercised: True if option exercised/assigned

        Returns:
            STTCostBreakdown with cost details
        """
        if not self._include_stt:
            return STTCostBreakdown(
                stt_rate=0.0,
                premium_value=0.0,
                stt_amount=0.0,
                is_expiry_stt=False,
                is_settled=False,
            )

        total_premium = premium * quantity * lot_size

        if exercised:
            settlement_value = strike_price * quantity * lot_size
            stt_rate = self.STT_EXERCISE_PCT
            stt_amount = settlement_value * stt_rate
            log.info(f"STT exercise: {stt_amount:.2f} (rate: {stt_rate*100:.3f}%)")
            return STTCostBreakdown(
                stt_rate=stt_rate,
                premium_value=total_premium,
                stt_amount=stt_amount,
                is_expiry_stt=True,
                is_settled=True,
            )

        if is_expiry and self._apply_expiry_stt:
            settlement_value = strike_price * quantity * lot_size
            stt_rate = self.STT_EXERCISE_PCT
            stt_amount = settlement_value * stt_rate
            log.warning(
                f"EXPIRY STT WARNING: {stt_amount:.2f} vs premium {total_premium:.2f} "
                f"(STT is {stt_amount/total_premium*100:.1f}% of premium)"
            )
            return STTCostBreakdown(
                stt_rate=stt_rate,
                premium_value=total_premium,
                stt_amount=stt_amount,
                is_expiry_stt=True,
                is_settled=True,
            )

        if position_type in (OptionPositionType.SHORT_CALL, OptionPositionType.SHORT_PUT):
            stt_rate = self.STT_SHORT_OPTIONS_PCT
            stt_amount = total_premium * stt_rate
        else:
            stt_rate = self.STT_LONG_OPTIONS_PCT
            stt_amount = total_premium * stt_rate

        return STTCostBreakdown(
            stt_rate=stt_rate,
            premium_value=total_premium,
            stt_amount=stt_amount,
            is_expiry_stt=False,
            is_settled=False,
        )

    def estimate_expiry_stt_risk(
        self,
        position_type: OptionPositionType,
        premium_received: float,
        strike_price: float,
        underlying_price: float,
        lot_size: int,
    ) -> dict[str, any]:
        """
        Estimate STT risk if position held to expiry.

        Returns:
            dict with risk analysis
        """
        if position_type not in (OptionPositionType.SHORT_CALL, OptionPositionType.SHORT_PUT):
            return {
                "risk_level": "NONE",
                "reason": "Long positions don't face expiry STT",
                "stt_if_exercised": 0.0,
            }

        settlement_value = strike_price * lot_size
        expiry_stt = settlement_value * self.STT_EXERCISE_PCT

        if position_type == OptionPositionType.SHORT_CALL:
            if underlying_price > strike_price:
                (underlying_price - strike_price) * lot_size
                risk_ratio = expiry_stt / max(premium_received, 1)
                return {
                    "risk_level": "HIGH" if risk_ratio > 0.5 else "MEDIUM",
                    "reason": f"Short call ITM by {underlying_price - strike_price}",
                    "stt_if_exercised": expiry_stt,
                    "premium_received": premium_received,
                    "stt_as_pct_of_premium": risk_ratio * 100,
                }
            return {
                "risk_level": "LOW",
                "reason": "Short call OTM - unlikely to be exercised",
                "stt_if_exercised": expiry_stt,
            }

        if position_type == OptionPositionType.SHORT_PUT:
            if underlying_price < strike_price:
                (strike_price - underlying_price) * lot_size
                risk_ratio = expiry_stt / max(premium_received, 1)
                return {
                    "risk_level": "HIGH" if risk_ratio > 0.5 else "MEDIUM",
                    "reason": f"Short put ITM by {strike_price - underlying_price}",
                    "stt_if_exercised": expiry_stt,
                    "premium_received": premium_received,
                    "stt_as_pct_of_premium": risk_ratio * 100,
                }
            return {
                "risk_level": "LOW",
                "reason": "Short put OTM - unlikely to be exercised",
                "stt_if_exercised": expiry_stt,
            }

        return {"risk_level": "UNKNOWN"}

    def should_close_before_expiry(
        self,
        position_type: OptionPositionType,
        premium_received: float,
        strike_price: float,
        underlying_price: float,
        lot_size: int,
        exit_cost: float,
    ) -> tuple[bool, str]:
        """
        Determine if position should be closed before expiry.

        Compares:
        - STT cost if held to expiry
        - Exit transaction cost
        """
        if position_type not in (OptionPositionType.SHORT_CALL, OptionPositionType.SHORT_PUT):
            return False, "Long position - no expiry STT risk"

        risk = self.estimate_expiry_stt_risk(
            position_type, premium_received, strike_price, underlying_price, lot_size
        )

        if risk.get("risk_level") == "HIGH" and premium_received > 0:
            risk_pct = risk.get("stt_as_pct_of_premium", 0)
            if risk_pct > exit_cost * 100 / premium_received:
                return True, f"Close to avoid {risk_pct:.1f}% STT vs {exit_cost:.1f}% exit cost"

        return False, ""


def create_stt_model(
    include_stt: bool = True,
    apply_expiry_stt: bool = True,
) -> STTCostModel:
    """Factory function to create STT model."""
    return STTCostModel(
        include_stt=include_stt,
        apply_expiry_stt=apply_expiry_stt,
    )
