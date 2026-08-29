"""Engineering Analytics — Lead Time, Cycle Time, MTTR, MTBF, CFR & More (Pillar 12).

Tracks and reports on DORA and engineering metrics:
- Lead Time: time from commit to deployment
- Cycle Time: time from first commit to merge
- MTTR: Mean Time To Resolve (incidents)
- MTBF: Mean Time Between Failures
- Change Failure Rate (CFR): % of changes that resulted in failure
- Deployment Success Rate
- Escaped Defects
- Code Churn (additions + deletions over time)
- Engineering Velocity (commits/week)
- Developer Productivity (lines of shipped code/day)
- Hotspots (files with most changes)
- Knowledge Distribution (Bus Factor estimation)
- Review Time (time PR spends in review)
- Build Time
- Release Frequency

Usage:
    from core.engineering_analytics import get_engineering_analytics

    analytics = get_engineering_analytics()
    report = analytics.get_report(days=30)
    print(report.lead_time_days)
    print(report.mttr_hours)
    print(f"CFR: {report.change_failure_rate:.1f}%")

Design:
- Thread-safe singleton with RLock
- JSON persistence for metrics history
- Works with git log data via CLI or direct import
- Chart-data output for visualization
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

METRICS_FILE = "json/engineering_metrics.json"
MAX_METRICS_HISTORY = 1000


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class EngineeringMetricsReport:
    """Complete engineering analytics report."""

    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    period_days: int = 30

    # Velocity metrics
    lead_time_days: float = 0.0
    cycle_time_days: float = 0.0
    engineering_velocity: float = 0.0  # commits/week
    release_frequency: float = 0.0  # releases/month

    # Quality metrics
    mttr_hours: float = 0.0
    mtbf_hours: float = 0.0
    deployment_success_rate: float = 100.0  # percentage
    change_failure_rate: float = 0.0  # percentage — key DORA metric
    escaped_defects: int = 0

    # Productivity metrics
    code_churn_lines: int = 0  # additions + deletions
    developer_productivity: float = 0.0  # lines/day
    avg_review_time_hours: float = 0.0
    avg_build_time_minutes: float = 0.0

    # Hotspots
    hotspots: list[dict[str, Any]] = field(default_factory=list)
    knowledge_distribution: dict[str, float] = field(default_factory=dict)
    bus_factor: int = 1

    # Trends
    velocity_trend: str = "STABLE"  # RISING, STABLE, FALLING
    quality_trend: str = "STABLE"
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "period_days": self.period_days,
            "lead_time_days": round(self.lead_time_days, 2),
            "cycle_time_days": round(self.cycle_time_days, 2),
            "engineering_velocity": round(self.engineering_velocity, 2),
            "release_frequency": round(self.release_frequency, 2),
            "mttr_hours": round(self.mttr_hours, 2),
            "mtbf_hours": round(self.mtbf_hours, 2),
            "deployment_success_rate": round(self.deployment_success_rate, 1),
            "change_failure_rate": round(self.change_failure_rate, 1),
            "escaped_defects": self.escaped_defects,
            "code_churn_lines": self.code_churn_lines,
            "developer_productivity": round(self.developer_productivity, 2),
            "avg_review_time_hours": round(self.avg_review_time_hours, 2),
            "avg_build_time_minutes": round(self.avg_build_time_minutes, 2),
            "hotspots": self.hotspots[:10],
            "knowledge_distribution": self.knowledge_distribution,
            "bus_factor": self.bus_factor,
            "velocity_trend": self.velocity_trend,
            "quality_trend": self.quality_trend,
            "recommendations": self.recommendations[:10],
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  ENGINEERING ANALYTICS REPORT",
            f"  Period: {self.period_days} days",
            "═" * 60,
            "",
            "  Velocity:",
            f"    Lead Time:         {self.lead_time_days:.1f} days",
            f"    Cycle Time:        {self.cycle_time_days:.1f} days",
            f"    Velocity:          {self.engineering_velocity:.1f} commits/week",
            f"    Release Freq:      {self.release_frequency:.1f}/month",
            "",
            "  Quality:",
            f"    MTTR:              {self.mttr_hours:.1f} hours",
            f"    MTBF:              {self.mtbf_hours:.1f} hours",
            f"    Deploy Success:    {self.deployment_success_rate:.1f}%",
            f"    Change Fail Rate:  {self.change_failure_rate:.1f}%",
            f"    Escaped Defects:   {self.escaped_defects}",
            "",
            "  Productivity:",
            f"    Code Churn:        {self.code_churn_lines} lines",
            f"    Developer Prod:    {self.developer_productivity:.0f} lines/day",
            f"    Review Time:       {self.avg_review_time_hours:.1f} hours",
            f"    Build Time:        {self.avg_build_time_minutes:.1f} min",
            "",
            f"  Bus Factor:         {self.bus_factor}",
            f"  Velocity Trend:     {self.velocity_trend}",
            f"  Quality Trend:      {self.quality_trend}",
        ]
        if self.hotspots:
            lines.extend([
                "",
                "  Hotspots (most changed files):",
            ])
            for h in self.hotspots[:5]:
                lines.append(f"    {h.get('file', '?')}: {h.get('changes', 0)} changes")
        if self.recommendations:
            lines.extend([
                "",
                "  Recommendations:",
            ])
            for r in self.recommendations[:5]:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


@dataclass
class GitCommitRecord:
    """A single git commit record for analytics."""

    hash: str
    author: str
    date: str
    files_changed: int
    lines_added: int
    lines_deleted: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "hash": self.hash,
            "author": self.author,
            "date": self.date,
            "files_changed": self.files_changed,
            "lines_added": self.lines_added,
            "lines_deleted": self.lines_deleted,
            "message": self.message[:100],
        }


@dataclass
class IncidentRecord:
    """A single incident record for MTTR/MTBF calculation."""

    id: str
    created_at: str
    resolved_at: str | None
    severity: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "severity": self.severity,
        }


# ── Engineering Analytics Engine ─────────────────────────────────────────────


class EngineeringAnalyticsEngine:
    """Tracks and reports on engineering metrics.

    Analyzes:
    - Lead Time, Cycle Time
    - MTTR, MTBF
    - Deployment Success Rate
    - Code Churn & Velocity
    - Hotspots & Bus Factor
    - Review Time & Build Time
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._commits: list[GitCommitRecord] = []
        self._incidents: list[IncidentRecord] = []
        self._deployments: list[dict[str, Any]] = []
        self._reviews: list[dict[str, Any]] = []
        self._builds: list[dict[str, Any]] = []
        self._failures: list[dict[str, Any]] = []  # For Change Failure Rate (CFR)
        self._load_metrics()

    # ── Public API ─────────────────────────────────────────────────────────

    def record_commit(self, record: GitCommitRecord) -> None:
        """Record a git commit for analytics."""
        with self._lock:
            self._commits.append(record)
            if len(self._commits) > MAX_METRICS_HISTORY:
                self._commits = self._commits[-MAX_METRICS_HISTORY:]
            self._save_metrics()

    def record_incident(self, record: IncidentRecord) -> None:
        """Record an incident for MTTR/MTBF calculation."""
        with self._lock:
            self._incidents.append(record)
            if len(self._incidents) > MAX_METRICS_HISTORY:
                self._incidents = self._incidents[-MAX_METRICS_HISTORY:]
            self._save_metrics()

    def record_deployment(
        self, success: bool, duration_seconds: float = 0.0
    ) -> None:
        """Record a deployment outcome."""
        with self._lock:
            self._deployments.append({
                "timestamp": time.time(),
                "success": success,
                "duration_seconds": duration_seconds,
            })
            if len(self._deployments) > MAX_METRICS_HISTORY:
                self._deployments = self._deployments[-MAX_METRICS_HISTORY:]
            self._save_metrics()

    def record_review(
        self, pr_id: str, hours_in_review: float, approved: bool = True
    ) -> None:
        """Record a code review cycle."""
        with self._lock:
            self._reviews.append({
                "pr_id": pr_id,
                "hours_in_review": hours_in_review,
                "approved": approved,
                "timestamp": time.time(),
            })
            if len(self._reviews) > MAX_METRICS_HISTORY:
                self._reviews = self._reviews[-MAX_METRICS_HISTORY:]
            self._save_metrics()

    def record_build(self, duration_minutes: float, success: bool = True) -> None:
        """Record a build cycle."""
        with self._lock:
            self._builds.append({
                "duration_minutes": duration_minutes,
                "success": success,
                "timestamp": time.time(),
            })
            if len(self._builds) > MAX_METRICS_HISTORY:
                self._builds = self._builds[-MAX_METRICS_HISTORY:]
            self._save_metrics()

    def record_failure(
        self,
        change_id: str,
        severity: str = "HIGH",
        description: str = "",
    ) -> None:
        """Record a change failure for Change Failure Rate (CFR) calculation.

        Args:
            change_id: Identifier for the change that failed (e.g., commit hash or PR ID).
            severity: Impact severity (LOW, MEDIUM, HIGH, CRITICAL).
            description: Description of the failure.
        """
        with self._lock:
            self._failures.append({
                "change_id": change_id,
                "severity": severity,
                "description": description,
                "timestamp": time.time(),
            })
            if len(self._failures) > MAX_METRICS_HISTORY:
                self._failures = self._failures[-MAX_METRICS_HISTORY:]
            self._save_metrics()

    def get_report(self, days: int = 30) -> EngineeringMetricsReport:
        """Generate an engineering analytics report.

        Args:
            days: Period to analyze (default: 30 days).

        Returns:
            EngineeringMetricsReport with all metrics.
        """
        cutoff = time.time() - (days * 86400)
        report = EngineeringMetricsReport(period_days=days)

        with self._lock:
            # Filter by time period
            recent_commits = [
                c for c in self._commits
                if self._parse_timestamp(c.date) >= cutoff
            ]
            recent_incidents = [
                inc for inc in self._incidents
                if self._parse_timestamp(inc.created_at) >= cutoff
            ]
            recent_deployments = [
                d for d in self._deployments
                if d["timestamp"] >= cutoff
            ]
            recent_reviews = [
                r for r in self._reviews
                if r["timestamp"] >= cutoff
            ]
            recent_builds = [
                b for b in self._builds
                if b["timestamp"] >= cutoff
            ]

        # Velocity metrics
        n_commits = len(recent_commits)
        report.engineering_velocity = n_commits / max(days / 7, 1)
        report.code_churn_lines = sum(
            c.lines_added + c.lines_deleted for c in recent_commits
        )
        report.developer_productivity = (
            sum(c.lines_added for c in recent_commits) / max(days, 1)
        )
        report.release_frequency = len(recent_deployments) / max(days / 30, 1)

        # Lead time and cycle time estimates (from commit timestamps)
        if recent_commits:
            # Simplified: lead time = time from first commit to latest commit
            timestamps = sorted(
                self._parse_timestamp(c.date) for c in recent_commits
            )
            if len(timestamps) > 1:
                span = (timestamps[-1] - timestamps[0]) / 86400
                report.lead_time_days = span
                report.cycle_time_days = span / max(len(timestamps), 1)

        # Quality metrics
        # MTTR: average time to resolve incidents
        resolved = [
            inc for inc in recent_incidents
            if inc.resolved_at is not None
        ]
        if resolved:
            total_hours = 0.0
            for inc in resolved:
                created = self._parse_timestamp(inc.created_at)
                resolved_ts = self._parse_timestamp(inc.resolved_at)
                if created and resolved_ts:
                    total_hours += (resolved_ts - created) / 3600
            report.mttr_hours = total_hours / len(resolved)

        # MTBF: average time between incidents
        if len(recent_incidents) > 1:
            sorted_inc = sorted(
                recent_incidents,
                key=lambda inc: self._parse_timestamp(inc.created_at),
            )
            intervals = []
            for i in range(1, len(sorted_inc)):
                t1 = self._parse_timestamp(sorted_inc[i - 1].created_at)
                t2 = self._parse_timestamp(sorted_inc[i].created_at)
                if t1 and t2:
                    intervals.append((t2 - t1) / 3600)
            if intervals:
                report.mtbf_hours = sum(intervals) / len(intervals)

        # Deployment success rate
        if recent_deployments:
            successes = sum(1 for d in recent_deployments if d["success"])
            report.deployment_success_rate = (
                successes / len(recent_deployments) * 100
            )

        # Change Failure Rate (CFR) — key DORA metric
        # CFR = failed_changes / total_changes * 100
        with self._lock:
            recent_failures = [
                f for f in self._failures
                if f["timestamp"] >= cutoff
            ]
        total_changes = n_commits
        if total_changes > 0 and recent_failures:
            report.change_failure_rate = (
                len(recent_failures) / max(total_changes, 1) * 100
            )

        # Review time
        if recent_reviews:
            report.avg_review_time_hours = sum(
                r["hours_in_review"] for r in recent_reviews
            ) / len(recent_reviews)

        # Build time
        if recent_builds:
            successful = [b for b in recent_builds if b["success"]]
            if successful:
                report.avg_build_time_minutes = sum(
                    b["duration_minutes"] for b in successful
                ) / len(successful)

        # Hotspots
        file_changes: dict[str, int] = {}
        author_files: dict[str, set[str]] = {}
        for c in recent_commits:
            if c.files_changed > 0:
                for _ in range(min(c.files_changed, 20)):  # Approximate per commit
                    file_key = c.message.split("\n")[0][:50]
                    file_changes[file_key] = file_changes.get(file_key, 0) + 1
            if c.author not in author_files:
                author_files[c.author] = set()
            author_files[c.author].add(c.hash)

        sorted_files = sorted(
            file_changes.items(), key=lambda x: x[1], reverse=True
        )
        report.hotspots = [
            {"file": f, "changes": c} for f, c in sorted_files[:10]
        ]

        # Bus factor
        if author_files:
            # Bus factor = number of authors needed to cover 50% of commits
            author_commits: dict[str, int] = {}
            for c in recent_commits:
                author_commits[c.author] = (
                    author_commits.get(c.author, 0) + 1
                )
            sorted_authors = sorted(
                author_commits.items(), key=lambda x: x[1], reverse=True
            )
            total = sum(a[1] for a in sorted_authors)
            cumulative = 0
            bus_factor = 0
            for _, count in sorted_authors:
                cumulative += count
                bus_factor += 1
                if cumulative / max(total, 1) >= 0.5:
                    break
            report.bus_factor = bus_factor

            # Knowledge distribution
            total_commits = sum(author_commits.values())
            report.knowledge_distribution = {
                author: round(count / max(total_commits, 1) * 100, 1)
                for author, count in sorted_authors[:10]
            }

        # Trends (compare with previous period)
        prev_cutoff = cutoff - (days * 86400)
        prev_commits = [
            c for c in self._commits
            if prev_cutoff <= self._parse_timestamp(c.date) < cutoff
        ]

        if prev_commits:
            prev_velocity = len(prev_commits) / max(days / 7, 1)
            if report.engineering_velocity > prev_velocity * 1.2:
                report.velocity_trend = "RISING"
            elif report.engineering_velocity < prev_velocity * 0.8:
                report.velocity_trend = "FALLING"
            else:
                report.velocity_trend = "STABLE"

        if recent_incidents and len(self._incidents) > len(recent_incidents):
            prev_incidents = [
                inc for inc in self._incidents
                if prev_cutoff <= self._parse_timestamp(inc.created_at) < cutoff
            ]
            if prev_incidents:
                prev_mttr = self._calc_mttr(prev_incidents)
                if report.mttr_hours < prev_mttr * 0.8:
                    report.quality_trend = "RISING"
                elif report.mttr_hours > prev_mttr * 1.2:
                    report.quality_trend = "FALLING"
                else:
                    report.quality_trend = "STABLE"

        # Recommendations
        report.recommendations = self._generate_recommendations(report)

        return report

    def import_from_git_log(self, days: int = 30) -> int:
        """Import git log data for DORA metric calculation.

        Runs `git log` to fetch commit data and populates the analytics
        engine with real commit records.

        Args:
            days: Number of days of history to import.

        Returns:
            Number of commits imported.
        """
        try:
            import subprocess
            since = int(time.time()) - (days * 86400)
            result = subprocess.run(
                [
                    "git", "log",
                    f"--since={since}",
                    "--format=%H|%an|%ai|%s",
                    "--shortstat",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return 0

            lines = result.stdout.strip().splitlines()
            imported = 0
            current_hash = ""
            current_author = ""
            current_date = ""
            current_message = ""

            f_count, a_count, d_count = 0, 0, 0
            for line in lines:
                if "|" in line and not line.startswith(" "):
                    # Save previous commit if exists
                    if current_hash:
                        self.record_commit(GitCommitRecord(
                            hash=current_hash,
                            author=current_author,
                            date=current_date,
                            files_changed=f_count,
                            lines_added=a_count,
                            lines_deleted=d_count,
                            message=current_message,
                        ))
                        imported += 1

                    # Parse new commit
                    parts = line.split("|", 3)
                    current_hash = parts[0] if len(parts) > 0 else ""
                    current_author = parts[1] if len(parts) > 1 else ""
                    current_date = parts[2] if len(parts) > 2 else ""
                    current_message = parts[3] if len(parts) > 3 else ""
                    f_count, a_count, d_count = 0, 0, 0

                elif "file" in line or "files" in line:
                    # Parse shortstat: " 2 files changed, 50 insertions(+), 10 deletions(-)"
                    import re as _re
                    f_match = _re.search(r"(\d+) file", line)
                    a_match = _re.search(r"(\d+) insertion", line)
                    d_match = _re.search(r"(\d+) deletion", line)
                    f_count = int(f_match.group(1)) if f_match else 0
                    a_count = int(a_match.group(1)) if a_match else 0
                    d_count = int(d_match.group(1)) if d_match else 0

            # Save last commit
            if current_hash:
                self.record_commit(GitCommitRecord(
                    hash=current_hash,
                    author=current_author,
                    date=current_date,
                    files_changed=f_count,
                    lines_added=a_count,
                    lines_deleted=d_count,
                    message=current_message,
                ))
                imported += 1

            _log.info("[EAN] Imported %d commits from git log (%d days)", imported, days)
            return imported

        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            _log.warning("[EAN] Git log import failed: %s", exc)
            return 0

    def to_chart_data(self, days: int = 30) -> dict[str, list[Any]]:
        """Generate chart-friendly data from metrics history.

        Returns dict with time-series data suitable for dashboard charts:
        - dates: list of date strings
        - velocity: commits per week
        - mttr: hours
        - deployment_success: percentage
        - change_failure_rate: percentage

        Args:
            days: Period to analyze.

        Returns:
            Dict with chart-ready arrays.
        """
        # Generate weekly data points
        chart_data: dict[str, list[Any]] = {
            "dates": [],
            "velocity": [],
            "mttr_hours": [],
            "deployment_success_pct": [],
            "change_failure_rate_pct": [],
            "code_churn_lines": [],
            "lead_time_days": [],
        }

        for week in range(max(days // 7, 1)):
            week_days = min(7, days - week * 7)
            week_report = self.get_report(days=week_days)
            chart_data["dates"].append(f"W{week + 1}")
            chart_data["velocity"].append(round(week_report.engineering_velocity, 1))
            chart_data["mttr_hours"].append(round(week_report.mttr_hours, 1))
            chart_data["deployment_success_pct"].append(round(week_report.deployment_success_rate, 1))
            chart_data["change_failure_rate_pct"].append(round(week_report.change_failure_rate, 1))
            chart_data["code_churn_lines"].append(week_report.code_churn_lines)
            chart_data["lead_time_days"].append(round(week_report.lead_time_days, 1))

        return chart_data

    def get_stats(self) -> dict[str, Any]:
        """Get quick analytics statistics."""
        with self._lock:
            return {
                "total_commits": len(self._commits),
                "total_incidents": len(self._incidents),
                "total_deployments": len(self._deployments),
                "total_reviews": len(self._reviews),
                "total_builds": len(self._builds),
            }

    # ── Internal ───────────────────────────────────────────────────────────

    def _parse_timestamp(self, date_str: str | None) -> float:
        """Parse a timestamp string to Unix time."""
        if date_str is None:
            return 0.0
        try:
            if "T" in date_str:
                return datetime.fromisoformat(date_str).timestamp()
            # Try Unix timestamp
            return float(date_str)
        except (ValueError, TypeError):
            return 0.0

    def _calc_mttr(self, incidents: list[IncidentRecord]) -> float:
        """Calculate MTTR from a list of incidents."""
        resolved = [inc for inc in incidents if inc.resolved_at]
        if not resolved:
            return 0.0
        total = 0.0
        for inc in resolved:
            created = self._parse_timestamp(inc.created_at)
            resolved_ts = self._parse_timestamp(inc.resolved_at)
            if created and resolved_ts:
                total += (resolved_ts - created) / 3600
        return total / len(resolved)

    def _generate_recommendations(
        self, report: EngineeringMetricsReport
    ) -> list[str]:
        """Generate recommendations based on analytics."""
        recs: list[str] = []

        if report.lead_time_days > 7:
            recs.append(
                f"Lead time is {report.lead_time_days:.1f} days — "
                "investigate bottlenecks in review/deployment pipeline"
            )
        if report.cycle_time_days > 3:
            recs.append(
                f"Cycle time is {report.cycle_time_days:.1f} days — "
                "consider smaller, more frequent PRs"
            )
        if report.mttr_hours > 24:
            recs.append(
                f"MTTR is {report.mttr_hours:.1f} hours — "
                "improve incident response procedures"
            )
        if report.deployment_success_rate < 95:
            recs.append(
                f"Deployment success rate is {report.deployment_success_rate:.1f}% — "
                "invest in pre-deployment testing"
            )
        if report.change_failure_rate > 15:
            recs.append(
                f"Change Failure Rate is {report.change_failure_rate:.1f}% — "
                "strengthen pre-deployment validation and testing"
            )
        if report.escaped_defects > 3:
            recs.append(
                f"{report.escaped_defects} escaped defects — "
                "improve test coverage and review process"
            )
        if report.bus_factor <= 2:
            recs.append(
                f"Bus factor is {report.bus_factor} — "
                "critical knowledge concentration risk"
            )
        if report.avg_review_time_hours > 24:
            recs.append(
                f"Review time is {report.avg_review_time_hours:.1f} hours — "
                "consider expediting reviews"
            )
        if report.velocity_trend == "FALLING":
            recs.append(
                "Engineering velocity is declining — investigate blockers"
            )
        if report.quality_trend == "FALLING":
            recs.append(
                "Quality metrics are declining — "
                "increase test coverage and code review rigour"
            )

        return recs[:8]

    # ── Persistence ────────────────────────────────────────────────────────

    def _load_metrics(self) -> None:
        """Load metrics from JSON file."""
        path = Path(METRICS_FILE)
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                self._commits = [
                    GitCommitRecord(**c) for c in data.get("commits", [])
                ]
                self._incidents = [
                    IncidentRecord(**inc) for inc in data.get("incidents", [])
                ]
                self._deployments = data.get("deployments", [])
                self._reviews = data.get("reviews", [])
                self._builds = data.get("builds", [])
                self._failures = data.get("failures", [])
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.debug("[EAN] Load metrics failed: %s", exc)

    def _save_metrics(self) -> None:
        """Save metrics to JSON file."""
        path = Path(METRICS_FILE)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "commits": [c.to_dict() for c in self._commits],
                "incidents": [inc.to_dict() for inc in self._incidents],
                "deployments": self._deployments,
                "reviews": self._reviews,
                "builds": self._builds,
                "failures": self._failures,
            }, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            _log.debug("[EAN] Save metrics failed: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────

_engine: EngineeringAnalyticsEngine | None = None
_engine_lock = threading.RLock()


def get_engineering_analytics() -> EngineeringAnalyticsEngine:
    """Get the singleton EngineeringAnalyticsEngine instance."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = EngineeringAnalyticsEngine()
        return _engine


def reset_engineering_analytics() -> None:
    """Force-reset singleton (for testing)."""
    global _engine
    with _engine_lock:
        _engine = None


def _cli() -> None:
    """Command-line interface.

    Usage:
        python -m core.engineering_analytics            # 30-day report
        python -m core.engineering_analytics --days 90   # 90-day report
        python -m core.engineering_analytics --stats     # Statistics
        python -m core.engineering_analytics --json      # JSON output
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Engineering Analytics — Metrics & Reports",
    )
    parser.add_argument("--days", type=int, default=30, help="Analysis period")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--import-git", type=int, nargs="?", const=30, help="Import git log (optional days)")
    parser.add_argument("--chart", action="store_true", help="Output chart data")

    args = parser.parse_args()
    analytics = get_engineering_analytics()

    if args.import_git:
        imported = analytics.import_from_git_log(days=args.import_git)
        print(f"Imported {imported} commits from git log ({args.import_git} days)")
        return

    if args.chart:
        chart = analytics.to_chart_data(days=args.days)
        print(json.dumps(chart, indent=2))
        return

    if args.stats:
        stats = analytics.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("═" * 50)
            print("Engineering Analytics — Statistics")
            print("═" * 50)
            for k, v in stats.items():
                print(f"  {k.replace('_', ' ').title():30s}: {v}")
        return

    report = analytics.get_report(days=args.days)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary_text())


if __name__ == "__main__":
    _cli()


__all__ = [
    "EngineeringAnalyticsEngine",
    "EngineeringMetricsReport",
    "GitCommitRecord",
    "IncidentRecord",
    "get_engineering_analytics",
    "reset_engineering_analytics",
]
