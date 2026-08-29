"""Constitution Alert Bridge — wires Constitution v4.0 health checks to notification service.

Automatically sends notifications when constitution health scores drop below
configurable thresholds. Integrates with the existing NotificationService
for Telegram/email alert delivery.

Usage:
    from core.constitution_alert_bridge import get_constitution_alert_bridge
    bridge = get_constitution_alert_bridge()
    bridge.check_and_alert()           # Single check cycle
    bridge.start_scheduler()           # Background monitoring thread
    bridge.stop_scheduler()            # Graceful stop
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

DEFAULT_CHECK_INTERVAL_SECONDS: int = 3600  # 1 hour
DEFAULT_HEALTH_WARN_THRESHOLD: float = 7.0
DEFAULT_HEALTH_CRIT_THRESHOLD: float = 5.0


@dataclass
class BridgeConfig:
    """Configuration for the Constitution Alert Bridge."""

    enabled: bool = True
    check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS
    health_warn_threshold: float = DEFAULT_HEALTH_WARN_THRESHOLD
    health_crit_threshold: float = DEFAULT_HEALTH_CRIT_THRESHOLD
    notify_on_warning: bool = True
    notify_on_critical: bool = True
    notify_on_recovery: bool = True
    telegram_enabled: bool = True


@dataclass
class AlertCheckResult:
    """Result of a single alert check cycle."""

    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    overall_score: float = 0.0
    previous_score: float | None = None
    score_delta: float = 0.0
    total_categories: int = 0
    open_regressions: int = 0
    health_status: str = "UNKNOWN"  # HEALTHY, WARNING, CRITICAL
    alert_sent: bool = False
    alert_message: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "overall_score": round(self.overall_score, 2),
            "previous_score": round(self.previous_score, 2) if self.previous_score is not None else None,
            "score_delta": round(self.score_delta, 2),
            "total_categories": self.total_categories,
            "open_regressions": self.open_regressions,
            "health_status": self.health_status,
            "alert_sent": self.alert_sent,
            "alert_message": self.alert_message,
            "error": self.error,
        }


class ConstitutionAlertBridge:
    """Bridges constitution health checks to notification service alerts.

    Monitors constitution health on a configurable schedule and sends
    alerts when scores drop below defined thresholds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._cfg = BridgeConfig(
            **{k: v for k, v in (config or {}).items() if k in BridgeConfig.__dataclass_fields__}
        )
        self._lock = threading.RLock()
        self._scheduler_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_result: AlertCheckResult | None = None
        self._notification_service = None

    def _get_notification_service(self):
        """Lazy-initialize the notification service."""
        if self._notification_service is None:
            try:
                from core.services.notification_service import NotificationService
                self._notification_service = NotificationService()
                self._notification_service.start()
            except ImportError:
                _log.warning("[CAB] NotificationService not available — alerts will be logged only")
                self._notification_service = False  # Sentinel: don't retry
        return self._notification_service if self._notification_service is not False else None

    def _send_alert(self, message: str, is_critical: bool) -> bool:
        """Send an alert via the notification service, with logging fallback."""
        ns = self._get_notification_service()
        if ns:
            try:
                from core.ports.notification.notification_port import (
                    Notification,
                    NotificationChannel,
                    NotificationPriority,
                )
                notif = Notification(
                    message=message,
                    channel=NotificationChannel.TELEGRAM if self._cfg.telegram_enabled else NotificationChannel.IN_APP,
                    priority=NotificationPriority.CRITICAL if is_critical else NotificationPriority.HIGH,
                    subject="[CONSTITUTION] Health Alert" if is_critical else "[CONSTITUTION] Health Warning",
                    metadata={"source": "constitution_alert_bridge", "critical": is_critical},
                )
                ns.send_notification(notif)
                return True
            except Exception as exc:
                _log.warning("[CAB] Notification send failed: %s", exc)
        # Fallback: log the alert
        level = "CRITICAL" if is_critical else "WARNING"
        _log.info("[CAB] Alert (%s): %s", level, message)
        return False

    def check_and_alert(self) -> AlertCheckResult:
        """Run a single constitution health check cycle and send alerts if needed.

        Returns:
            AlertCheckResult with full details.
        """
        start = time.time()
        result = AlertCheckResult()

        try:
            from core.constitution import get_validator
            v = get_validator()
            health = v.comprehensive_health_check()

            result.overall_score = health.get("overall_score", 0.0)
            result.total_categories = health.get("total_categories", 0)
            result.open_regressions = health.get("open_regressions", 0)

            # Detect score change from previous check
            with self._lock:
                if self._last_result is not None:
                    result.previous_score = self._last_result.overall_score
                    result.score_delta = result.overall_score - result.previous_score

            # Determine health status
            if result.overall_score >= self._cfg.health_warn_threshold:
                result.health_status = "HEALTHY"
            elif result.overall_score >= self._cfg.health_crit_threshold:
                result.health_status = "WARNING"
            else:
                result.health_status = "CRITICAL"

            # Generate alert message
            domains_health = {}
            for key, label in [
                ("enterprise_layers", "Enterprise Layers"),
                ("quality_gates", "Quality Gates"),
                ("success_metrics", "Success Metrics"),
                ("engineering_principles", "Engineering Principles"),
                ("architecture_standards", "Architecture Standards"),
                ("security_governance", "Security & Governance"),
                ("platform_engineering", "Platform Engineering"),
                ("sre_reliability", "SRE/Reliability"),
            ]:
                domain = health.get(key, {})
                domains_health[label] = domain.get("count", 0)

            # Decide whether to send alert
            send_alert = False
            is_critical = False
            alert_parts = [f"Constitution Health: {result.overall_score:.2f}/10 ({result.health_status})"]

            if result.health_status == "CRITICAL" and self._cfg.notify_on_critical:
                send_alert = True
                is_critical = True
                alert_parts.append(f"CRITICAL: Score {result.overall_score:.2f} below threshold {self._cfg.health_crit_threshold}")
            elif result.health_status == "WARNING" and self._cfg.notify_on_warning:
                send_alert = True
                is_critical = False
                alert_parts.append(f"WARNING: Score {result.overall_score:.2f} below threshold {self._cfg.health_warn_threshold}")

            # Check for recovery
            if not send_alert and self._cfg.notify_on_recovery and self._last_result is not None:
                if self._last_result.health_status in ("WARNING", "CRITICAL") and result.health_status == "HEALTHY":
                    send_alert = True
                    is_critical = False
                    alert_parts.append(f"RECOVERED to healthy state (was {self._last_result.health_status})")

            # Add domain details
            for label, count in sorted(domains_health.items()):
                if count > 0:
                    alert_parts.append(f"  {label}: {count}")

            if result.open_regressions > 0:
                alert_parts.append(f"  Open regressions: {result.open_regressions}")

            result.alert_message = "\n".join(alert_parts)

            if send_alert:
                result.alert_sent = self._send_alert(result.alert_message, is_critical)

        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            _log.error("[CAB] Check cycle failed: %s", exc)

        # Store result
        with self._lock:
            self._last_result = result

        duration = time.time() - start
        _log.info(
            "[CAB] Check complete: score=%.2f status=%s alert=%s in %.2fs",
            result.overall_score, result.health_status, result.alert_sent, duration,
        )
        return result

    def get_last_result(self) -> AlertCheckResult | None:
        """Get the last check result."""
        with self._lock:
            return self._last_result

    def get_stats(self) -> dict[str, Any]:
        """Get bridge statistics."""
        with self._lock:
            return {
                "enabled": self._cfg.enabled,
                "check_interval_seconds": self._cfg.check_interval_seconds,
                "health_warn_threshold": self._cfg.health_warn_threshold,
                "health_crit_threshold": self._cfg.health_crit_threshold,
                "scheduler_running": self._scheduler_thread is not None and self._scheduler_thread.is_alive(),
                "last_check": self._last_result.to_dict() if self._last_result else None,
            }

    def start_scheduler(self) -> bool:
        """Start the background scheduler thread."""
        with self._lock:
            if self._scheduler_thread is not None and self._scheduler_thread.is_alive():
                _log.debug("[CAB] Scheduler already running")
                return False

            self._stop_event.clear()
            self._scheduler_thread = threading.Thread(
                target=self._scheduler_loop,
                daemon=True,
                name="constitution-alert-bridge",
            )
            self._scheduler_thread.start()
            _log.info("[CAB] Scheduler started (interval=%ds)", self._cfg.check_interval_seconds)
            return True

    def stop_scheduler(self) -> None:
        """Stop the background scheduler thread gracefully."""
        self._stop_event.set()
        _log.info("[CAB] Scheduler stop requested")

    def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while not self._stop_event.is_set():
            self.check_and_alert()
            for _ in range(self._cfg.check_interval_seconds):
                if self._stop_event.is_set():
                    return
                time.sleep(1)


# ── Singleton ───────────────────────────────────────────────────────────────

_bridge: ConstitutionAlertBridge | None = None
_bridge_lock = threading.RLock()


def get_constitution_alert_bridge(config: dict[str, Any] | None = None) -> ConstitutionAlertBridge:
    """Get or create the singleton ConstitutionAlertBridge.

    Args:
        config: Optional config dict (only used on first creation).

    Returns:
        The singleton bridge instance.
    """
    global _bridge
    if _bridge is None:
        with _bridge_lock:
            if _bridge is None:
                _bridge = ConstitutionAlertBridge(config)
    return _bridge


def reset_constitution_alert_bridge() -> None:
    """Reset the singleton (for testing)."""
    global _bridge
    with _bridge_lock:
        if _bridge is not None:
            _bridge.stop_scheduler()
        _bridge = None


__all__ = [
    "AlertCheckResult",
    "BridgeConfig",
    "ConstitutionAlertBridge",
    "get_constitution_alert_bridge",
    "reset_constitution_alert_bridge",
]
