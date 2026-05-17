"""
Idempotency Failure Alerts - CRITICAL FIX #7
Alerts when persistence fails - NO silent degradation.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


class DegradationMode(Enum):
    """Operational mode based on idempotency status"""
    NORMAL = "NORMAL"                    # All systems operational
    DEGRADED = "DEGRADED"                # Idempotency degraded, alerts sent
    FROZEN = "FROZEN"                    # Execution frozen until resolved


@dataclass
class IdempotencyAlert:
    """Alert for idempotency failure"""
    alert_type: str  # PERSISTENCE_FAILURE, CACHE_MISS, RECONCILIATION_FAILURE
    severity: str    # CRITICAL, HIGH, MEDIUM
    message: str
    timestamp: str
    affected_key: str | None = None
    recovery_action: str | None = None


class IdempotencyAlertManager:
    """
    Manages idempotency alerts and operational mode.
    NO SILENT DEGRADATION - critical alerts on failure.
    """

    def __init__(
        self,
        freeze_execution_on_critical: bool = True,
        alert_callback: Callable | None = None,
    ):
        self._freeze_on_critical = freeze_execution_on_critical
        self._alert_callback = alert_callback
        self._alerts: list[IdempotencyAlert] = []
        self._mode = DegradationMode.NORMAL
        self._critical_failures_count = 0

    def record_persistence_failure(
        self,
        idempotency_key: str,
        error: Exception,
    ) -> DegradationMode:
        """
        Record idempotency persistence failure.
        Returns new operational mode.
        """
        alert = IdempotencyAlert(
            alert_type="PERSISTENCE_FAILURE",
            severity="CRITICAL",
            message=f"Idempotency persistence failed for key {idempotency_key}: {error}",
            timestamp=time_provider.format_ts(),
            affected_key=idempotency_key,
            recovery_action="Using in-memory cache only. Risk of duplicate orders on restart.",
        )
        self._alerts.append(alert)
        self._critical_failures_count += 1
        self._mode = DegradationMode.DEGRADED

        _log.critical(alert.message)

        if self._alert_callback:
            self._alert_callback(alert)

        if self._freeze_on_critical and self._critical_failures_count >= 3:
            self._mode = DegradationMode.FROZEN
            freeze_alert = IdempotencyAlert(
                alert_type="EXECUTION_FROZEN",
                severity="CRITICAL",
                message="Execution FROZEN due to repeated idempotency failures",
                timestamp=time_provider.format_ts(),
                recovery_action="Manual intervention required. Check persistence.",
            )
            self._alerts.append(freeze_alert)
            _log.critical("EXECUTION FROZEN - Manual intervention required")

        return self._mode

    def record_cache_miss(
        self,
        idempotency_key: str,
    ) -> None:
        """Record cache miss during idempotency check"""
        alert = IdempotencyAlert(
            alert_type="CACHE_MISS",
            severity="MEDIUM",
            message=f"Idempotency cache miss for key {idempotency_key}",
            timestamp=time_provider.format_ts(),
            affected_key=idempotency_key,
            recovery_action="Checking persistence...",
        )
        self._alerts.append(alert)
        _log.warning(alert.message)

    def record_reconciliation_failure(
        self,
        details: str,
    ) -> None:
        """Record reconciliation failure"""
        alert = IdempotencyAlert(
            alert_type="RECONCILIATION_FAILURE",
            severity="HIGH",
            message=f"Idempotency reconciliation failed: {details}",
            timestamp=time_provider.format_ts(),
            recovery_action="Manual reconciliation required",
        )
        self._alerts.append(alert)
        _log.error(alert.message)

        if self._alert_callback:
            self._alert_callback(alert)

    def get_current_mode(self) -> DegradationMode:
        """Get current operational mode"""
        return self._mode

    def can_execute(self) -> tuple[bool, str]:
        """Check if execution is allowed"""
        if self._mode == DegradationMode.FROZEN:
            return False, "EXECUTION_FROZEN: Idempotency system degraded"
        if self._mode == DegradationMode.DEGRADED:
            _log.warning("Operating in DEGRADED mode - idempotency persistence failed")
        return True, "OK"

    def get_recent_alerts(self, count: int = 10) -> list[IdempotencyAlert]:
        """Get recent alerts"""
        return self._alerts[-count:]

    def reset_mode(self, reason: str = "Manual reset") -> None:
        """Reset to NORMAL mode (after issue resolved)"""
        old_mode = self._mode
        self._mode = DegradationMode.NORMAL
        self._critical_failures_count = 0

        reset_alert = IdempotencyAlert(
            alert_type="MODE_RESET",
            severity="HIGH",
            message=f"Mode reset from {old_mode.value} to NORMAL: {reason}",
            timestamp=time_provider.format_ts(),
            recovery_action="Execution allowed",
        )
        self._alerts.append(reset_alert)
        _log.info(f"Idempotency mode reset: {reason}")


# Singleton
_alert_manager: IdempotencyAlertManager | None = None


def get_idempotency_alert_manager(
    freeze_on_critical: bool = True,
    alert_callback: Callable | None = None,
) -> IdempotencyAlertManager:
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = IdempotencyAlertManager(freeze_on_critical, alert_callback)
    return _alert_manager
