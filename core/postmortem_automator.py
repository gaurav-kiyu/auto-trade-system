"""Postmortem Automator — Auto-generated Incident Postmortems (Constitution v4.0).

Automatically generates structured postmortem documents from incidents,
covering:
- Incident timeline and severity
- Root cause analysis from RootCauseAnalyzer
- Impact assessment (affected services, users, data)
- Resolution steps taken
- Lessons learned and action items
- Trend detection across similar incidents

Integrates with:
- RootCauseAnalyzer for investigation data
- ImpactAnalysisEngine for blast radius
- DecisionMemory for knowledge capture
- BIDashboard for trend tracking

Usage:
    from core.postmortem_automator import get_postmortem_automator

    automator = get_postmortem_automator()
    p = automator.generate_postmortem(
        incident_type="broker_disconnect",
        incident_message="Connection refused: broker.zerodha.com:443",
        severity="CRITICAL",
    )
    print(p.title)
    print(p.lessons_learned)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

POSTMORTEM_TEMPLATES: dict[str, dict[str, Any]] = {
    "broker_disconnect": {
        "title_template": "Broker Connection Failure — {date}",
        "category": "Connectivity",
        "severity": "CRITICAL",
        "typical_impact": "Trading operations paused — manual intervention required",
        "common_action_items": [
            "Add broker health check with auto-reconnect",
            "Implement circuit breaker for broker API calls",
            "Create runbook for broker outage recovery",
            "Verify failover broker configuration",
        ],
    },
    "reconciliation_mismatch": {
        "title_template": "State Reconciliation Mismatch — {date}",
        "category": "Data Integrity",
        "severity": "HIGH",
        "typical_impact": "Position tracking desynchronized — verification required",
        "common_action_items": [
            "Add automated reconciliation at regular intervals",
            "Improve WAL journal for order tracking",
            "Add idempotency keys to all order submissions",
            "Implement state snapshot verification",
        ],
    },
    "stale_quote": {
        "title_template": "Stale Market Data Detected — {date}",
        "category": "Data Quality",
        "severity": "NORMAL",
        "typical_impact": "Signal quality degraded — no trades on stale data",
        "common_action_items": [
            "Add data staleness threshold and auto-fallback",
            "Implement WebSocket reconnection with exponential backoff",
            "Add data provider health metrics",
            "Verify yfinance rate limiting compliance",
        ],
    },
    "risk_breach": {
        "title_template": "Risk Limit Breach — {date}",
        "category": "Risk Management",
        "severity": "CRITICAL",
        "typical_impact": "Hard halt triggered — all trading paused",
        "common_action_items": [
            "Review risk limit configuration appropriateness",
            "Add pre-trade risk validation checks",
            "Implement gradual limit approach instead of hard threshold",
            "Add risk limit breach simulation testing",
        ],
    },
    "circuit_breaker": {
        "title_template": "Circuit Breaker Triggered — {date}",
        "category": "Reliability",
        "severity": "HIGH",
        "typical_impact": "Service degraded or paused — automatic recovery attempted",
        "common_action_items": [
            "Review circuit breaker threshold tuning",
            "Add half-open state for faster recovery",
            "Implement health check before circuit breaker reset",
            "Add circuit breaker metrics and alerting",
        ],
    },
    "db_failure": {
        "title_template": "Database Failure — {date}",
        "category": "Infrastructure",
        "severity": "HIGH",
        "typical_impact": "State persistence interrupted — some data may be lost",
        "common_action_items": [
            "Add database health monitoring and alerting",
            "Implement automated backup verification",
            "Configure WAL journal for crash recovery",
            "Add disk space monitoring and alerting",
        ],
    },
}


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class TimelineEvent:
    """An event in the incident timeline."""

    timestamp: float = 0.0
    event_type: str = ""  # DETECTION, INVESTIGATION, MITIGATION, RESOLUTION
    description: str = ""
    source: str = ""
    duration_minutes: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp).isoformat() if self.timestamp else "",
            "event_type": self.event_type,
            "description": self.description,
            "source": self.source,
            "duration_minutes": round(self.duration_minutes, 1),
        }


@dataclass
class LessonLearned:
    """A lesson learned from an incident."""

    category: str = ""  # PROCESS, TECHNOLOGY, PEOPLE, EXTERNAL
    description: str = ""
    recommendation: str = ""
    priority: str = "MEDIUM"  # CRITICAL, HIGH, MEDIUM, LOW
    automation_possible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "description": self.description,
            "recommendation": self.recommendation,
            "priority": self.priority,
            "automation_possible": self.automation_possible,
        }


@dataclass
class ActionItem:
    """An action item resulting from the postmortem."""

    description: str = ""
    owner: str = "system"
    priority: str = "MEDIUM"
    due_days: int = 30
    status: str = "OPEN"
    related_threat: str = ""
    mitre_technique: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "owner": self.owner,
            "priority": self.priority,
            "due_days": self.due_days,
            "status": self.status,
            "related_threat": self.related_threat,
            "mitre_technique": self.mitre_technique,
        }


@dataclass
class PostmortemDocument:
    """Complete postmortem document for an incident."""

    title: str = ""
    incident_id: str = ""
    incident_type: str = ""
    category: str = ""
    severity: str = "NORMAL"
    date: str = ""
    duration_minutes: float = 0.0
    summary: str = ""
    timeline: list[TimelineEvent] = field(default_factory=list)
    root_cause: str = ""
    root_cause_confidence: float = 0.0
    impact_description: str = ""
    affected_modules: list[str] = field(default_factory=list)
    resolution_steps: list[str] = field(default_factory=list)
    lessons_learned: list[LessonLearned] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    similar_incidents_count: int = 0
    trend: str = "FIRST_OCCURRENCE"  # FIRST_OCCURRENCE, RECURRING, INCREASING, DECREASING
    generated_by: str = "AI Postmortem Automator"
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        timeline = []
        for e in self.timeline:
            timeline.append(e.to_dict() if hasattr(e, 'to_dict') else e)
        lessons = []
        for lesson_item in self.lessons_learned:
            lessons.append(lesson_item.to_dict() if hasattr(lesson_item, 'to_dict') else lesson_item)
        actions = []
        for a in self.action_items:
            actions.append(a.to_dict() if hasattr(a, 'to_dict') else a)
        return {
            "title": self.title,
            "incident_id": self.incident_id,
            "incident_type": self.incident_type,
            "category": self.category,
            "severity": self.severity,
            "date": self.date,
            "duration_minutes": round(self.duration_minutes, 1),
            "summary": self.summary,
            "timeline": timeline,
            "root_cause": self.root_cause,
            "root_cause_confidence": round(self.root_cause_confidence, 2),
            "impact_description": self.impact_description,
            "affected_modules": self.affected_modules,
            "resolution_steps": self.resolution_steps,
            "lessons_learned": lessons,
            "action_items": actions,
            "similar_incidents_count": self.similar_incidents_count,
            "trend": self.trend,
            "generated_by": self.generated_by,
            "timestamp": self.timestamp,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            f"  POSTMORTEM: {self.title}",
            "═" * 60,
            f"  Incident ID: {self.incident_id}",
            f"  Type: {self.incident_type} ({self.category})",
            f"  Severity: {self.severity}",
            f"  Duration: {self.duration_minutes:.0f} min",
            f"  Trend: {self.trend}",
            "",
        ]
        lines.append(f"  Summary: {self.summary[:120]}")
        lines.append(f"  Root Cause: {self.root_cause[:120]}")
        if self.lessons_learned:
            lines.append("\n  Lessons Learned:")
            for _item in self.lessons_learned:
                lines.append(f"    [{_item.priority}] ({_item.category}) {_item.description}")
        if self.action_items:
            lines.append("\n  Action Items:")
            for a in self.action_items:
                lines.append(f"    [{a.priority}] {a.description} (due: {a.due_days}d)")
        lines.append("═" * 60)
        return "\n".join(lines)


@dataclass
class PostmortemReport:
    """Aggregated postmortem report."""

    timestamp: float = 0.0
    total_postmortems: int = 0
    postmortems: list[PostmortemDocument] = field(default_factory=list)
    by_category: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    open_action_items: int = 0
    completed_action_items: int = 0
    top_lessons: list[str] = field(default_factory=list)
    trend_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_postmortems": self.total_postmortems,
            "postmortems": [p.to_dict() for p in self.postmortems[-20:]],
            "by_category": self.by_category,
            "by_severity": self.by_severity,
            "open_action_items": self.open_action_items,
            "completed_action_items": self.completed_action_items,
            "top_lessons": self.top_lessons,
            "trend_summary": self.trend_summary,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  POSTMORTEM AUTOMATOR REPORT",
            "═" * 60,
            f"  Total Postmortems: {self.total_postmortems}",
            f"  Open Action Items: {self.open_action_items}",
            f"  Completed Action Items: {self.completed_action_items}",
            "",
        ]
        if self.by_category:
            lines.append("  By Category:")
            for cat, count in sorted(self.by_category.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"    {cat}: {count}")
        if self.by_severity:
            lines.append("  By Severity:")
            for sev, count in sorted(self.by_severity.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"    {sev}: {count}")
        if self.top_lessons:
            lines.append("  Top Lessons Learned:")
            for _item in self.top_lessons[:5]:
                lines.append(f"    • {_item}")
        if self.trend_summary:
            lines.append(f"\n  Trend: {self.trend_summary}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Postmortem Automator ──────────────────────────────────────────────────


class PostmortemAutomator:
    """Postmortem Automator — Auto-generated Incident Postmortems.

    Generates structured postmortem documents from incidents using
    data from RootCauseAnalyzer, ImpactAnalysisEngine, and historical
    patterns. Tracks action items, lessons learned, and trends.

    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._postmortems: list[PostmortemDocument] = []
        self._action_items: list[ActionItem] = []
        self._max_postmortems = 200
        self._persist_path = Path("json/postmortems.json")
        self._action_items_path = Path("json/action_items.json")
        self._load_all()

    # ── Public API ────────────────────────────────────────────────────────

    def generate_postmortem(
        self,
        incident_type: str,
        incident_message: str,
        severity: str = "NORMAL",
        stack_trace: str = "",
        module: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PostmortemDocument:
        """Generate a postmortem from an incident.

        Collects data from RootCauseAnalyzer, builds timeline,
        identifies lessons learned, and generates action items.

        Args:
            incident_type: Type of incident (e.g., 'broker_disconnect').
            incident_message: Human-readable error message.
            severity: Incident severity.
            stack_trace: Optional stack trace.
            module: Optional affected module.
            metadata: Optional additional context.

        Returns:
            PostmortemDocument with full postmortem.
        """
        time.time()
        now = datetime.utcnow()
        doc = PostmortemDocument(
            incident_id=f"PM-{int(time.time())}",
            incident_type=incident_type,
            severity=severity,
            date=now.isoformat(),
            timestamp=time.time(),
        )

        # 1. Use template if available
        template = POSTMORTEM_TEMPLATES.get(incident_type, {})
        doc.title = (template.get("title_template", "Incident Postmortem — {date}")
                     .format(date=now.strftime("%Y-%m-%d")))
        doc.category = template.get("category", "Operational")

        # 2. Collect root cause data from RootCauseAnalyzer
        rca_result = self._collect_root_cause(incident_type, incident_message, stack_trace, module)
        if rca_result:
            doc.root_cause = rca_result.get("probable_cause", "Unknown")
            doc.root_cause_confidence = rca_result.get("confidence", 0.0)
            doc.affected_modules = rca_result.get("impacted_modules", [])
            doc.resolution_steps = rca_result.get("recovery_actions", [])

        # 4. Determine duration from metadata (before building timeline so base_ts uses it)
        duration_data = metadata.get("duration_minutes", 30) if metadata else 30
        if isinstance(duration_data, (int, float)):
            doc.duration_minutes = float(duration_data)

        # 3. Build timeline (now uses correct duration from metadata)
        doc.timeline = self._build_timeline(doc, rca_result)

        # 5. Ensure duration is positive (at least from timeline)
        if doc.timeline:
            first = doc.timeline[0].timestamp
            last = doc.timeline[-1].timestamp
            timeline_duration = (last - first) / 60.0
            if timeline_duration > 0:
                doc.duration_minutes = timeline_duration

        # 6. Generate summary
        doc.summary = self._generate_summary(doc, incident_message)

        # 6. Generate impact description
        doc.impact_description = template.get("typical_impact",
            f"Incident affecting {incident_type} module(s)")

        # 7. Generate lessons learned
        doc.lessons_learned = self._generate_lessons(doc, template)

        # 8. Generate action items
        doc.action_items = self._generate_action_items(doc, template)
        self._action_items.extend(doc.action_items)

        # 9. Check trend
        doc.similar_incidents_count = self._count_similar(incident_type)
        doc.trend = self._determine_trend(incident_type, doc.similar_incidents_count)

        # Save
        with self._lock:
            self._postmortems.append(doc)
            if len(self._postmortems) > self._max_postmortems:
                self._postmortems = self._postmortems[-self._max_postmortems:]
            self._persist_all()

        return doc

    def get_postmortem(self, incident_id: str) -> PostmortemDocument | None:
        """Get a specific postmortem by ID."""
        with self._lock:
            for p in self._postmortems:
                if p.incident_id == incident_id:
                    return p
            return None

    def get_all_postmortems(self, limit: int = 50) -> list[PostmortemDocument]:
        """Get all postmortems, most recent first."""
        with self._lock:
            return list(reversed(self._postmortems[-limit:]))

    def get_action_items(self, status: str = "OPEN") -> list[ActionItem]:
        """Get action items, optionally filtered by status."""
        with self._lock:
            return [a for a in self._action_items if status in ("ALL", a.status)]

    def complete_action_item(self, description: str) -> bool:
        """Mark an action item as completed."""
        with self._lock:
            for a in self._action_items:
                if a.description == description and a.status == "OPEN":
                    a.status = "COMPLETED"
                    self._persist_action_items()
                    return True
            return False

    def get_report(self) -> PostmortemReport:
        """Generate an aggregated postmortem report."""
        with self._lock:
            report = PostmortemReport(
                timestamp=time.time(),
                total_postmortems=len(self._postmortems),
                postmortems=list(self._postmortems[-20:]),
            )

            # By category
            by_cat: dict[str, int] = {}
            for p in self._postmortems:
                by_cat[p.category] = by_cat.get(p.category, 0) + 1
            report.by_category = by_cat

            # By severity
            by_sev: dict[str, int] = {}
            for p in self._postmortems:
                by_sev[p.severity] = by_sev.get(p.severity, 0) + 1
            report.by_severity = by_sev

            # Action items stats
            report.open_action_items = sum(1 for a in self._action_items if a.status == "OPEN")
            report.completed_action_items = sum(1 for a in self._action_items if a.status == "COMPLETED")

            # Top lessons
            all_lessons: list[str] = []
            for p in self._postmortems:
                for _item in p.lessons_learned:
                    if _item.priority in ("CRITICAL", "HIGH"):
                        all_lessons.append(_item.description)
            report.top_lessons = all_lessons[:10]

            # Trend summary
            categories = len(by_cat)
            total = len(self._postmortems)
            if total > 0:
                report.trend_summary = (
                    f"{total} postmortems across {categories} categories | "
                    f"{report.open_action_items} open action items | "
                    f"{report.completed_action_items} completed"
                )

            return report

    def get_stats(self) -> dict[str, Any]:
        """Get postmortem automator statistics."""
        with self._lock:
            return {
                "total_postmortems": len(self._postmortems),
                "total_action_items": len(self._action_items),
                "open_action_items": sum(1 for a in self._action_items if a.status == "OPEN"),
                "completed_action_items": sum(1 for a in self._action_items if a.status == "COMPLETED"),
                "latest_postmortem": self._postmortems[-1].to_dict() if self._postmortems else None,
                "categories": list(set(p.category for p in self._postmortems)),
                "incident_types": list(set(p.incident_type for p in self._postmortems)),
            }

    def clear_all(self) -> None:
        """Clear all postmortem data."""
        with self._lock:
            self._postmortems.clear()
            self._action_items.clear()
            for p in [self._persist_path, self._action_items_path]:
                if p.exists():
                    p.unlink()

    # ── Data Collection ─────────────────────────────────────────────────

    def _collect_root_cause(
        self, incident_type: str, incident_message: str,
        stack_trace: str, module: str,
    ) -> dict[str, Any] | None:
        """Collect root cause data from RootCauseAnalyzer."""
        try:
            from core.root_cause_analyzer import get_root_cause_analyzer
            rca = get_root_cause_analyzer()
            result = rca.investigate(
                error_type=incident_type,
                error_message=incident_message,
                stack_trace=stack_trace,
                module=module,
            )
            return {
                "probable_cause": result.probable_cause,
                "confidence": result.confidence,
                "impacted_modules": result.impacted_modules,
                "recovery_actions": [result.recommended_fix] if result.recommended_fix else [],
            }
        except ImportError:
            return None

    def _build_timeline(
        self, doc: PostmortemDocument, rca_result: dict[str, Any] | None
    ) -> list[TimelineEvent]:
        """Build incident timeline from available data."""
        timeline: list[TimelineEvent] = []
        base_ts = doc.timestamp - doc.duration_minutes * 60

        # Detection
        timeline.append(TimelineEvent(
            timestamp=base_ts,
            event_type="DETECTION",
            description=f"Incident detected: {doc.incident_type}",
            source="system",
        ))

        # Investigation
        timeline.append(TimelineEvent(
            timestamp=base_ts + 60,
            event_type="INVESTIGATION",
            description="Root cause analysis initiated",
            source="RootCauseAnalyzer",
        ))

        # Resolution
        if doc.resolution_steps:
            res_ts = base_ts + doc.duration_minutes * 60 * 0.5
            for i, step in enumerate(doc.resolution_steps[:3]):
                timeline.append(TimelineEvent(
                    timestamp=res_ts + (i * 60),
                    event_type="MITIGATION" if i < len(doc.resolution_steps) - 1 else "RESOLUTION",
                    description=step[:120],
                    source="system",
                ))

        return timeline

    def _generate_summary(self, doc: PostmortemDocument, incident_message: str) -> str:
        """Generate a human-readable incident summary."""
        return (
            f"A {doc.severity} {doc.incident_type} incident occurred on {doc.date}. "
            f"Root cause identified as: {doc.root_cause[:80]}. "
            f"Duration: {doc.duration_minutes:.0f} minutes. "
            f"{len(doc.action_items)} action items generated to prevent recurrence."
        )

    def _generate_lessons(
        self, doc: PostmortemDocument, template: dict[str, Any]
    ) -> list[LessonLearned]:
        """Generate lessons learned from the incident."""
        lessons: list[LessonLearned] = []

        lesson_map: dict[str, list[tuple[str, str, str, bool]]] = {
            "broker_disconnect": [
                ("PROCESS", "Broker dependency creates single point of failure",
                 "Implement broker-agnostic architecture with automatic failover", True),
                ("TECHNOLOGY", "Connection recovery was not automatic",
                 "Add exponential backoff reconnection with health checks", True),
            ],
            "reconciliation_mismatch": [
                ("PROCESS", "State verification occurs only at specific points",
                 "Implement continuous reconciliation at shorter intervals", True),
                ("TECHNOLOGY", "Retry logic can cause duplicate submissions",
                 "Add idempotency keys to all broker operations", True),
            ],
            "stale_quote": [
                ("TECHNOLOGY", "No staleness detection on data feed",
                 "Add data freshness monitoring with automatic source switching", True),
                ("PROCESS", "Single data provider creates reliability risk",
                 "Add multiple data provider fallback chain", True),
            ],
            "risk_breach": [
                ("PROCESS", "Risk limit was not appropriate for market conditions",
                 "Implement dynamic risk limits based on volatility regime", False),
                ("TECHNOLOGY", "No gradual limit warning before hard halt",
                 "Add progressive limit warnings before hard halt", True),
            ],
        }

        for category, description, recommendation, auto_possible in lesson_map.get(doc.incident_type, []):
            lessons.append(LessonLearned(
                category=category,
                description=description,
                recommendation=recommendation,
                priority="HIGH",
                automation_possible=auto_possible,
            ))

        # Generic lesson if none available
        if not lessons:
            lessons.append(LessonLearned(
                category="TECHNOLOGY",
                description=f"Incident of type '{doc.incident_type}' was not fully mitigated",
                recommendation=f"Review and implement automated handling for {doc.incident_type}",
                priority="MEDIUM",
                automation_possible=True,
            ))

        return lessons

    def _generate_action_items(
        self, doc: PostmortemDocument, template: dict[str, Any]
    ) -> list[ActionItem]:
        """Generate action items from the postmortem."""
        items: list[ActionItem] = []

        # From lesson recommendations
        for lesson in doc.lessons_learned:
            if lesson.automation_possible:
                items.append(ActionItem(
                    description=lesson.recommendation,
                    priority=lesson.priority,
                    due_days=14 if lesson.priority == "CRITICAL" else 30,
                ))

        # Common action items from template
        for action_desc in template.get("common_action_items", []):
            items.append(ActionItem(
                description=action_desc,
                priority="HIGH",
                due_days=30,
            ))

        # Deduplicate by description
        seen: set[str] = set()
        unique_items: list[ActionItem] = []
        for item in items:
            if item.description not in seen:
                unique_items.append(item)
                seen.add(item.description)

        return unique_items[:10]

    def _count_similar(self, incident_type: str) -> int:
        """Count similar incidents in postmortem history."""
        with self._lock:
            return sum(1 for p in self._postmortems if p.incident_type == incident_type)

    def _determine_trend(self, incident_type: str, count: int) -> str:
        """Determine if this is a new, recurring, or growing pattern."""
        if count <= 1:
            return "FIRST_OCCURRENCE"
        elif count <= 3:
            return "RECURRING"
        # Check if frequency is increasing
        with self._lock:
            recent = [p for p in self._postmortems if p.incident_type == incident_type]
            if len(recent) >= 4:
                # Compare last 2 vs prior 2
                last_two = recent[-2:]
                prior_two = recent[-4:-2]
                if len(last_two) >= 2 and len(prior_two) >= 2:
                    last_span = last_two[-1].timestamp - last_two[0].timestamp
                    prior_span = prior_two[-1].timestamp - prior_two[0].timestamp
                    if prior_span > 0 and last_span < prior_span * 0.5:
                        return "INCREASING"
            return "RECURRING"

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist_all(self) -> None:
        """Persist all postmortem data to disk."""
        self._persist_postmortems()
        self._persist_action_items()

    def _persist_postmortems(self) -> None:
        """Persist postmortem documents."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [p.to_dict() for p in self._postmortems[-100:]]
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[PM] Postmortems persist: %s", exc)

    def _persist_action_items(self) -> None:
        """Persist action items."""
        try:
            self._action_items_path.parent.mkdir(parents=True, exist_ok=True)
            data = [a.to_dict() for a in self._action_items]
            self._action_items_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[PM] Action items persist: %s", exc)

    def _load_all(self) -> None:
        """Load all postmortem data from disk."""
        self._load_postmortems()
        self._load_action_items()

    def _load_postmortems(self) -> None:
        """Load postmortems from disk, reconstructing nested dataclasses."""
        try:
            if self._persist_path.is_file():
                data = json.loads(self._persist_path.read_text(encoding="utf-8"))
                for item in data:
                    try:
                        fields = {k: v for k, v in item.items()
                                  if k in PostmortemDocument.__dataclass_fields__}
                        # Reconstruct nested dataclass objects
                        if "timeline" in fields and isinstance(fields["timeline"], list):
                            fields["timeline"] = [
                                TimelineEvent(**{k: v for k, v in e.items()
                                                  if k in TimelineEvent.__dataclass_fields__})
                                if isinstance(e, dict) else e
                                for e in fields["timeline"]
                            ]
                        if "lessons_learned" in fields and isinstance(fields["lessons_learned"], list):
                            fields["lessons_learned"] = [
                                LessonLearned(**{k: v for k, v in _item.items()
                                                  if k in LessonLearned.__dataclass_fields__})
                                if isinstance(_item, dict) else _item
                                for _item in fields["lessons_learned"]
                            ]
                        if "action_items" in fields and isinstance(fields["action_items"], list):
                            fields["action_items"] = [
                                ActionItem(**{k: v for k, v in a.items()
                                              if k in ActionItem.__dataclass_fields__})
                                if isinstance(a, dict) else a
                                for a in fields["action_items"]
                            ]
                        p = PostmortemDocument(**fields)
                        self._postmortems.append(p)
                    except (TypeError, ValueError) as exc:
                        _log.debug("[PM] Load skip: %s", exc)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[PM] Load failed: %s", exc)

    def _load_action_items(self) -> None:
        """Load action items from disk."""
        try:
            if self._action_items_path.is_file():
                data = json.loads(self._action_items_path.read_text(encoding="utf-8"))
                for item in data:
                    try:
                        a = ActionItem(**{k: v for k, v in item.items()
                                           if k in ActionItem.__dataclass_fields__})
                        self._action_items.append(a)
                    except (TypeError, ValueError) as exc:
                        _log.debug("[PM] Action item load skip: %s", exc)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[PM] Action items load failed: %s", exc)


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.postmortem_automator",
        description="Postmortem Automator — Generate incident postmortems",
    )
    ap.add_argument("--generate", type=str, help="Generate postmortem for incident type")
    ap.add_argument("--message", type=str, default="", help="Incident message")
    ap.add_argument("--severity", type=str, default="HIGH", help="Severity (NORMAL/HIGH/CRITICAL)")
    ap.add_argument("--list", action="store_true", help="List all postmortems")
    ap.add_argument("--report", action="store_true", help="Show aggregated report")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    auto = get_postmortem_automator()

    if args.generate:
        pm = auto.generate_postmortem(
            incident_type=args.generate,
            incident_message=args.message or f"CLI test: {args.generate}",
            severity=args.severity,
        )
        if args.json:
            import json
            print(json.dumps(pm.to_dict(), indent=2))
        else:
            print(pm.summary_text())
        return

    if args.list:
        pms = auto.get_all_postmortems()
        if args.json:
            import json
            print(json.dumps([p.to_dict() for p in pms], indent=2))
        else:
            print(f"Total Postmortems: {len(pms)}")
            for p in pms[-10:]:
                print(f"  [{p.severity}] {p.title}")
                print(f"       {p.summary[:80]}...")
        return

    if args.report:
        report = auto.get_report()
        if args.json:
            import json
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.summary_text())
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()

# ── Singleton ──────────────────────────────────────────────────────────────

_automator: PostmortemAutomator | None = None
_automator_lock = threading.RLock()


def get_postmortem_automator() -> PostmortemAutomator:
    """Get the singleton PostmortemAutomator instance."""
    global _automator
    with _automator_lock:
        if _automator is None:
            _automator = PostmortemAutomator()
        return _automator


def reset_postmortem_automator() -> None:
    """Force-reset singleton (for testing)."""
    global _automator
    with _automator_lock:
        _automator = None


__all__ = [
    "ActionItem",
    "LessonLearned",
    "PostmortemAutomator",
    "PostmortemDocument",
    "PostmortemReport",
    "TimelineEvent",
    "get_postmortem_automator",
    "reset_postmortem_automator",
]
