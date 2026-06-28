"""
Self-Healing Models — extracted from orchestrator.py for SRP compliance.

Contains all enums and data classes used by the self-healing framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class HealthStatus(Enum):
    """System health status levels."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    CRITICAL = "CRITICAL"


class RecoveryAction(Enum):
    """Available recovery actions the orchestrator can execute."""
    RESET_CIRCUIT_BREAKER = "reset_circuit_breaker"
    RECONNECT_BROKER = "reconnect_broker"
    RESTART_STALE_FEED = "restart_stale_feed"
    RECONNECT_DATABASE = "reconnect_database"
    RELOAD_CONFIG = "reload_config"
    CLEAR_HARD_HALT = "clear_hard_halt"
    RECYCLE_SESSION = "recycle_session"
    RESTART_WATCHDOG = "restart_watchdog"
    NOTIFY_OPERATOR = "notify_operator"
    # Auto-remediation actions
    DISK_CLEANUP = "disk_cleanup"
    FORCE_WAL_CHECKPOINT = "force_wal_checkpoint"
    CLEAR_STALE_LOCKS = "clear_stale_locks"
    RUN_RUNBOOK = "run_runbook"


@dataclass
class HealingAction:
    """Record of a single healing action execution."""

    action: RecoveryAction
    component: str
    status: str                    # "SUCCESS" | "FAILED" | "SKIPPED"
    message: str                   # Human-readable outcome
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class HealingCycleResult:
    """Result of a complete healing cycle."""

    actions_taken: list[HealingAction] = field(default_factory=list)
    n_actions: int = 0
    n_success: int = 0
    n_failed: int = 0
    n_skipped: int = 0
    overall_health: HealthStatus = HealthStatus.HEALTHY
    duration_seconds: float = 0.0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_actions": self.n_actions,
            "n_success": self.n_success,
            "n_failed": self.n_failed,
            "n_skipped": self.n_skipped,
            "overall_health": self.overall_health.value,
            "duration_seconds": round(self.duration_seconds, 2),
            "summary": self.summary,
            "actions": [{
                "action": a.action.value,
                "component": a.component,
                "status": a.status,
                "message": a.message,
                "timestamp": a.timestamp,
                "duration_ms": round(a.duration_ms, 1),
            } for a in self.actions_taken],
        }

    def format_text(self) -> str:
        """Return a human-readable summary."""
        lines = [
            f"Self-Healing Cycle: {self.summary}",
            f"  Actions: {self.n_actions} total, "
            f"{self.n_success} success, {self.n_failed} failed, {self.n_skipped} skipped",
            f"  Health: {self.overall_health.value}",
            f"  Duration: {self.duration_seconds:.1f}s",
        ]
        for a in self.actions_taken:
            icon = {"SUCCESS": "✅", "FAILED": "❌", "SKIPPED": "⏭️"}.get(a.status, "❓")
            lines.append(f"    {icon} {a.action.value} on {a.component}: {a.message}")
        return "\n".join(lines)


@dataclass
class FailurePattern:
    """Detection pattern for a known failure mode."""

    name: str
    description: str
    recovery_actions: list[RecoveryAction]
    cooldown_seconds: int = 300


__all__ = [
    "FailurePattern",
    "HealingAction",
    "HealingCycleResult",
    "HealthStatus",
    "RecoveryAction",
]
