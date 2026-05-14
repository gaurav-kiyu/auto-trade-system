"""
Mandate Validation Rules - PART 5
Four gates that any new parameter must pass before live deployment
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import logging

_log = logging.getLogger(__name__)


@dataclass
class ValidationConfig:
    min_observations: int = 80
    walkforward_degradation_max: float = 0.20
    min_regimes_positive: int = 2
    min_win_rate: float = 0.48
    negative_weeks_threshold: int = 3


class ValidationResult:
    PASSED = "PASSED"
    FAILED = "FAILED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MandateValidator:
    def __init__(self, config: dict):
        self.cfg = self._load_config(config)
        self._param_history: dict[str, list] = {}

    def _load_config(self, config: dict) -> ValidationConfig:
        return ValidationConfig(
            min_observations=config.get("MANDATE_VALIDATION_MIN_OBSERVATIONS", 80),
            walkforward_degradation_max=config.get("MANDATE_WALKFORWARD_DEGRADATION_MAX", 0.20),
            min_regimes_positive=2,
            min_win_rate=config.get("MANDATE_MIN_WIN_RATE_THRESHOLD", 0.48),
            negative_weeks_threshold=config.get("MANDATE_NEGATIVE_WEEKS_THRESHOLD", 3),
        )

    def validate_parameter(
        self,
        parameter_name: str,
        observations: list[dict],
        period_a_results: Optional[dict] = None,
        period_b_results: Optional[dict] = None,
        regime_breakdown: Optional[dict[str, list]] = None,
    ) -> tuple[str, str]:
        if len(observations) < self.cfg.min_observations:
            return ValidationResult.INSUFFICIENT_DATA, (
                f"Only {len(observations)} observations, need {self.cfg.min_observations} minimum"
            )

        if period_a_results and period_b_results:
            if not self._check_walkforward(period_a_results, period_b_results):
                return ValidationResult.FAILED, "Walk-forward test failed: degraded >20%"

        if regime_breakdown:
            positive_regimes = sum(1 for trades in regime_breakdown.values() if self._is_positive(trades))
            if positive_regimes < self.cfg.min_regimes_positive:
                return ValidationResult.FAILED, f"Only {positive_regimes}/3 regimes positive"

        win_rate = self._calculate_win_rate(observations)
        if win_rate < self.cfg.min_win_rate:
            return ValidationResult.FAILED, f"Win rate {win_rate:.1%} below minimum {self.cfg.min_win_rate:.1%}"

        return ValidationResult.PASSED, "All validation gates passed"

    def _check_walkforward(self, period_a: dict, period_b: dict) -> bool:
        a_pnl = period_a.get("net_pnl", 0)
        b_pnl = period_b.get("net_pnl", 0)

        if a_pnl <= 0:
            return True

        degradation = (a_pnl - b_pnl) / a_pnl
        return degradation <= self.cfg.walkforward_degradation_max

    def _is_positive(self, observations: list) -> bool:
        if not observations:
            return False
        total_pnl = sum(o.get("pnl", 0) for o in observations)
        return total_pnl > 0

    def _calculate_win_rate(self, observations: list[dict]) -> float:
        if not observations:
            return 0.0
        wins = sum(1 for o in observations if o.get("pnl", 0) > 0)
        return wins / len(observations)

    def check_system_health(self, recent_trades: list[dict], recent_weeks_pnl: list[float]) -> tuple[bool, str]:
        if len(recent_trades) >= 50:
            win_rate = self._calculate_win_rate(recent_trades[-50:])
            if win_rate < self.cfg.min_win_rate:
                return False, f"Win rate {win_rate:.1%} below threshold"

        negative_weeks = sum(1 for pnl in recent_weeks_pnl if pnl < 0)
        if negative_weeks >= self.cfg.negative_weeks_threshold:
            return False, f"{negative_weeks} consecutive negative weeks"

        return True, "System health OK"

    def get_validation_status(self, param_name: str) -> dict:
        observations = self._param_history.get(param_name, [])
        return {
            "parameter": param_name,
            "observations": len(observations),
            "validation_status": "VALIDATED" if len(observations) >= self.cfg.min_observations else "INSUFFICIENT_DATA",
        }


def create_mandate_validator(config: dict) -> MandateValidator:
    return MandateValidator(config)