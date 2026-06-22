"""
Incident Alerting System - Structured alerts for critical events

Sends Telegram alerts for:
- broker_disconnect
- reconciliation_mismatch
- stale_quotes
- retry_storm
- risk_breach
- circuit_breaker
- orphan_order
- db_failure

Uses priority queue (CRITICAL < HIGH < NORMAL < LOW) to avoid spam.
Integrates with existing notification service.
"""
from __future__ import annotations

import heapq
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger("incident_alerting")


class IncidentType(Enum):
    """Types of incidents that trigger alerts."""
    BROKER_DISCONNECT = "broker_disconnect"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    STALE_QUOTE = "stale_quote"
    RETRY_STORM = "retry_storm"
    RISK_BREACH = "risk_breach"
    CIRCUIT_BREAKER = "circuit_breaker"
    ORPHAN_ORDER = "orphan_order"
    DB_FAILURE = "db_failure"
    HARD_HALT = "hard_halt"
    SYSTEM_MODE_CHANGE = "system_mode_change"
    UNKNOWN_STATE = "unknown_state"
    ORDER_MODIFICATION_FAILED = "order_modification_failed"


class IncidentSeverity(Enum):
    """Incident severity levels."""
    CRITICAL = 0  # Highest priority
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass(order=True)
class Incident:
    """Incident record for priority queue."""
    severity: int
    timestamp: float = field(compare=False)
    incident_type: str = field(compare=False)
    message: str = field(compare=False)
    details: dict[str, Any] = field(default_factory=dict, compare=False)
    acknowledged: bool = field(default=False, compare=False)


class IncidentAlerting:
    """
    Thread-safe incident alerting system with priority queue.
    Sends alerts via callback (typically Telegram notification).

    Severity-based channel routing (NEW):
      - CRITICAL: sent via primary alert channel (Telegram + optional secondary)
      - HIGH:     sent via primary alert channel with cooldown
      - NORMAL:   logged only (no notification) unless escalated
      - LOW:      suppressed entirely unless explicitly requested

    This reduces alert fatigue by filtering lower-severity incidents
    from noisy notification channels while still tracking them in the queue.
    """

    def __init__(
        self,
        send_alert_fn: Callable[[str, bool], None] | None = None,
        config: dict | None = None
    ):
        self._config = config or {}
        self._send_alert = send_alert_fn
        self._lock = threading.RLock()
        self._queue: list[Incident] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Configuration
        self._enabled = self._config.get("INCIDENT_ALERTING_ENABLED", True)
        self._dequeue_interval = self._config.get("INCIDENT_DEQUEUE_INTERVAL_SEC", 5)
        self._max_queue_size = self._config.get("INCIDENT_MAX_QUEUE_SIZE", 100)

        # Cooldown to prevent alert storms
        self._cooldown_seconds = self._config.get("INCIDENT_COOLDOWN_SECONDS", 60)
        self._last_alert_time: dict[IncidentType, float] = {}

        # Severity-based channel routing (new — reduces alert fatigue)
        # Define which severity levels get delivered via callback vs logged only
        threshold_name = self._config.get("INCIDENT_DELIVERY_THRESHOLD", "HIGH").upper()
        self._delivery_threshold = IncidentSeverity[threshold_name]
        # Only severities at or above this threshold are actually sent
        # CRITICAL=0, HIGH=1 are sent; NORMAL=2, LOW=3 are logged only

    def start(self) -> None:
        """Start the incident processing thread."""
        if not self._enabled:
            log.info("Incident alerting disabled by config")
            return

        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="IncidentAlerts")
        self._thread.start()
        log.info("Incident alerting started")

    def stop(self) -> None:
        """Stop the incident processing thread."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def report_incident(
        self,
        incident_type: IncidentType,
        severity: IncidentSeverity,
        message: str,
        details: dict[str, Any] | None = None
    ) -> None:
        """
        Report an incident to the queue.
        Thread-safe.
        """
        if not self._enabled:
            return

        # Check cooldown
        if self._is_in_cooldown(incident_type):
            log.debug(f"Incident {incident_type.value} in cooldown, skipping")
            return

        with self._lock:
            # Check queue size
            if len(self._queue) >= self._max_queue_size:
                log.warning(f"Incident queue full ({self._max_queue_size}), dropping incident")
                return

            # Add to priority queue
            incident = Incident(
                severity=severity.value,
                timestamp=time.time(),
                incident_type=incident_type.value,
                message=message,
                details=details or {}
            )
            heapq.heappush(self._queue, incident)

            # Update cooldown
            self._last_alert_time[incident_type] = time.time()

            log.info(f"Incident queued: {incident_type.value} [{severity.name}] - {message}")

    def _is_in_cooldown(self, incident_type: IncidentType) -> bool:
        """Check if incident type is in cooldown period."""
        last_time = self._last_alert_time.get(incident_type, 0)
        return (time.time() - last_time) < self._cooldown_seconds

    def _run_loop(self) -> None:
        """Main incident processing loop."""
        while self._running:
            try:
                self._process_incidents()
            except Exception as e:
                log.error(f"Incident processing error: {e} (type: {type(e).__name__})")

            if self._stop_event.wait(self._dequeue_interval):
                break

    def _should_deliver(self, severity_value: int) -> bool:
        """Determine if an incident of this severity should be delivered.

        Only incidents at or above the delivery threshold are sent via
        the callback channel. Lower-severity incidents are tracked in
        the queue but not delivered, reducing notification noise.

        Args:
            severity_value: IncidentSeverity.value (0=CRITICAL, 3=LOW).

        Returns:
            True if the incident should be delivered to the notification channel.
        """
        return severity_value <= self._delivery_threshold.value

    def _process_incidents(self) -> None:
        """Process queued incidents in priority order.

        Respects severity-based delivery threshold:
        - Incidents at or above threshold: sent via callback
        - Incidents below threshold: tracked in queue but not sent
        """
        while True:
            incident = None

            with self._lock:
                if not self._queue:
                    break
                incident = heapq.heappop(self._queue)

            if incident is None:
                break

            # Check delivery threshold — skip low-severity notifications
            if not self._should_deliver(incident.severity):
                log.debug(
                    "[ALERT-FILTER] Suppressed %s (severity=%d, threshold=%d): %s",
                    incident.incident_type,
                    incident.severity,
                    self._delivery_threshold.value,
                    incident.message[:100],
                )
                continue

            # Send alert via callback
            if self._send_alert:
                try:
                    # Format message
                    formatted = self._format_alert(incident)
                    is_critical = incident.severity <= IncidentSeverity.HIGH.value
                    self._send_alert(formatted, is_critical)
                except Exception as exc:
                    log.error("Failed to send incident alert: %s (type=%s)", exc, type(exc).__name__)

    def _format_alert(self, incident: Incident) -> str:
        """Format incident as alert message."""
        severity_icon = {
            0: "🚨",  # CRITICAL
            1: "⚠️",   # HIGH
            2: "ℹ️",   # NORMAL
            3: "•",   # LOW
        }.get(incident.severity, "?")

        msg = f"{severity_icon} {incident.incident_type.upper()}: {incident.message}"

        if incident.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in incident.details.items() if v)
            if detail_str:
                msg += f"\n  Details: {detail_str}"

        return msg

    def get_queue_size(self) -> int:
        """Get current queue size."""
        with self._lock:
            return len(self._queue)

    def clear_queue(self) -> None:
        """Clear all pending incidents."""
        with self._lock:
            self._queue.clear()

    # Convenience methods for common incidents

    def alert_broker_disconnect(self, details: dict | None = None) -> None:
        """Alert: Broker disconnected."""
        self.report_incident(
            IncidentType.BROKER_DISCONNECT,
            IncidentSeverity.CRITICAL,
            "Broker connection lost",
            details
        )

    def alert_reconciliation_mismatch(self, details: dict | None = None) -> None:
        """Alert: Reconciliation mismatch detected."""
        self.report_incident(
            IncidentType.RECONCILIATION_MISMATCH,
            IncidentSeverity.HIGH,
            "Broker truth mismatch",
            details
        )

    def alert_stale_quote(self, symbol: str, age_seconds: float) -> None:
        """Alert: Stale quote detected."""
        self.report_incident(
            IncidentType.STALE_QUOTE,
            IncidentSeverity.NORMAL,
            f"Stale quote for {symbol}",
            {"symbol": symbol, "age_seconds": age_seconds}
        )

    def alert_risk_breach(self, breach_type: str, details: dict | None = None) -> None:
        """Alert: Risk breach."""
        self.report_incident(
            IncidentType.RISK_BREACH,
            IncidentSeverity.CRITICAL,
            f"Risk breach: {breach_type}",
            details
        )

    def alert_hard_halt(self, reason: str) -> None:
        """Alert: Hard halt triggered."""
        self.report_incident(
            IncidentType.HARD_HALT,
            IncidentSeverity.CRITICAL,
            f"HARD HALT: {reason}",
            {}
        )

    def alert_orphan_order(self, order_id: str) -> None:
        """Alert: Orphan order detected."""
        self.report_incident(
            IncidentType.ORPHAN_ORDER,
            IncidentSeverity.HIGH,
            f"Orphan order: {order_id}",
            {"order_id": order_id}
        )

    def alert_system_mode_change(self, old_mode: str, new_mode: str, reason: str) -> None:
        """Alert: System mode changed."""
        self.report_incident(
            IncidentType.SYSTEM_MODE_CHANGE,
            IncidentSeverity.HIGH,
            f"Mode: {old_mode} → {new_mode}",
            {"old_mode": old_mode, "new_mode": new_mode, "reason": reason}
        )

    def alert_order_modification_failed(
        self,
        order_id: str,
        reason: str,
        details: dict | None = None,
    ) -> None:
        """Alert: Order modification failed.

        Triggered when an order modification attempt is rejected by the broker
        or fails due to timeout/error. Includes order ID and failure details
        so operators can investigate and manually intervene if needed.
        """
        self.report_incident(
            IncidentType.ORDER_MODIFICATION_FAILED,
            IncidentSeverity.HIGH,
            f"Modify failed: {order_id} - {reason}",
            details or {},
        )


# Singleton
_incident_alerting: IncidentAlerting | None = None


def get_incident_alerting(
    send_alert_fn: Callable | None = None,
    config: dict | None = None
) -> IncidentAlerting:
    """Get or create singleton incident alerting."""
    global _incident_alerting
    if _incident_alerting is None:
        _incident_alerting = IncidentAlerting(send_alert_fn, config)
    return _incident_alerting


def alert_broker_disconnect(details: dict | None = None) -> None:
    """Quick access to alert broker disconnect."""
    if _incident_alerting:
        _incident_alerting.alert_broker_disconnect(details)


def alert_risk_breach(breach_type: str, details: dict | None = None) -> None:
    """Quick access to alert risk breach."""
    if _incident_alerting:
        _incident_alerting.alert_risk_breach(breach_type, details)
