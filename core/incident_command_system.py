"""Enterprise Incident Command System — Automated incident detection and management.

Monitors all constitution modules and system components, automatically
creates incidents when thresholds are breached, assigns severity levels,
tracks the incident lifecycle, and integrates with the notification system.

Features:
- Automatic incident detection from module health checks
- Severity classification (CRITICAL, HIGH, MEDIUM, LOW)
- Incident lifecycle (DETECTED → INVESTIGATING → RESOLVED → CLOSED)
- Auto-resolution when system recovers
- Deduplication (same module+type won't create duplicate open incidents)
- SLA tracking (time-to-acknowledge, time-to-resolve)
- Dashboard API for incident management
- Notification integration via alert callback

Usage:
    from core.incident_command_system import get_incident_commander

    commander = get_incident_commander()
    commander.run_detection_cycle()  # Check all modules for incidents
    incidents = commander.get_open_incidents()
    commander.acknowledge_incident("INC-001")
    commander.resolve_incident("INC-001", "Fixed via config reload")

Design:
- Thread-safe singleton with RLock
- JSON persistence for incident history
- Integration with Continuous Intelligence Pipeline
- Notification callbacks for critical/high incidents
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

INCIDENTS_FILE: str = "json/incidents.json"
MAX_INCIDENTS: int = 1000
SLA_ACKNOWLEDGE_MINUTES: int = 15
SLA_RESOLVE_MINUTES: int = 120


# ── Enums ────────────────────────────────────────────────────────────────────


class IncidentSeverity(str, Enum):
    """Severity levels for incidents."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IncidentStatus(str, Enum):
    """Lifecycle states for incidents."""

    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class Incident:
    """A single incident record."""

    incident_id: str
    title: str
    description: str
    source: str  # Module or component that detected it
    severity: IncidentSeverity
    status: IncidentStatus = IncidentStatus.DETECTED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    acknowledged_at: str | None = None
    resolved_at: str | None = None
    closed_at: str | None = None
    resolution_notes: str = ""
    detected_by: str = ""  # e.g., "pipeline", "health_check", "manual"
    affected_modules: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    scorecard_pct_at_detection: float = 0.0
    sla_acknowledge_minutes: int = SLA_ACKNOWLEDGE_MINUTES
    sla_resolve_minutes: int = SLA_RESOLVE_MINUTES

    def __post_init__(self) -> None:
        """Convert string values to enums after construction (e.g., from JSON deserialization)."""
        if isinstance(self.severity, str):
            self.severity = IncidentSeverity(self.severity)
        if isinstance(self.status, str):
            self.status = IncidentStatus(self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "severity": self.severity.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "acknowledged_at": self.acknowledged_at,
            "resolved_at": self.resolved_at,
            "closed_at": self.closed_at,
            "resolution_notes": self.resolution_notes,
            "detected_by": self.detected_by,
            "affected_modules": self.affected_modules,
            "tags": self.tags,
            "scorecard_pct_at_detection": self.scorecard_pct_at_detection,
            "sla_acknowledge_minutes": self.sla_acknowledge_minutes,
            "sla_resolve_minutes": self.sla_resolve_minutes,
        }

    @property
    def is_open(self) -> bool:
        """Check if incident is still active (not resolved or closed)."""
        return self.status in (IncidentStatus.DETECTED, IncidentStatus.INVESTIGATING)

    @property
    def minutes_since_creation(self) -> float:
        """Minutes since the incident was created."""
        try:
            created = datetime.fromisoformat(self.created_at)
            now = datetime.now(timezone.utc)
            return (now - created).total_seconds() / 60.0
        except (ValueError, TypeError):
            return 0.0

    @property
    def sla_breached(self) -> bool:
        """Check if SLA has been breached."""
        if self.status == IncidentStatus.DETECTED:
            return self.minutes_since_creation > SLA_ACKNOWLEDGE_MINUTES
        if self.status == IncidentStatus.INVESTIGATING:
            # Check from creation time
            return self.minutes_since_creation > SLA_RESOLVE_MINUTES
        return False


@dataclass
class IncidentConfig:
    """Configuration for the Incident Command System."""

    enabled: bool = True
    incidents_file: str = INCIDENTS_FILE
    max_incidents: int = MAX_INCIDENTS
    auto_detect: bool = True
    auto_resolve: bool = True
    notify_on_critical: bool = True
    notify_on_high: bool = True
    notify_on_resolve: bool = True
    sla_acknowledge_minutes: int = SLA_ACKNOWLEDGE_MINUTES
    sla_resolve_minutes: int = SLA_RESOLVE_MINUTES


# ── Incident Command Engine ──────────────────────────────────────────────────


class IncidentCommander:
    """Orchestrates incident detection, management, and notification.

    The central authority for the Incident Command System.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._cfg = IncidentConfig(**{k: v for k, v in (config or {}).items() if k in IncidentConfig.__dataclass_fields__})
        self._lock = threading.RLock()
        self._incidents: list[Incident] = []
        self._incident_counter: int = 0
        self._alert_fn: Callable[[str, bool], None] | None = None
        self._load_incidents()

    # ── Alert callback ─────────────────────────────────────────────────────

    def set_alert_fn(self, fn: Callable[[str, bool], None] | None) -> None:
        """Set the alert callback function (signature: fn(message: str, is_critical: bool))."""
        self._alert_fn = fn

    # ── Persistence ─────────────────────────────────────────────────────────

    def _load_incidents(self) -> None:
        """Load incidents from JSON file."""
        path = self._cfg.incidents_file
        # In-memory mode: never read a file (on POSIX ":memory:" is a valid
        # filename, so without this a junk file accumulates incidents across runs)
        if path == ":memory:":
            return
        # Clean up any stale .tmp file from a previous failed atomic write
        tmp_path = path + ".tmp"
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                _log.debug("[ICS] Cleaned up stale .tmp file: %s", tmp_path)
            except OSError as exc:
                _log.debug("[ICS] Could not remove stale .tmp file: %s", exc)
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                self._incidents = [Incident(**item) for item in data.get("incidents", [])]
                self._incident_counter = data.get("counter", len(self._incidents))
                # Auto-resolve synthetic test incidents
                for inc in self._incidents:
                    if inc.is_open and (inc.source == "e2e_test" or inc.title.startswith("E2E test incident")):
                        inc.status = IncidentStatus.RESOLVED
                        inc.resolved_at = datetime.now(timezone.utc).isoformat()
                        inc.resolution_notes = "Auto-resolved: test incident completed"
            _log.info("[ICS] Loaded %d incidents from %s", len(self._incidents), path)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.warning("[ICS] Failed to load incidents: %s — starting fresh", exc)
            # Backup corrupt file to prevent repeated failures
            try:
                backup_path = path + ".bak"
                if os.path.exists(path):
                    os.replace(path, backup_path)
                    _log.info("[ICS] Backed up corrupt file to %s", backup_path)
            except (OSError, AttributeError) as backup_exc:
                _log.debug("[ICS] Backup failed: %s", backup_exc)
            self._incidents = []
            self._incident_counter = 0

    def _save_incidents(self) -> None:
        """Save incidents to JSON file (atomic write to prevent corruption)."""
        # In-memory mode: never write a file (see _load_incidents)
        if self._cfg.incidents_file == ":memory:":
            return
        # Limit incidents to prevent unbounded file growth
        if len(self._incidents) > MAX_INCIDENTS:
            self._incidents = self._incidents[-MAX_INCIDENTS:]
        try:
            data = json.dumps({
                "incidents": [inc.to_dict() for inc in self._incidents],
                "counter": self._incident_counter,
            }, indent=2)
            # Atomic write: write to temp file, then rename
            tmp_path = self._cfg.incidents_file + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._cfg.incidents_file)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            _log.warning("[ICS] Failed to save incidents: %s", exc)

    # ── Incident creation ───────────────────────────────────────────────────

    def _next_id(self) -> str:
        """Generate the next incident ID."""
        self._incident_counter += 1
        return f"INC-{self._incident_counter:04d}"

    def create_incident(
        self,
        title: str,
        description: str,
        source: str,
        severity: IncidentSeverity | str,
        detected_by: str = "auto",
        affected_modules: list[str] | None = None,
        tags: list[str] | None = None,
        scorecard_pct: float = 0.0,
    ) -> Incident | None:
        """Create a new incident if no duplicate open incident exists.

        Args:
            title: Short incident title.
            description: Detailed description.
            source: Module or component that detected it.
            severity: Severity level (CRITICAL, HIGH, MEDIUM, LOW).
            detected_by: Detection method.
            affected_modules: List of affected module names.
            tags: Additional tags.
            scorecard_pct: Scorecard percentage at time of detection.

        Returns:
            The new Incident, or None if a duplicate already exists.
        """
        sev = severity if isinstance(severity, IncidentSeverity) else IncidentSeverity(severity.upper())

        # Deduplication: check for open incident from same source with same title
        with self._lock:
            for inc in self._incidents:
                if inc.is_open and inc.source == source and inc.title == title:
                    _log.debug("[ICS] Duplicate incident prevented: %s/%s", source, title)
                    return None

            incident = Incident(
                incident_id=self._next_id(),
                title=title,
                description=description,
                source=source,
                severity=sev,
                detected_by=detected_by,
                affected_modules=affected_modules or [],
                tags=tags or [],
                scorecard_pct_at_detection=scorecard_pct,
            )
            self._incidents.append(incident)
            self._save_incidents()

        # Notify for critical/high severity
        if sev in (IncidentSeverity.CRITICAL, IncidentSeverity.HIGH):
            self._send_alert(
                f"[ICS] {sev.value} INCIDENT {incident.incident_id}: {title}\n{description[:200]}",
                is_critical=(sev == IncidentSeverity.CRITICAL),
            )

        _log.info("[ICS] Created incident %s: %s (%s)", incident.incident_id, title, sev.value)
        return incident

    # ── Incident lifecycle ──────────────────────────────────────────────────

    def acknowledge_incident(self, incident_id: str, notes: str = "") -> bool:
        """Mark an incident as INVESTIGATING.

        Args:
            incident_id: The incident ID (e.g., INC-0001).
            notes: Optional acknowledgement notes.

        Returns:
            True if acknowledged, False if not found or already resolved.
        """
        with self._lock:
            for inc in self._incidents:
                if inc.incident_id == incident_id and inc.is_open:
                    inc.status = IncidentStatus.INVESTIGATING
                    inc.acknowledged_at = datetime.now(timezone.utc).isoformat()
                    if notes:
                        inc.resolution_notes = notes
                    self._save_incidents()
                    return True
            return False

    def resolve_incident(self, incident_id: str, resolution_notes: str = "") -> bool:
        """Mark an incident as RESOLVED.

        Args:
            incident_id: The incident ID.
            resolution_notes: How the incident was resolved.

        Returns:
            True if resolved, False if not found or already closed.
        """
        with self._lock:
            for inc in self._incidents:
                if inc.incident_id == incident_id and inc.status != IncidentStatus.CLOSED:
                    was_open = inc.is_open
                    inc.status = IncidentStatus.RESOLVED
                    inc.resolved_at = datetime.now(timezone.utc).isoformat()
                    if resolution_notes:
                        inc.resolution_notes = resolution_notes
                    self._save_incidents()

                    if was_open and self._cfg.notify_on_resolve:
                        self._send_alert(
                            f"[ICS] RESOLVED {inc.incident_id}: {inc.title}",
                            is_critical=False,
                        )
                    return True
            return False

    def close_incident(self, incident_id: str, notes: str = "") -> bool:
        """Close a resolved incident."""
        with self._lock:
            for inc in self._incidents:
                if inc.incident_id == incident_id and inc.status == IncidentStatus.RESOLVED:
                    inc.status = IncidentStatus.CLOSED
                    inc.closed_at = datetime.now(timezone.utc).isoformat()
                    if notes:
                        inc.resolution_notes = notes
                    self._save_incidents()
                    return True
            return False

    # ── Query methods ───────────────────────────────────────────────────────

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        """Get a specific incident by ID."""
        with self._lock:
            for inc in self._incidents:
                if inc.incident_id == incident_id:
                    return inc.to_dict()
            return None

    def get_open_incidents(self) -> list[dict[str, Any]]:
        """Get all open (DETECTED or INVESTIGATING) incidents."""
        with self._lock:
            return [inc.to_dict() for inc in self._incidents if inc.is_open]

    def get_all_incidents(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get all incidents, most recent first."""
        with self._lock:
            return [inc.to_dict() for inc in self._incidents[-limit:]][::-1]

    def get_stats(self) -> dict[str, Any]:
        """Get incident statistics."""
        with self._lock:
            total = len(self._incidents)
            open_count = sum(1 for inc in self._incidents if inc.is_open)
            resolved = sum(1 for inc in self._incidents if inc.status == IncidentStatus.RESOLVED)
            closed = sum(1 for inc in self._incidents if inc.status == IncidentStatus.CLOSED)
            critical = sum(1 for inc in self._incidents if inc.severity == IncidentSeverity.CRITICAL and inc.is_open)
            high = sum(1 for inc in self._incidents if inc.severity == IncidentSeverity.HIGH and inc.is_open)
            sla_breached = sum(1 for inc in self._incidents if inc.is_open and inc.sla_breached)
            return {
                "enabled": self._cfg.enabled,
                "total_incidents": total,
                "open_incidents": open_count,
                "resolved": resolved,
                "closed": closed,
                "critical_open": critical,
                "high_open": high,
                "sla_breached": sla_breached,
                "auto_detect": self._cfg.auto_detect,
                "auto_resolve": self._cfg.auto_resolve,
            }

    # ── Detection cycle ─────────────────────────────────────────────────────

    def run_detection_cycle(self) -> dict[str, Any]:
        """Run a full detection cycle against all constitution modules.

        Checks:
        1. Module health (from run_constitution_checks)
        2. Scorecard compliance
        3. Auto-resolves incidents if system recovered

        Returns:
            Dict with created/resolved counts.
        """
        created = 0
        resolved = 0

        try:
            # Step 1: Check module health
            from scripts.run_constitution_checks import run_checks
            check_report = run_checks()

            if check_report.failed > 0:
                failed_modules = [
                    r for r in check_report.results if r.status == "FAIL"
                ]
                for fm in failed_modules:
                    inc = self.create_incident(
                        title=f"Module failure: {fm.name}",
                        description=f"Module {fm.key} failed health check: {fm.error[:300] if fm.error else 'Unknown error'}",
                        source="health_check",
                        severity=IncidentSeverity.HIGH,
                        detected_by="detection_cycle",
                        affected_modules=[fm.key],
                    )
                    if inc:
                        created += 1

            # Step 2: Check scorecard
            from scripts.constitution_scorecard import run_scorecard
            scorecard = run_scorecard()

            if scorecard.overall_pct < 90.0:
                inc = self.create_incident(
                    title=f"Scorecard compliance dropped to {scorecard.overall_pct:.1f}%",
                    description=f"Scorecard dropped below 90% threshold. "
                                f"Passed: {scorecard.total_passed}/{scorecard.total_requirements}",
                    source="scorecard",
                    severity=IncidentSeverity.CRITICAL if scorecard.overall_pct < 70 else IncidentSeverity.HIGH,
                    detected_by="detection_cycle",
                    scorecard_pct=scorecard.overall_pct,
                )
                if inc:
                    created += 1

            # Step 3: Auto-resolve incidents if system recovered
            if self._cfg.auto_resolve and check_report.failed == 0 and scorecard.overall_pct >= 90.0:
                with self._lock:
                    for inc in self._incidents:
                        if inc.is_open and inc.detected_by == "detection_cycle":
                            if (inc.source == "health_check" and
                                not any(r.key in inc.affected_modules for r in check_report.results if r.status == "FAIL")):
                                # Module is healthy now
                                inc.status = IncidentStatus.RESOLVED
                                inc.resolved_at = datetime.now(timezone.utc).isoformat()
                                inc.resolution_notes = "Auto-resolved: system healthy"
                                resolved += 1
                            elif inc.source == "scorecard" and scorecard.overall_pct >= 90.0:
                                inc.status = IncidentStatus.RESOLVED
                                inc.resolved_at = datetime.now(timezone.utc).isoformat()
                                inc.resolution_notes = f"Auto-resolved: scorecard at {scorecard.overall_pct}%"
                                resolved += 1
                    self._save_incidents()

        except Exception as exc:
            _log.error("[ICS] Detection cycle failed: %s", exc)

        return {"created": created, "resolved": resolved, "open_after": len(self.get_open_incidents())}

    # ── Alerting ────────────────────────────────────────────────────────────

    def _send_alert(self, message: str, is_critical: bool) -> None:
        """Send an alert via the configured callback."""
        if self._alert_fn:
            try:
                self._alert_fn(message, is_critical)
                return
            except Exception as exc:
                _log.warning("[ICS] Alert callback failed: %s", exc)
        _log.info("[ICS] Alert (%s): %s", "CRITICAL" if is_critical else "INFO", message)

    def get_last_report(self) -> dict[str, Any] | None:
        """Get a summary report of the system state."""
        stats = self.get_stats()
        open_incidents = self.get_open_incidents()
        return {
            "stats": stats,
            "open_incidents": open_incidents,
            "open_count": len(open_incidents),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_commander: IncidentCommander | None = None
_commander_lock = threading.RLock()


def get_incident_commander(config: dict[str, Any] | None = None) -> IncidentCommander:
    """Get or create the singleton IncidentCommander."""
    global _commander
    if _commander is None:
        with _commander_lock:
            if _commander is None:
                _commander = IncidentCommander(config)
    return _commander


def reset_incident_commander() -> None:
    """Reset the singleton (for testing)."""
    global _commander
    with _commander_lock:
        _commander = None


__all__ = [
    "IncidentCommander",
    "Incident",
    "IncidentConfig",
    "IncidentSeverity",
    "IncidentStatus",
    "get_incident_commander",
    "reset_incident_commander",
]
