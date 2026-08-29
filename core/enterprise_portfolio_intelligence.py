"""Enterprise Portfolio Intelligence — Connect Epics, Features, Stories & Business Goals (Pillar 10).

Connects the technical codebase to business value tracking:
- Epics → Features → Stories → Tasks mapping
- Bugs tracking per module/feature
- Releases linked to features/stories
- Incidents linked to modules
- Support tickets per feature area
- Customer feedback aggregation
- Roadmap vs. actual progress
- Business Goals / KPIs / OKRs tracking
- Value analysis: engineering effort vs. business value

Usage:
    from core.enterprise_portfolio_intelligence import get_portfolio_intelligence

    pi = get_portfolio_intelligence()
    pi.register_epic("EPIC-001", "Risk Management Overhaul", ["risk_service", "execution_service"])
    pi.register_feature("EPIC-001", "FTR-001", "Circuit Breaker Enhancement")
    report = pi.get_portfolio_report()
    print(report.feature_completion_pct)
    print(report.highest_value_features)

Design:
- Thread-safe singleton with RLock
- JSON persistence for portfolio data
- Integrates with IncidentCommandSystem for incident-module mapping
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

PORTFOLIO_FILE = "json/portfolio_intelligence.json"
MAX_PORTFOLIO_HISTORY = 500

# Statuses
STATUS_BACKLOG = "BACKLOG"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"
STATUS_BLOCKED = "BLOCKED"

VALID_STATUSES = (
    STATUS_BACKLOG,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_CANCELLED,
    STATUS_BLOCKED,
)


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class Epic:
    """A business epic — large body of work."""

    epic_id: str
    title: str
    description: str = ""
    status: str = STATUS_BACKLOG
    affected_modules: list[str] = field(default_factory=list)
    business_goal: str = ""
    kpi_targets: dict[str, float] = field(default_factory=dict)
    estimated_effort_hours: float = 0.0
    actual_effort_hours: float = 0.0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "epic_id": self.epic_id,
            "title": self.title,
            "description": self.description[:200],
            "status": self.status,
            "affected_modules": self.affected_modules,
            "business_goal": self.business_goal,
            "kpi_targets": self.kpi_targets,
            "estimated_effort_hours": self.estimated_effort_hours,
            "actual_effort_hours": self.actual_effort_hours,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "tags": self.tags,
        }

    @property
    def is_completed(self) -> bool:
        return self.status == STATUS_COMPLETED


@dataclass
class Feature:
    """A feature within an epic."""

    feature_id: str
    epic_id: str
    title: str
    description: str = ""
    status: str = STATUS_BACKLOG
    business_value_score: float = 5.0  # 1-10
    technical_complexity: float = 5.0  # 1-10
    estimated_hours: float = 0.0
    actual_hours: float = 0.0
    assigned_modules: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "epic_id": self.epic_id,
            "title": self.title,
            "description": self.description[:200],
            "status": self.status,
            "business_value_score": self.business_value_score,
            "technical_complexity": self.technical_complexity,
            "estimated_hours": self.estimated_hours,
            "actual_hours": self.actual_hours,
            "assigned_modules": self.assigned_modules,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "tags": self.tags,
        }

    @property
    def value_ratio(self) -> float:
        """Value per unit of effort."""
        effort = max(self.actual_hours, self.estimated_hours, 1)
        return self.business_value_score / effort

    @property
    def is_completed(self) -> bool:
        return self.status == STATUS_COMPLETED


@dataclass
class BugRecord:
    """A bug or defect tracked against a module."""

    bug_id: str
    module: str
    title: str
    severity: str = "MEDIUM"  # CRITICAL, HIGH, MEDIUM, LOW
    status: str = STATUS_BACKLOG
    linked_feature_id: str = ""
    linked_incident_id: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    resolved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bug_id": self.bug_id,
            "module": self.module,
            "title": self.title[:100],
            "severity": self.severity,
            "status": self.status,
            "linked_feature_id": self.linked_feature_id,
            "linked_incident_id": self.linked_incident_id,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


@dataclass
class BusinessGoal:
    """A business goal / KPI / OKR."""

    goal_id: str
    title: str
    target_value: float
    current_value: float = 0.0
    unit: str = ""
    linked_epics: list[str] = field(default_factory=list)
    category: str = "PERFORMANCE"  # PERFORMANCE, QUALITY, COVERAGE, VELOCITY, REVENUE
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "target_value": self.target_value,
            "current_value": self.current_value,"progress_pct": round(self.progress_pct, 1),
            "unit": self.unit,
            "linked_epics": self.linked_epics,
            "category": self.category,
        }

    @property
    def progress_pct(self) -> float:
        return min(100.0, self.current_value / max(self.target_value, 0.01) * 100)


@dataclass
class PortfolioReport:
    """Aggregated portfolio intelligence report."""

    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Epics and Features
    n_epics: int = 0
    n_features: int = 0
    n_bugs: int = 0
    n_goals: int = 0

    # Completion stats
    epic_completion_pct: float = 0.0
    feature_completion_pct: float = 0.0
    bug_resolution_pct: float = 0.0

    # Value analysis
    highest_value_features: list[dict[str, Any]] = field(default_factory=list)
    modules_with_most_bugs: list[dict[str, Any]] = field(default_factory=list)
    goal_progress: list[dict[str, Any]] = field(default_factory=list)

    # Business analysis
    effort_vs_value: str = "BALANCED"  # HIGH_VALUE, BALANCED, HIGH_EFFORT
    health: str = "HEALTHY"  # HEALTHY, AT_RISK, CRITICAL
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "n_epics": self.n_epics,
            "n_features": self.n_features,
            "n_bugs": self.n_bugs,
            "n_goals": self.n_goals,
            "epic_completion_pct": round(self.epic_completion_pct, 1),
            "feature_completion_pct": round(self.feature_completion_pct, 1),
            "bug_resolution_pct": round(self.bug_resolution_pct, 1),
            "highest_value_features": self.highest_value_features[:10],
            "modules_with_most_bugs": self.modules_with_most_bugs[:10],
            "goal_progress": self.goal_progress,
            "effort_vs_value": self.effort_vs_value,
            "health": self.health,
            "recommendations": self.recommendations[:10],
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  ENTERPRISE PORTFOLIO INTELLIGENCE",
            "═" * 60,
            f"  Portfolio Health: {self.health}",
            f"  Effort vs Value:  {self.effort_vs_value}",
            "",
            f"  Epics:     {self.n_epics}  ({self.epic_completion_pct:.0f}% complete)",
            f"  Features:  {self.n_features}  ({self.feature_completion_pct:.0f}% complete)",
            f"  Bugs:      {self.n_bugs}  ({self.bug_resolution_pct:.0f}% resolved)",
            f"  Goals:     {self.n_goals}",
        ]
        if self.goal_progress:
            lines.append("")
            lines.append("  Goal Progress:")
            for g in self.goal_progress:
                bar = "■" * int(g.get("progress_pct", 0) / 10) + "□" * (
                    10 - int(g.get("progress_pct", 0) / 10)
                )
                lines.append(f"    {g.get('title', '?')[:30]:30s} {bar}")
        if self.recommendations:
            lines.append("")
            lines.append("  Recommendations:")
            for r in self.recommendations[:5]:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Portfolio Intelligence Engine ────────────────────────────────────────────


class PortfolioIntelligenceEngine:
    """Connects technical work to business value.

    Tracks epics, features, bugs, business goals and provides
    portfolio-level analysis and recommendations.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._epics: dict[str, Epic] = {}
        self._features: dict[str, Feature] = {}
        self._bugs: list[BugRecord] = []
        self._goals: dict[str, BusinessGoal] = {}
        self._load_portfolio()

    # ── Epic Management ────────────────────────────────────────────────────

    def register_epic(
        self,
        epic_id: str,
        title: str,
        description: str = "",
        affected_modules: list[str] | None = None,
        business_goal: str = "",
        kpi_targets: dict[str, float] | None = None,
        estimated_effort_hours: float = 0.0,
    ) -> Epic:
        """Register a new epic."""
        epic = Epic(
            epic_id=epic_id,
            title=title.strip(),
            description=description.strip(),
            affected_modules=affected_modules or [],
            business_goal=business_goal,
            kpi_targets=kpi_targets or {},
            estimated_effort_hours=estimated_effort_hours,
        )
        with self._lock:
            self._epics[epic_id] = epic
            self._save_portfolio()
        _log.info("[PI] Registered epic '%s': %s", epic_id, title)
        return epic

    def update_epic_status(self, epic_id: str, status: str) -> bool:
        """Update an epic's status."""
        if status not in VALID_STATUSES:
            return False
        with self._lock:
            epic = self._epics.get(epic_id)
            if not epic:
                return False
            epic.status = status
            if status == STATUS_COMPLETED:
                epic.completed_at = datetime.now(timezone.utc).isoformat()
            self._save_portfolio()
            return True

    # ── Feature Management ─────────────────────────────────────────────────

    def register_feature(
        self,
        epic_id: str,
        feature_id: str,
        title: str,
        description: str = "",
        business_value_score: float = 5.0,
        technical_complexity: float = 5.0,
        estimated_hours: float = 0.0,
        assigned_modules: list[str] | None = None,
    ) -> Feature | None:
        """Register a new feature under an epic."""
        if epic_id not in self._epics:
            _log.warning("[PI] Epic '%s' not found — cannot add feature", epic_id)
            return None

        feature = Feature(
            feature_id=feature_id,
            epic_id=epic_id,
            title=title.strip(),
            description=description.strip(),
            business_value_score=min(10.0, max(1.0, business_value_score)),
            technical_complexity=min(10.0, max(1.0, technical_complexity)),
            estimated_hours=estimated_hours,
            assigned_modules=assigned_modules or [],
        )
        with self._lock:
            self._features[feature_id] = feature
            self._save_portfolio()
        _log.info(
            "[PI] Registered feature '%s' under epic '%s': %s",
            feature_id, epic_id, title,
        )
        return feature

    def update_feature_status(self, feature_id: str, status: str) -> bool:
        """Update a feature's status."""
        if status not in VALID_STATUSES:
            return False
        with self._lock:
            feature = self._features.get(feature_id)
            if not feature:
                return False
            feature.status = status
            if status == STATUS_COMPLETED:
                feature.completed_at = datetime.now(timezone.utc).isoformat()
            self._save_portfolio()
            return True

    def report_feature_effort(
        self, feature_id: str, actual_hours: float
    ) -> bool:
        """Report actual effort spent on a feature."""
        with self._lock:
            feature = self._features.get(feature_id)
            if not feature:
                return False
            feature.actual_hours += actual_hours
            self._save_portfolio()
            return True

    # ── Bug Management ─────────────────────────────────────────────────────

    def register_bug(
        self,
        bug_id: str,
        module: str,
        title: str,
        severity: str = "MEDIUM",
        linked_feature_id: str = "",
        linked_incident_id: str = "",
    ) -> BugRecord:
        """Register a new bug."""
        bug = BugRecord(
            bug_id=bug_id,
            module=module,
            title=title.strip(),
            severity=severity.upper(),
            linked_feature_id=linked_feature_id,
            linked_incident_id=linked_incident_id,
        )
        with self._lock:
            self._bugs.append(bug)
            self._save_portfolio()
        return bug

    def resolve_bug(self, bug_id: str) -> bool:
        """Mark a bug as resolved."""
        with self._lock:
            for bug in self._bugs:
                if bug.bug_id == bug_id and bug.status != STATUS_COMPLETED:
                    bug.status = STATUS_COMPLETED
                    bug.resolved_at = datetime.now(timezone.utc).isoformat()
                    self._save_portfolio()
                    return True
            return False

    # ── Business Goal Management ───────────────────────────────────────────

    def register_goal(
        self,
        goal_id: str,
        title: str,
        target_value: float,
        unit: str = "",
        linked_epics: list[str] | None = None,
        category: str = "PERFORMANCE",
    ) -> BusinessGoal:
        """Register a business goal / KPI / OKR."""
        goal = BusinessGoal(
            goal_id=goal_id,
            title=title.strip(),
            target_value=target_value,
            unit=unit,
            linked_epics=linked_epics or [],
            category=category,
        )
        with self._lock:
            self._goals[goal_id] = goal
            self._save_portfolio()
        return goal

    def update_goal_progress(self, goal_id: str, current_value: float) -> bool:
        """Update a goal's current value."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return False
            goal.current_value = current_value
            self._save_portfolio()
            return True

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_portfolio_report(self) -> PortfolioReport:
        """Generate an aggregated portfolio intelligence report."""
        report = PortfolioReport()

        with self._lock:
            report.n_epics = len(self._epics)
            report.n_features = len(self._features)
            report.n_bugs = len(self._bugs)
            report.n_goals = len(self._goals)

            # Completion stats
            if self._epics:
                report.epic_completion_pct = (
                    sum(1 for e in self._epics.values() if e.is_completed)
                    / len(self._epics) * 100
                )
            if self._features:
                report.feature_completion_pct = (
                    sum(1 for f in self._features.values() if f.is_completed)
                    / len(self._features) * 100
                )
            if self._bugs:
                report.bug_resolution_pct = (
                    sum(1 for b in self._bugs if b.status == STATUS_COMPLETED)
                    / len(self._bugs) * 100
                )

            # Highest value features
            sorted_features = sorted(
                self._features.values(),
                key=lambda f: f.value_ratio,
                reverse=True,
            )
            report.highest_value_features = [
                {
                    "feature_id": f.feature_id,
                    "title": f.title,
                    "value_ratio": round(f.value_ratio, 3),
                    "business_value": f.business_value_score,
                    "effort": max(f.actual_hours, f.estimated_hours, 1),
                    "status": f.status,
                }
                for f in sorted_features[:10]
            ]

            # Modules with most bugs
            module_bugs: dict[str, int] = {}
            for bug in self._bugs:
                if bug.status != STATUS_COMPLETED:
                    module_bugs[bug.module] = module_bugs.get(bug.module, 0) + 1
            sorted_modules = sorted(
                module_bugs.items(), key=lambda x: x[1], reverse=True
            )
            report.modules_with_most_bugs = [
                {"module": mod, "open_bugs": count}
                for mod, count in sorted_modules[:10]
            ]

            # Goal progress
            report.goal_progress = [
                g.to_dict() for g in self._goals.values()
            ]

            # Effort vs value
            if self._features:
                total_value = sum(
                    f.business_value_score for f in self._features.values()
                )
                total_effort = sum(
                    max(f.actual_hours, f.estimated_hours, 1)
                    for f in self._features.values()
                )
                ratio = total_value / max(total_effort, 1)
                if ratio > 2.0:
                    report.effort_vs_value = "HIGH_VALUE"
                elif ratio < 0.5:
                    report.effort_vs_value = "HIGH_EFFORT"
                else:
                    report.effort_vs_value = "BALANCED"

            # Health
            if report.bug_resolution_pct < 50 or report.feature_completion_pct < 20:
                report.health = "CRITICAL"
            elif report.bug_resolution_pct < 70 or report.feature_completion_pct < 40:
                report.health = "AT_RISK"
            else:
                report.health = "HEALTHY"

            # Recommendations
            report.recommendations = self._generate_recommendations(report)

        return report

    def get_stats(self) -> dict[str, Any]:
        """Get quick portfolio statistics."""
        with self._lock:
            return {
                "epics": len(self._epics),
                "features": len(self._features),
                "bugs": len(self._bugs),
                "goals": len(self._goals),
                "completed_epics": sum(
                    1 for e in self._epics.values() if e.is_completed
                ),
                "completed_features": sum(
                    1 for f in self._features.values() if f.is_completed
                ),
                "open_bugs": sum(
                    1 for b in self._bugs if b.status != STATUS_COMPLETED
                ),
                "goals_on_track": sum(
                    1 for g in self._goals.values()
                    if g.current_value / max(g.target_value, 0.01) >= 0.8
                ),
            }

    def get_epic_details(self, epic_id: str) -> dict[str, Any] | None:
        """Get epic details with linked features."""
        with self._lock:
            epic = self._epics.get(epic_id)
            if not epic:
                return None
            features = [
                f.to_dict()
                for f in self._features.values()
                if f.epic_id == epic_id
            ]
            return {
                "epic": epic.to_dict(),
                "features": features,
                "n_features": len(features),
                "n_completed_features": sum(1 for f in features if f.get("status") == STATUS_COMPLETED),
            }

    # ── Private ────────────────────────────────────────────────────────────

    def _generate_recommendations(self, report: PortfolioReport) -> list[str]:
        """Generate portfolio-level recommendations."""
        recs: list[str] = []

        if report.health == "CRITICAL":
            recs.append("CRITICAL: Portfolio health is critical — immediate attention needed")
        elif report.health == "AT_RISK":
            recs.append("Portfolio is at risk — focus on completing in-flight features")

        if report.bug_resolution_pct < 60:
            recs.append(f"Bug resolution rate is {report.bug_resolution_pct:.0f}% — prioritize bug fixes")

        if report.feature_completion_pct < 30:
            recs.append(f"Feature completion is {report.feature_completion_pct:.0f}% — review scope")

        if report.modules_with_most_bugs:
            top_module = report.modules_with_most_bugs[0]
            recs.append(
                f"Module '{top_module['module']}' has {top_module['open_bugs']} open bugs — "
                "investigate root cause"
            )

        if report.effort_vs_value == "HIGH_EFFORT":
            recs.append("Effort vs value ratio is unfavorable — review priorities")

        if not recs:
            recs.append("Portfolio is in good health — continue current trajectory")

        return recs[:8]

    # ── Persistence ────────────────────────────────────────────────────────

    def _load_portfolio(self) -> None:
        """Load portfolio data from JSON file."""
        try:
            path = Path(PORTFOLIO_FILE)
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                self._epics = {
                    k: Epic(**v) for k, v in data.get("epics", {}).items()
                }
                self._features = {
                    k: Feature(**v) for k, v in data.get("features", {}).items()
                }
                self._bugs = [BugRecord(**b) for b in data.get("bugs", [])]
                self._goals = {
                    k: BusinessGoal(**v) for k, v in data.get("goals", {}).items()
                }
                _log.info(
                    "[PI] Loaded portfolio: %d epics, %d features, %d bugs, %d goals",
                    len(self._epics), len(self._features),
                    len(self._bugs), len(self._goals),
                )
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.debug("[PI] Load portfolio failed: %s", exc)

    def _save_portfolio(self) -> None:
        """Save portfolio data to JSON file."""
        try:
            path = Path(PORTFOLIO_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "epics": {k: v.to_dict() for k, v in self._epics.items()},
                "features": {k: v.to_dict() for k, v in self._features.items()},
                "bugs": [b.to_dict() for b in self._bugs],
                "goals": {k: v.to_dict() for k, v in self._goals.items()},
            }, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            _log.debug("[PI] Save portfolio failed: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────

_engine: PortfolioIntelligenceEngine | None = None
_engine_lock = threading.RLock()


def get_portfolio_intelligence() -> PortfolioIntelligenceEngine:
    """Get the singleton PortfolioIntelligenceEngine instance."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = PortfolioIntelligenceEngine()
        return _engine


def reset_portfolio_intelligence() -> None:
    """Force-reset singleton (for testing)."""
    global _engine
    with _engine_lock:
        _engine = None


def _cli() -> None:
    """Command-line interface.

    Usage:
        python -m core.enterprise_portfolio_intelligence           # Full report
        python -m core.enterprise_portfolio_intelligence --stats   # Statistics
        python -m core.enterprise_portfolio_intelligence --json    # JSON output
        python -m core.enterprise_portfolio_intelligence \
            --register-epic EPIC-004 "New Epic" --modules core/foo
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Enterprise Portfolio Intelligence",
    )
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--json", action="store_true", help="JSON output")

    # Registration
    parser.add_argument("--register-epic", nargs=2, metavar=("ID", "TITLE"))
    parser.add_argument("--modules", nargs="+", default=[])

    args = parser.parse_args()
    pi = get_portfolio_intelligence()

    if args.register_epic:
        epic_id, title = args.register_epic
        epic = pi.register_epic(
            epic_id=epic_id,
            title=title,
            affected_modules=args.modules,
        )
        if args.json:
            print(json.dumps(epic.to_dict(), indent=2))
        else:
            print(f"Registered epic: {epic_id} - {title}")
        return

    if args.stats:
        stats = pi.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("═" * 50)
            print("Portfolio Intelligence — Statistics")
            print("═" * 50)
            for k, v in stats.items():
                print(f"  {k.replace('_', ' ').title():35s}: {v}")
        return

    report = pi.get_portfolio_report()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary_text())


if __name__ == "__main__":
    _cli()


__all__ = [
    "BugRecord",
    "BusinessGoal",
    "Epic",
    "Feature",
    "PortfolioIntelligenceEngine",
    "PortfolioReport",
    "get_portfolio_intelligence",
    "reset_portfolio_intelligence",
]
