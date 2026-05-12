"""
Risk Limits Manager.

Handles daily loss limits, consecutive loss protection, and portfolio-level constraints.
"""

from __future__ import annotations
from typing import Any, Dict, Optional
from dataclasses import dataclass
from core.safety_state import trip_hard_halt
from core.common.kernels.models import RiskDecision, RiskEvaluation

@dataclass
class LimitConfig:
    max_daily_loss: float = -2000.0
    max_daily_trades: int = 10
    max_open_positions: int = 5
    max_portfolio_risk: float = 0.25
    max_consecutive_losses: int = 3

class RiskLimitsManager:
    def __init__(self, config: LimitConfig):
        self.config = config

    def check_daily_loss(self, daily_pnl: float) -> RiskEvaluation:
        if daily_pnl <= self.config.max_daily_loss:
            trip_hard_halt(
                f"Daily loss limit breached: {daily_pnl} <= {self.config.max_daily_loss}",
                source="RiskLimitsManager.check_daily_loss",
            )
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason=f"Daily loss limit reached: {daily_pnl:.2f} <= {self.config.max_daily_loss:.2f}",
                risk_score=1.0
            )
        return RiskEvaluation(decision=RiskDecision.ALLOWED, reason="Daily loss limit check passed", risk_score=0.0)

    def check_consecutive_losses(self, consecutive_losses: int) -> RiskEvaluation:
        if consecutive_losses >= self.config.max_consecutive_losses:
            trip_hard_halt(
                f"Consecutive loss limit breached: {consecutive_losses} >= {self.config.max_consecutive_losses}",
                source="RiskLimitsManager.check_consecutive_losses",
            )
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason=f"Consecutive loss limit reached: {consecutive_losses} >= {self.config.max_consecutive_losses}",
                risk_score=1.0
            )
        return RiskEvaluation(decision=RiskDecision.ALLOWED, reason="Consecutive loss limit check passed", risk_score=0.0)

    def check_portfolio_limits(self, open_positions_count: int, current_risk: float) -> RiskEvaluation:
        if open_positions_count >= self.config.max_open_positions:
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason=f"Maximum open positions reached: {open_positions_count} >= {self.config.max_open_positions}",
                risk_score=0.8
            )

        if current_risk > self.config.max_portfolio_risk:
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason=f"Portfolio risk limit reached: {current_risk:.2%} > {self.config.max_portfolio_risk:.2%}",
                risk_score=0.9
            )
        return RiskEvaluation(decision=RiskDecision.ALLOWED, reason="Portfolio limits check passed", risk_score=0.1)
