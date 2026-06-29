"""
MTTR Tracker — Mean Time to Resolve Tracking.

Tracks incident resolution times across categories and computes MTTR
(Mean Time to Resolve) and MTBF (Mean Time Between Failures) metrics.
Integrated with the SLO governance system for alerting on SLA breaches.

Usage
-----
    from core.mttr_tracker import MTTRTracker

    tracker = MTTRTracker()
    tracker.record_incident("broker_outage", severity="CRITICAL")
    # ... incident is resolved ...
    tracker.resolve_incident("broker_outage", incident_id="...")
    report = tracker.get_report()
    print(f"Overall MTTR: {report.overall_mttr:.1f}s")
    print(f"MTBF: {report.mtbf_hours:.1f}h")
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class IncidentRecord:
    """A single tracked incident.

    Attributes:
        category: Incident category (e.g., "broker_outage", "market_data").
        severity: Severity level (INFO, WARNING, ERROR, CRITICAL).
        incident_id: Unique incident identifier.
        started_at: Timestamp when incident was detected.
        resolved_at: Timestamp when incident was resolved (None if open).
        description: Optional human-readable description.
        resolution_time_seconds: Computed resolution duration (0 if open).
    """
    category: str
    severity: str = "WARNING"
    incident_id: str = ""
    started_at: float = field(default_factory=time.time)
    resolved_at: float | None = None
    description: str = ""
    resolution_time_seconds: float = 0.0


@dataclass
class MTTRReport:
    """MTTR/MTBF analysis report.

    Attributes:
        overall_mttr: Mean Time To Resolve across all resolved incidents (seconds).
        overall_mtbf: Mean Time Between Failures (seconds).
        mtbf_hours: MTBF in hours.
        by_category: Per-category MTTR breakdown (category -> seconds).
        by_severity: Per-severity MTTR breakdown (severity -> seconds).
        open_incidents: Count of currently open (unresolved) incidents.
        total_incidents: Total tracked incidents.
        resolved_incidents: Number of resolved incidents used for MTTR.
        p50_mttr: Median resolution time (seconds).
        p90_mttr: 90th percentile resolution time (seconds).
        p99_mttr: 99th percentile resolution time (seconds).
        max_mttr: Maximum resolution time (seconds).
        min_mttr: Minimum resolution time (seconds).
        timestamp: Report generation time.
    """
    overall_mttr: float = 0.0
    overall_mtbf: float = 0.0
    mtbf_hours: float = 0.0
    by_category: dict[str, float] = field(default_factory=dict)
    by_severity: dict[str, float] = field(default_factory=dict)
    open_incidents: int = 0
    total_incidents: int = 0
    resolved_incidents: int = 0
    p50_mttr: float = 0.0
    p90_mttr: float = 0.0
    p99_mttr: float = 0.0
    max_mttr: float = 0.0
    min_mttr: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_mttr_seconds": round(self.overall_mttr, 1),
            "overall_mtbf_seconds": round(self.overall_mtbf, 1),
            "mtbf_hours": round(self.mtbf_hours, 2),
            "by_category": {k: round(v, 1) for k, v in self.by_category.items()},
            "by_severity": {k: round(v, 1) for k, v in self.by_severity.items()},
            "open_incidents": self.open_incidents,
            "total_incidents": self.total_incidents,
            "resolved_incidents": self.resolved_incidents,
            "p50_mttr_seconds": round(self.p50_mttr, 1),
            "p90_mttr_seconds": round(self.p90_mttr, 1),
            "p99_mttr_seconds": round(self.p99_mttr, 1),
            "max_mttr_seconds": round(self.max_mttr, 1),
            "min_mttr_seconds": round(self.min_mttr, 1),
            "timestamp": self.timestamp,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            "=" * 60,
            "  MTTR / MTBF Report",
            "=" * 60,
            f"  Total Incidents:   {self.total_incidents}",
            f"  Resolved:           {self.resolved_incidents}",
            f"  Open:               {self.open_incidents}",
            "",
            f"  Overall MTTR:       {self.overall_mttr:.1f}s",
            f"  MTBF:               {self.mtbf_hours:.2f}h",
            "",
            "  Resolution Times:",
            f"    P50:  {self.p50_mttr:.1f}s",
            f"    P90:  {self.p90_mttr:.1f}s",
            f"    P99:  {self.p99_mttr:.1f}s",
            f"    Max:  {self.max_mttr:.1f}s",
            f"    Min:  {self.min_mttr:.1f}s",
            "",
            "  By Category:",
        ]
        for cat, mttr in sorted(self.by_category.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"    {cat:<25s} {mttr:.1f}s")
        lines.extend([
            "",
            "  By Severity:",
        ])
        for sev, mttr in sorted(self.by_severity.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"    {sev:<10s} {mttr:.1f}s")
        lines.append("=" * 60)
        return "\n".join(lines)


# ── MTTR Tracker ─────────────────────────────────────────────────────────────


class MTTRTracker:
    """Tracks incident resolution times and computes MTTR/MTBF metrics.

    Thread-safe. Integrates with SLO governance by recording metrics
    named ``mttr_<category>`` and ``mtbf_hours`` on each resolution.
    """

    def __init__(self, alert_fn: Any | None = None):
        self._lock = threading.RLock()
        self._incidents: list[IncidentRecord] = []
        self._open: dict[str, IncidentRecord] = {}  # incident_id -> record
        self._alert_fn = alert_fn
        self._start_time = time.time()
        self._last_resolved_time: float | None = None
        self._resolution_times: list[float] = []

    # ── Record methods ────────────────────────────────────────────────────

    def record_incident(
        self,
        category: str,
        severity: str = "WARNING",
        incident_id: str = "",
        description: str = "",
    ) -> str:
        """Record a new incident.

        Args:
            category: Incident category (e.g., "broker_outage").
            severity: CRITICAL, ERROR, WARNING, or INFO.
            incident_id: Optional ID (auto-generated if empty).
            description: Optional description.

        Returns:
            The incident_id for use with resolve_incident().
        """
        with self._lock:
            iid = incident_id or f"inc_{int(time.time() * 1000)}_{len(self._incidents)}"
            record = IncidentRecord(
                category=category,
                severity=severity.upper(),
                incident_id=iid,
                started_at=time.time(),
                description=description,
            )
            self._incidents.append(record)
            self._open[iid] = record
            _log.info("[MTTR] Incident opened: %s [%s] %s", iid, severity, category)
            return iid

    def resolve_incident(self, incident_id: str) -> bool:
        """Mark an incident as resolved.

        Args:
            incident_id: ID returned by record_incident().

        Returns:
            True if resolved, False if ID not found or already resolved.
        """
        with self._lock:
            record = self._open.pop(incident_id, None)
            if record is None:
                return False
            now = time.time()
            record.resolved_at = now
            resolution_time = now - record.started_at
            record.resolution_time_seconds = resolution_time
            self._resolution_times.append(resolution_time)
            self._last_resolved_time = now

            _log.info(
                "[MTTR] Incident resolved: %s (%s) in %.1fs",
                incident_id, record.category, resolution_time,
            )

            # Cascade to SLO governance
            try:
                from core.slo_governance import record_metric
                category_key = f"mttr_{record.category.lower().replace('-', '_')}"
                record_metric(category_key, resolution_time)
                record_metric("mttr_overall", self._compute_mttr())
                record_metric("mtbf_hours", self._compute_mtbf_hours())
            except ImportError:
                pass
            except Exception as exc:
                _log.debug("[MTTR] SLO cascade skipped: %s", exc)

            # Alert if resolution exceeds thresholds
            threshold = self._get_severity_threshold(record.severity)
            if resolution_time > threshold and self._alert_fn:
                self._alert_fn(
                    f"SLA breach: {record.category} resolved in "
                    f"{resolution_time:.0f}s (threshold: {threshold}s)"
                )

            return True

    def _get_severity_threshold(self, severity: str) -> float:
        """Get resolution time threshold per severity level (seconds)."""
        thresholds = {
            "CRITICAL": 60,    # 1 minute
            "ERROR": 300,      # 5 minutes
            "WARNING": 900,    # 15 minutes
            "INFO": 3600,      # 1 hour
        }
        return thresholds.get(severity, 300)

    def is_open(self, incident_id: str) -> bool:
        """Check if an incident is still open."""
        with self._lock:
            return incident_id in self._open

    @property
    def open_count(self) -> int:
        with self._lock:
            return len(self._open)

    @property
    def resolved_count(self) -> int:
        with self._lock:
            return len([r for r in self._incidents if r.resolved_at is not None])

    # ── Computation methods ───────────────────────────────────────────────

    def _compute_mttr(self) -> float:
        """Compute overall Mean Time To Resolve (seconds)."""
        if not self._resolution_times:
            return 0.0
        return sum(self._resolution_times) / len(self._resolution_times)

    def _compute_mtbf_hours(self) -> float:
        """Compute Mean Time Between Failures in hours."""
        if len(self._resolution_times) < 2:
            return 0.0
        # MTBF = total uptime / number_of_failures
        # Approximate as: (time_since_first_resolution - sum_resolution_times) / (failures - 1)
        elapsed = time.time() - self._start_time
        total_resolution_time = sum(self._resolution_times)
        uptime = max(elapsed - total_resolution_time, 1.0)
        failures = len(self._resolution_times)
        mtbf_seconds = uptime / max(failures, 1)
        return mtbf_seconds / 3600.0

    def _percentile(self, sorted_times: list[float], pct: float) -> float:
        """Compute a percentile from a sorted list."""
        if not sorted_times:
            return 0.0
        k = (len(sorted_times) - 1) * pct / 100.0
        f = int(k)
        c = min(f + 1, len(sorted_times) - 1)
        if f == c:
            return sorted_times[f]
        return sorted_times[f] * (c - k) + sorted_times[c] * (k - f)

    def get_report(self) -> MTTRReport:
        """Generate a comprehensive MTTR/MTBF report."""
        with self._lock:
            resolved = [r for r in self._incidents if r.resolved_at is not None]
            open_inc = [r for r in self._incidents if r.resolved_at is None]
            sorted_times = sorted(self._resolution_times)

            # Per-category MTTR
            by_category: dict[str, list[float]] = {}
            for r in resolved:
                if r.category not in by_category:
                    by_category[r.category] = []
                by_category[r.category].append(r.resolution_time_seconds)

            category_mttr = {
                cat: sum(times) / len(times) for cat, times in by_category.items()
            }

            # Per-severity MTTR
            by_severity: dict[str, list[float]] = {}
            for r in resolved:
                sev = r.severity
                if sev not in by_severity:
                    by_severity[sev] = []
                by_severity[sev].append(r.resolution_time_seconds)

            severity_mttr = {
                sev: sum(times) / len(times) for sev, times in by_severity.items()
            }

            overall_mttr = self._compute_mttr()
            mtbf_hours = self._compute_mtbf_hours()

            # MTBF in seconds = total_uptime_seconds / failure_count
            _elapsed = time.time() - self._start_time
            _total_fail_secs = sum(self._resolution_times) if self._resolution_times else 0.0
            mtbf_seconds = max(_elapsed - _total_fail_secs, 1.0) / max(len(resolved), 1)

            return MTTRReport(
                overall_mttr=overall_mttr,
                overall_mtbf=mtbf_seconds,
                mtbf_hours=mtbf_hours,
                by_category=category_mttr,
                by_severity=severity_mttr,
                open_incidents=len(open_inc),
                total_incidents=len(self._incidents),
                resolved_incidents=len(resolved),
                p50_mttr=self._percentile(sorted_times, 50),
                p90_mttr=self._percentile(sorted_times, 90),
                p99_mttr=self._percentile(sorted_times, 99),
                max_mttr=sorted_times[-1] if sorted_times else 0.0,
                min_mttr=sorted_times[0] if sorted_times else 0.0,
            )

    # ── Utility ───────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Reset all tracked incidents."""
        with self._lock:
            self._incidents.clear()
            self._open.clear()
            self._resolution_times.clear()
            self._start_time = time.time()
            self._last_resolved_time = None

    def merge(self, other: MTTRTracker) -> None:
        """Merge incidents from another tracker."""
        with self._lock:
            for record in other._incidents:
                self._incidents.append(record)
                if record.incident_id in other._open:
                    self._open[record.incident_id] = record
                    if record.resolved_at is not None:
                        self._resolution_times.append(record.resolution_time_seconds)


# ── Singleton ────────────────────────────────────────────────────────────────

_tracker: MTTRTracker | None = None
_tracker_lock = threading.RLock()


def get_mttr_tracker() -> MTTRTracker:
    """Get the global MTTR tracker singleton."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = MTTRTracker()
    return _tracker


def get_mttr_report() -> MTTRReport:
    """Convenience: get current MTTR report."""
    return get_mttr_tracker().get_report()


# ── CLI ─────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.mttr_tracker")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--record", nargs=2, metavar=("category", "severity"),
                    help="Record an incident: --record broker_outage CRITICAL")
    ap.add_argument("--resolve", metavar="incident_id", help="Resolve an incident by ID")
    args = ap.parse_args()

    tracker = get_mttr_tracker()

    if args.record:
        cat, sev = args.record
        iid = tracker.record_incident(cat, severity=sev)
        print(f"Incident recorded: {iid}")
        return

    if args.resolve:
        ok = tracker.resolve_incident(args.resolve)
        print(f"Resolved: {ok}")
        return

    report = tracker.get_report()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary())


if __name__ == "__main__":
    _cli()


__all__ = [
    "IncidentRecord",
    "MTTRReport",
    "MTTRTracker",
    "get_mttr_report",
    "get_mttr_tracker",
]

