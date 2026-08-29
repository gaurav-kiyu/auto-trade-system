"""Layer 5: Risk & Veto Engine with Reason Codes (v6.0 Production).

Evaluates:
- Hard Risk Veto overriding model to NO_TRADE
- Versioned decision gates (Min Probability, Min EV, Min R:R)
- Granular Reason Codes
"""

from __future__ import annotations

from dataclasses import dataclass

from core.logging import get_logger
from core.quant.meta_classifier import MetaEvaluationResult
from core.quant.preguard_data_quality import PreGuardResult

_log = get_logger("QUANT_RISK_VETO")


@dataclass
class RiskVetoResult:
    vetoed: bool  # True if risk vetoes the trade
    final_decision: str  # BUY, SELL, NO_TRADE
    final_reason_code: str  # SUCCESS_PASS, REGIME_TRANSITIONAL_UNCERTAIN, EXPECTED_VALUE_NEGATIVE, etc.
    risk_reasons: list[str]


class RiskVetoEngine:
    """Layer 5 Hard Risk Veto & Decision Arbiter."""

    def __init__(
        self,
        min_probability_threshold: float = 0.75,
        min_expected_value_threshold: float = 0.15,
        min_net_rr_t1: float = 1.0,
        daily_loss_limit_reached: bool = False,
    ) -> None:
        self.min_probability = min_probability_threshold
        self.min_ev = min_expected_value_threshold
        self.min_net_rr_t1 = min_net_rr_t1
        self.daily_loss_limit_reached = daily_loss_limit_reached

    def arbitrate(
        self,
        preguard_res: PreGuardResult,
        regime_str: str,
        meta_res: MetaEvaluationResult,
    ) -> RiskVetoResult:
        """Arbitrate between Layer 0 Pre-Guard, Layer 1 Regime, Layer 4 Meta Model, and Risk Constraints."""

        # 1. Pre-Guard Hard Veto
        if not preguard_res.passed:
            return RiskVetoResult(
                vetoed=True,
                final_decision="NO_TRADE",
                final_reason_code=preguard_res.status_code,
                risk_reasons=[f"Pre-Guard Failed: {preguard_res.details.get('error', 'Unknown')}"],
            )

        # 2. Portfolio Daily Drawdown Hard Limit
        if self.daily_loss_limit_reached:
            return RiskVetoResult(
                vetoed=True,
                final_decision="NO_TRADE",
                final_reason_code="PORTFOLIO_DAILY_DRAWDOWN_LIMIT",
                risk_reasons=["Daily portfolio loss budget cap reached."],
            )

        # 3. Regime Transitional Veto
        if regime_str == "TRANSITIONAL_UNCERTAIN":
            return RiskVetoResult(
                vetoed=True,
                final_decision="NO_TRADE",
                final_reason_code="REGIME_TRANSITIONAL_UNCERTAIN",
                risk_reasons=["Market is in transitional/uncertain regime. Actionable edge is insufficient."],
            )

        # 4. Model Decision NO_TRADE Check
        if meta_res.direction == "NO_TRADE":
            return RiskVetoResult(
                vetoed=True,
                final_decision="NO_TRADE",
                final_reason_code="PROBABILITY_BELOW_THRESHOLD",
                risk_reasons=[f"Directional probability ({meta_res.directional_prob.p_buy*100:.1f}%) below threshold {self.min_probability*100:.1f}%"],
            )

        # 5. Expected Value Threshold Gate
        if meta_res.expected_value < self.min_ev:
            return RiskVetoResult(
                vetoed=True,
                final_decision="NO_TRADE",
                final_reason_code="EXPECTED_VALUE_BELOW_MINIMUM",
                risk_reasons=[f"Expected Value (+{meta_res.expected_value:.2f}R) below minimum threshold (+{self.min_ev:.2f}R)"],
            )

        # 6. Minimum Net R:R Check
        if meta_res.net_rr_t1 < self.min_net_rr_t1:
            return RiskVetoResult(
                vetoed=True,
                final_decision="NO_TRADE",
                final_reason_code="NET_RR_BELOW_MINIMUM",
                risk_reasons=[f"Net R:R to T1 ({meta_res.net_rr_t1:.2f}R) below minimum required ({self.min_net_rr_t1:.2f}R)"],
            )

        # All Gates Passed
        return RiskVetoResult(
            vetoed=False,
            final_decision=meta_res.direction,
            final_reason_code="SUCCESS_PASS",
            risk_reasons=["All 6 Layer Invariant Gates Passed."],
        )
