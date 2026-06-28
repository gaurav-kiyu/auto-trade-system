"""
Self-Healing Framework — auto-recovery orchestration for the trading platform.

Provides self-healing monitoring, failure detection, and recovery action execution.
"""

from __future__ import annotations

from core.self_healing.models import (
    FailurePattern,
    HealingAction,
    HealingCycleResult,
    HealthStatus,
    RecoveryAction,
)
from core.self_healing.orchestrator import (
    SelfHealingOrchestrator,
    get_orchestrator,
)

__all__ = [
    "FailurePattern",
    "HealingAction",
    "HealingCycleResult",
    "HealthStatus",
    "RecoveryAction",
    "SelfHealingOrchestrator",
    "get_orchestrator",
]
