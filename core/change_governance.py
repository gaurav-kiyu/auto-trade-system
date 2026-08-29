"""Change Governance — Phase 28: Change Governance & Approval Workflow.

Tracks change requests (CRs) through their full lifecycle:
- Submit → Review → Approve/Reject → Deploy → Verify → Close
- Integrates with ChangeRiskScorer for automated risk scoring
- Provides approval chains, deployment tracking, and rollback management
- Links changes to incidents, releases, and tests

Usage:
    from core.change_governance import ChangeGovernanceEngine

    engine = ChangeGovernanceEngine()
    cr = engine.create_change(
        title="Update SL_PCT for NIFTY",
        description="Adjust stop-loss from 5% to 4.5% based on backtest",
        files_changed=["json/index_config.defaults.json"],
        author="quant-team",
        change_type="CONFIG",
    )
    engine.submit_for_review(cr.change_id)
    engine.approve(cr.change_id, reviewer="cto")

Design:
- Thread-safe singleton with RLock
- JSON persistence for change request history
- Integration with ChangeRiskScorer for automated risk scoring
- Configurable approval chains
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CHANGE_FILE = "json/change_governance.json"
MAX_CHANGE_HISTORY = 500

SUPPORTED_CHANGE_TYPES = (
    "CONFIG",       # Configuration change
    "STRATEGY",     # Strategy parameter change
    "RISK",         # Risk parameter change
    "BROKER",       # Broker adapter change
    "CORE",         # Core module change
    "UI",           # Dashboard/UI change
    "ML",           # ML model/feature change
    "INFRA",        # Infrastructure change
    "SECURITY",     # Security change
    "OTHER",        # Other
)


class ChangeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEPLOYED = "DEPLOYED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    ROLLED_BACK = "ROLLED_BACK"


class ChangePriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class ChangeEvent:
    """An event in a change request's lifecycle."""

    event_type: str      # SUBMITTED, APPROVED, REJECTED, DEPLOYED, etc.
    actor: str           # Who performed the action
    comment: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "actor": self.actor,
            "comment": self.comment,
            "timestamp": self.timestamp,
        }


@dataclass
class ChangeRequest:
    """A single change request with full lifecycle tracking."""

    change_id: str
    title: str
    description: str = ""
    change_type: str = "OTHER"
    priority: str = "MEDIUM"
    status: str = "DRAFT"
    author: str = ""
    reviewer: str = ""
    approver: str = ""
    files_changed: list[str] = field(default_factory=list)
    risk_level: str = "LOW"
    risk_score: float = 0.0
    risk_factors: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    linked_incidents: list[str] = field(default_factory=list)
    linked_release: str = ""
    rollback_plan: str = ""
    test_summary: str = ""
    events: list[ChangeEvent] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    deployed_at: float | None = None
    verified_at: float | None = None
    closed_at: float | None = None

    @property
    def is_approved(self) -> bool:
        return self.status in ("APPROVED", "DEPLOYED", "VERIFIED", "CLOSED")

    @property
    def is_deployable(self) -> bool:
        return self.status == "APPROVED"

    @property
    def is_open(self) -> bool:
        return self.status not in ("CLOSED", "ROLLED_BACK")

    def add_event(self, event_type: str, actor: str, comment: str = "") -> None:
        self.events.append(ChangeEvent(
            event_type=event_type, actor=actor, comment=comment,
        ))
        # Keep only last 20 events per change to bound persistence size
        if len(self.events) > 20:
            self.events = self.events[-20:]
        self.updated_at = time.time()
        if event_type == "DEPLOYED":
            self.deployed_at = time.time()
        elif event_type == "VERIFIED":
            self.verified_at = time.time()
        elif event_type in ("CLOSED", "ROLLED_BACK"):
            self.closed_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "title": self.title,
            "description": self.description[:500],
            "change_type": self.change_type,
            "priority": self.priority,
            "status": self.status,
            "author": self.author,
            "reviewer": self.reviewer,
            "approver": self.approver,
            "files_changed": self.files_changed,
            "risk_level": self.risk_level,
            "risk_score": round(self.risk_score, 3),
            "risk_factors": self.risk_factors[:5],
            "recommendations": self.recommendations[:5],
            "linked_incidents": self.linked_incidents,
            "linked_release": self.linked_release,
            "rollback_plan": self.rollback_plan[:500],
            "test_summary": self.test_summary[:500],
            "events": [e.to_dict() for e in self.events[-10:]],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ChangeGovernanceReport:
    """Aggregated change governance report."""

    n_changes: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    by_risk: dict[str, int] = field(default_factory=dict)
    open_count: int = 0
    pending_review: list[dict[str, Any]] = field(default_factory=list)
    recent_changes: list[dict[str, Any]] = field(default_factory=list)
    avg_approval_time_hours: float = 0.0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_changes": self.n_changes,
            "by_status": self.by_status,
            "by_type": self.by_type,
            "by_risk": self.by_risk,
            "open_count": self.open_count,
            "pending_review": self.pending_review[:10],
            "recent_changes": self.recent_changes[:10],
            "avg_approval_time_hours": round(self.avg_approval_time_hours, 1),
            "recommendations": self.recommendations[:8],
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  CHANGE GOVERNANCE REPORT",
            "═" * 60,
            f"  Total Changes: {self.n_changes}",
            f"  Open:          {self.open_count}",
            f"  Pending Review: {len(self.pending_review)}",
            f"  Avg Approval:  {self.avg_approval_time_hours:.1f} hours",
            "",
        ]
        if self.by_status:
            lines.append("  By Status:")
            for s, c in sorted(self.by_status.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"    {s}: {c}")
        if self.by_risk:
            lines.append("  By Risk Level:")
            for r, c in sorted(self.by_risk.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"    {r}: {c}")
        if self.pending_review:
            lines.append("\n  Pending Review:")
            for cr in self.pending_review[:5]:
                lines.append(f"    {cr['change_id']}: {cr['title'][:60]}")
        if self.recommendations:
            lines.append("\n  Recommendations:")
            for r in self.recommendations[:5]:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Change Governance Engine ────────────────────────────────────────────────


class ChangeGovernanceEngine:
    """Change governance and approval workflow engine.

    Manages:
    - Change request lifecycle (DRAFT → SUBMITTED → IN_REVIEW → APPROVED → DEPLOYED → VERIFIED → CLOSED)
    - Automated risk scoring via ChangeRiskScorer
    - Approval chains and reviewer assignment
    - Rollback plan tracking
    - Change-to-incident linking
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._changes: dict[str, ChangeRequest] = {}
        self._load_changes()

    # ── Change Lifecycle ──────────────────────────────────────────────────

    def create_change(
        self,
        title: str,
        description: str = "",
        change_type: str = "OTHER",
        priority: str = "MEDIUM",
        author: str = "",
        files_changed: list[str] | None = None,
        rollback_plan: str = "",
        test_summary: str = "",
    ) -> ChangeRequest:
        """Create a new change request.

        Args:
            title: Short descriptive title.
            description: Detailed description of the change.
            change_type: Category (CONFIG, STRATEGY, RISK, etc.).
            priority: LOW, MEDIUM, HIGH, CRITICAL.
            author: Person or team requesting the change.
            files_changed: List of files affected.
            rollback_plan: How to roll back if the change fails.
            test_summary: Summary of testing performed.

        Returns:
            ChangeRequest with assigned ID and initial risk assessment.
        """
        clean_type = change_type.upper()
        if clean_type not in SUPPORTED_CHANGE_TYPES:
            clean_type = "OTHER"

        clean_priority = priority.upper()
        if clean_priority not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            clean_priority = "MEDIUM"

        change_id = self._generate_id()
        change = ChangeRequest(
            change_id=change_id,
            title=title.strip(),
            description=description.strip(),
            change_type=clean_type,
            priority=clean_priority,
            author=author.strip(),
            files_changed=[f.strip() for f in (files_changed or [])],
            rollback_plan=rollback_plan.strip(),
            test_summary=test_summary.strip(),
        )

        # Perform automated risk assessment
        self._assess_risk(change)

        change.add_event("CREATED", author or "system", "Change request created")

        with self._lock:
            self._changes[change_id] = change
            self._save_changes()

        _log.info(
            "[CHANGE_GOV] Created %s: %s [%s/%s] risk=%s",
            change_id, title, clean_type, clean_priority, change.risk_level,
        )
        return change

    def submit_for_review(self, change_id: str, comment: str = "") -> bool:
        """Submit a change for review (DRAFT → SUBMITTED)."""
        with self._lock:
            change = self._changes.get(change_id)
            if not change or change.status != "DRAFT":
                return False
            change.status = "SUBMITTED"
            change.add_event("SUBMITTED", change.author or "system", comment)
            self._save_changes()
        return True

    def start_review(self, change_id: str, reviewer: str, comment: str = "") -> bool:
        """Start reviewing a change (SUBMITTED → IN_REVIEW)."""
        with self._lock:
            change = self._changes.get(change_id)
            if not change or change.status != "SUBMITTED":
                return False
            change.status = "IN_REVIEW"
            change.reviewer = reviewer
            change.add_event("IN_REVIEW", reviewer, comment)
            self._save_changes()
        return True

    def approve(self, change_id: str, reviewer: str, comment: str = "") -> bool:
        """Approve a change (IN_REVIEW → APPROVED)."""
        with self._lock:
            change = self._changes.get(change_id)
            if not change or change.status not in ("SUBMITTED", "IN_REVIEW"):
                return False
            change.status = "APPROVED"
            change.approver = reviewer
            change.add_event("APPROVED", reviewer, comment)
            self._save_changes()
        return True

    def reject(self, change_id: str, reviewer: str, comment: str = "") -> bool:
        """Reject a change (IN_REVIEW → REJECTED)."""
        with self._lock:
            change = self._changes.get(change_id)
            if not change or change.status not in ("SUBMITTED", "IN_REVIEW"):
                return False
            change.status = "REJECTED"
            change.add_event("REJECTED", reviewer, comment)
            self._save_changes()
        return True

    def deploy(self, change_id: str, actor: str, comment: str = "") -> bool:
        """Mark a change as deployed (APPROVED → DEPLOYED)."""
        with self._lock:
            change = self._changes.get(change_id)
            if not change or change.status != "APPROVED":
                return False
            change.status = "DEPLOYED"
            change.add_event("DEPLOYED", actor, comment)
            self._save_changes()
        return True

    def verify(self, change_id: str, actor: str, comment: str = "") -> bool:
        """Verify a deployment (DEPLOYED → VERIFIED)."""
        with self._lock:
            change = self._changes.get(change_id)
            if not change or change.status != "DEPLOYED":
                return False
            change.status = "VERIFIED"
            change.add_event("VERIFIED", actor, comment)
            self._save_changes()
        return True

    def close(self, change_id: str, actor: str, comment: str = "") -> bool:
        """Close a change (VERIFIED → CLOSED)."""
        with self._lock:
            change = self._changes.get(change_id)
            if not change or change.status != "VERIFIED":
                return False
            change.status = "CLOSED"
            change.add_event("CLOSED", actor, comment)
            self._save_changes()
        return True

    def rollback(self, change_id: str, actor: str, comment: str = "") -> bool:
        """Roll back a change (any active status → ROLLED_BACK)."""
        with self._lock:
            change = self._changes.get(change_id)
            if not change or change.status in ("CLOSED", "ROLLED_BACK"):
                return False
            change.status = "ROLLED_BACK"
            change.add_event("ROLLED_BACK", actor, comment)
            self._save_changes()
        return True

    # ── Query Methods ─────────────────────────────────────────────────────

    def get_change(self, change_id: str) -> ChangeRequest | None:
        """Get a change request by ID."""
        with self._lock:
            return self._changes.get(change_id)

    def get_changes_by_status(self, status: str) -> list[ChangeRequest]:
        """Get all changes in a given status."""
        clean_status = status.upper()
        with self._lock:
            return [c for c in self._changes.values() if c.status == clean_status]

    def get_open_changes(self) -> list[ChangeRequest]:
        """Get all open (non-closed) changes."""
        with self._lock:
            return [c for c in self._changes.values() if c.is_open]

    def get_pending_review(self) -> list[ChangeRequest]:
        """Get changes awaiting review."""
        with self._lock:
            return [
                c for c in self._changes.values()
                if c.status in ("SUBMITTED", "IN_REVIEW")
            ]

    def get_deployable_changes(self) -> list[ChangeRequest]:
        """Get approved changes ready for deployment."""
        with self._lock:
            return [c for c in self._changes.values() if c.is_deployable]

    def get_changes_by_author(self, author: str) -> list[ChangeRequest]:
        """Get all changes by an author."""
        with self._lock:
            return [c for c in self._changes.values() if c.author == author]

    def link_incident(self, change_id: str, incident_id: str) -> bool:
        """Link an incident to a change request."""
        with self._lock:
            change = self._changes.get(change_id)
            if not change:
                return False
            if incident_id not in change.linked_incidents:
                change.linked_incidents.append(incident_id)
                self._save_changes()
            return True

    def link_release(self, change_id: str, release_id: str) -> bool:
        """Link a change request to a release."""
        with self._lock:
            change = self._changes.get(change_id)
            if not change:
                return False
            change.linked_release = release_id
            self._save_changes()
            return True

    # ── Reporting ─────────────────────────────────────────────────────────

    def get_report(self) -> ChangeGovernanceReport:
        """Generate aggregated governance report."""
        report = ChangeGovernanceReport()

        with self._lock:
            report.n_changes = len(self._changes)

            by_status: dict[str, int] = {}
            by_type: dict[str, int] = {}
            by_risk: dict[str, int] = {}
            open_count = 0

            for c in self._changes.values():
                by_status[c.status] = by_status.get(c.status, 0) + 1
                by_type[c.change_type] = by_type.get(c.change_type, 0) + 1
                by_risk[c.risk_level] = by_risk.get(c.risk_level, 0) + 1
                if c.is_open:
                    open_count += 1

            report.by_status = by_status
            report.by_type = by_type
            report.by_risk = by_risk
            report.open_count = open_count

            # Pending review
            report.pending_review = [
                c.to_dict() for c in self._changes.values()
                if c.status in ("SUBMITTED", "IN_REVIEW")
            ]

            # Recent changes (last 10)
            sorted_changes = sorted(
                self._changes.values(),
                key=lambda c: c.created_at, reverse=True,
            )
            report.recent_changes = [c.to_dict() for c in sorted_changes[:10]]

            # Average approval time
            approval_times: list[float] = []
            for c in self._changes.values():
                if c.status in ("APPROVED", "DEPLOYED", "VERIFIED", "CLOSED", "ROLLED_BACK"):
                    for evt in c.events:
                        if evt.event_type == "APPROVED":
                            approval_time = evt.timestamp - c.created_at
                            if approval_time > 0:
                                approval_times.append(approval_time / 3600)
                            break
            if approval_times:
                report.avg_approval_time_hours = sum(approval_times) / len(approval_times)

            # Recommendations
            report.recommendations = self._generate_recommendations(by_status)

        return report

    def get_stats(self) -> dict[str, Any]:
        """Get quick governance statistics."""
        with self._lock:
            return {
                "n_changes": len(self._changes),
                "by_status": {
                    s: sum(1 for c in self._changes.values() if c.status == s)
                    for s in ChangeStatus.__members__
                },
                "by_risk": {
                    r: sum(1 for c in self._changes.values() if c.risk_level == r)
                    for r in RiskLevel.__members__
                },
                "open_changes": sum(1 for c in self._changes.values() if c.is_open),
                "pending_review": len(self.get_pending_review()),
                "approved_ready": len(self.get_deployable_changes()),
            }

    # ── Private ───────────────────────────────────────────────────────────

    def _assess_risk(self, change: ChangeRequest) -> None:
        """Perform automated risk assessment using ChangeRiskScorer."""
        try:
            from core.change_risk_scorer import get_risk_scorer
            scorer = get_risk_scorer()
            if change.files_changed:
                score = scorer.score_change(
                    files_changed=change.files_changed,
                    commit_message=change.title,
                )
                change.risk_level = score.risk_level
                change.risk_score = score.risk_score
                change.risk_factors = score.risk_factors
                change.recommendations = score.recommendations
            else:
                # Default risk based on change type
                type_risk: dict[str, str] = {
                    "RISK": "HIGH", "SECURITY": "HIGH", "BROKER": "HIGH",
                    "CORE": "MEDIUM", "STRATEGY": "MEDIUM", "CONFIG": "MEDIUM",
                    "ML": "MEDIUM", "INFRA": "MEDIUM", "UI": "LOW", "OTHER": "LOW",
                }
                change.risk_level = type_risk.get(change.change_type, "LOW")
                change.risk_score = {
                    "CRITICAL": 0.85, "HIGH": 0.65, "MEDIUM": 0.40, "LOW": 0.15,
                }.get(change.risk_level, 0.15)
        except Exception:
            _log.warning("[CHANGE_GOV] Risk assessment failed for %s: using type-based default",
                         change.change_id)
            type_risk = {
                "RISK": "HIGH", "SECURITY": "HIGH", "BROKER": "HIGH",
                "CORE": "MEDIUM", "STRATEGY": "MEDIUM", "CONFIG": "MEDIUM",
            }
            change.risk_level = type_risk.get(change.change_type, "LOW")

    def _generate_recommendations(self, by_status: dict[str, int]) -> list[str]:
        """Generate governance recommendations."""
        recs: list[str] = []
        pending = by_status.get("SUBMITTED", 0) + by_status.get("IN_REVIEW", 0)
        if pending > 5:
            recs.append(f"{pending} changes pending review — review queue is growing")
        if by_status.get("DRAFT", 0) > 3:
            recs.append(f"{by_status.get('DRAFT', 0)} changes in DRAFT — clean up abandoned requests")
        if by_status.get("ROLLED_BACK", 0) > 2:
            recs.append(f"{by_status.get('ROLLED_BACK', 0)} recent rollbacks — investigate root cause")
        if not recs:
            recs.append("Change governance is healthy")
        return recs[:8]

    def _generate_id(self) -> str:
        """Generate a unique change request ID."""
        ts = int(time.time() * 1000000)
        return f"CR-{ts:016x}"

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_changes(self) -> None:
        """Load changes from JSON file."""
        try:
            path = Path(CHANGE_FILE)
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                for cid, cdata in data.get("changes", {}).items():
                    try:
                        # Reconstruct ChangeEvent objects
                        events = cdata.pop("events", [])
                        change = ChangeRequest(**cdata)
                        change.events = [ChangeEvent(**e) for e in events]
                        self._changes[cid] = change
                    except (TypeError, ValueError) as exc:
                        _log.debug("[CHANGE_GOV] Load skip '%s': %s", cid, exc)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.debug("[CHANGE_GOV] Load failed: %s", exc)

    def _save_changes(self) -> None:
        """Save changes to JSON file."""
        try:
            path = Path(CHANGE_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "changes": {
                    cid: c.to_dict() for cid, c in self._changes.items()
                },
            }
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            _log.debug("[CHANGE_GOV] Save failed: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────

_engine: ChangeGovernanceEngine | None = None
_engine_lock = threading.RLock()


def get_change_governance() -> ChangeGovernanceEngine:
    """Get the singleton ChangeGovernanceEngine instance."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = ChangeGovernanceEngine()
        return _engine


def reset_change_governance() -> None:
    """Force-reset singleton (for testing)."""
    global _engine
    with _engine_lock:
        _engine = None


def _cli() -> None:
    """Command-line interface.

    Usage:
        python -m core.change_governance --report
        python -m core.change_governance --create "Update SL_PCT"
        python -m core.change_governance --approve CR-abc123
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Change Governance — Change Management & Approval Workflow",
    )
    parser.add_argument("--report", action="store_true", help="Show governance report")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--create", type=str, metavar="TITLE", help="Create a change request")
    parser.add_argument("--approve", type=str, metavar="CR_ID", help="Approve a change")
    parser.add_argument("--reject", type=str, metavar="CR_ID", help="Reject a change")
    parser.add_argument("--reviewer", default="reviewer", help="Reviewer name")
    parser.add_argument("--type", default="CONFIG", help="Change type")

    args = parser.parse_args()
    engine = get_change_governance()

    if args.create:
        cr = engine.create_change(
            title=args.create,
            change_type=args.type,
            author=args.reviewer,
        )
        engine.submit_for_review(cr.change_id, "Auto-submitted via CLI")
        if args.json:
            print(json.dumps(cr.to_dict(), indent=2))
        else:
            print(f"Created: {cr.change_id} — {cr.title} [{cr.risk_level}]")
        return

    if args.approve:
        success = engine.approve(args.approve, args.reviewer)
        print(f"Approved: {args.approve}" if success else f"Failed to approve: {args.approve}")
        return

    if args.reject:
        success = engine.reject(args.reject, args.reviewer)
        print(f"Rejected: {args.reject}" if success else f"Failed to reject: {args.reject}")
        return

    if args.stats:
        stats = engine.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("═" * 50)
            print("Change Governance — Statistics")
            print("═" * 50)
            for k, v in stats.items():
                print(f"  {k.replace('_', ' ').title():30s}: {v}")
        return

    report = engine.get_report()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary_text())


if __name__ == "__main__":
    _cli()


__all__ = [
    "ChangeGovernanceEngine",
    "ChangeGovernanceReport",
    "ChangeRequest",
    "ChangeEvent",
    "ChangePriority",
    "ChangeStatus",
    "RiskLevel",
    "get_change_governance",
    "reset_change_governance",
]
