from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "SafetyConfig",
    "SafetyContext",
    "SafetyDecision",
    "SafetyEngine",
]

@dataclass(frozen=True)
class SafetyConfig:
    max_api_failures: int = 5
    max_consecutive_losses: int = 3
    max_reconciliation_mismatches: int = 1
    max_slippage_pct: float = 0.02
    max_stale_data_sec: int = 180
    require_healthy_data: bool = True


@dataclass(frozen=True)
class SafetyContext:
    api_failures: int = 0
    consecutive_losses: int = 0
    reconciliation_mismatches: int = 0
    slippage_pct: float = 0.0
    stale_data_sec: int = 0
    data_healthy: bool = True


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason: str = ""


class SafetyEngine:
    """Central circuit-breaker style safety checks."""

    def __init__(self, config: SafetyConfig) -> None:
        self.config = config

    def evaluate(self, ctx: SafetyContext) -> SafetyDecision:
        if self.config.require_healthy_data and not ctx.data_healthy:
            return SafetyDecision(False, "market data is unhealthy")
        if ctx.api_failures >= self.config.max_api_failures:
            return SafetyDecision(False, f"api failures {ctx.api_failures} >= {self.config.max_api_failures}")
        if ctx.consecutive_losses >= self.config.max_consecutive_losses:
            return SafetyDecision(False, f"loss streak {ctx.consecutive_losses} >= {self.config.max_consecutive_losses}")
        if ctx.reconciliation_mismatches >= self.config.max_reconciliation_mismatches:
            return SafetyDecision(False, f"reconciliation mismatches {ctx.reconciliation_mismatches} >= {self.config.max_reconciliation_mismatches}")
        if ctx.slippage_pct > self.config.max_slippage_pct:
            return SafetyDecision(False, f"slippage {ctx.slippage_pct:.2%} > {self.config.max_slippage_pct:.2%}")
        if ctx.stale_data_sec > self.config.max_stale_data_sec:
            return SafetyDecision(False, f"stale data {ctx.stale_data_sec}s > {self.config.max_stale_data_sec}s")
        return SafetyDecision(True, "")
