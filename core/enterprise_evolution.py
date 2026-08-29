"""Enterprise Evolution Engine — Self-Improving Platform (Constitution v4.0 Layer 12).

Analyses the codebase, architecture, security posture, test coverage, and
technical debt to generate evolution proposals. Tracks improvement trends
and recommends strategic upgrades. This is Layer 12 — the capstone layer
that completes the autonomous enterprise feedback loop.

Constitution Layer: 12 — Enterprise Evolution
Constitution Principle: Continuous Improvement, Automate Everything

Usage:
    from core.enterprise_evolution import get_evolution_engine

    engine = get_evolution_engine()
    proposals = engine.analyze_and_propose()
    for p in proposals:
        print(f"  [{p.priority}] {p.title}")
    print(f"Improvement velocity: {engine.get_improvement_velocity():.1f}/month")
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────

PRIORITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "IDEA")
CATEGORIES = (
    "ARCHITECTURE",
    "SECURITY",
    "PERFORMANCE",
    "RELIABILITY",
    "TESTING",
    "OBSERVABILITY",
    "DOCUMENTATION",
    "TECHNICAL_DEBT",
    "DEPLOYMENT",
    "GOVERNANCE",
    "AUTOMATION",
    "SCALABILITY",
)


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class EvolutionProposal:
    """A proposed evolution for the platform."""

    title: str = ""
    description: str = ""
    category: str = "ARCHITECTURE"
    priority: str = "MEDIUM"
    effort_estimate: str = ""  # Small, Medium, Large, XLarge
    impact_estimate: str = ""  # Low, Medium, High, Critical
    affected_modules: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    evidence: str = ""
    created_at: float = 0.0
    proposal_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "title": self.title,
            "description": self.description[:300],
            "category": self.category,
            "priority": self.priority,
            "effort": self.effort_estimate,
            "impact": self.impact_estimate,
            "affected_modules": self.affected_modules[:10],
            "prerequisites": self.prerequisites,
            "evidence": self.evidence[:200],
            "created_at": self.created_at,
        }


@dataclass
class EvolutionProposalResult:
    """Result of analyzing and generating evolution proposals."""

    proposals: list[EvolutionProposal] = field(default_factory=list)
    total_proposals: int = 0
    categories_covered: list[str] = field(default_factory=list)
    top_priority: str = "LOW"
    generated_at: float = 0.0
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_proposals": self.total_proposals,
            "categories_covered": self.categories_covered,
            "top_priority": self.top_priority,
            "generated_at": self.generated_at,
            "duration_ms": round(self.duration_ms, 1),
            "proposals": [p.to_dict() for p in self.proposals],
        }


@dataclass
class EvolutionTrend:
    """Tracked improvement trend over time."""

    month: str = ""
    proposals_generated: int = 0
    proposals_accepted: int = 0
    proposals_implemented: int = 0
    avg_priority_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "month": self.month,
            "proposals_generated": self.proposals_generated,
            "proposals_accepted": self.proposals_accepted,
            "proposals_implemented": self.proposals_implemented,
            "avg_priority_score": round(self.avg_priority_score, 2),
        }


# ── Enterprise Evolution Engine ─────────────────────────────────────────────


class EnterpriseEvolutionEngine:
    """Layer 12 — Self-recommending improvement engine.

    Analyses all available data sources to generate evolution proposals
    that improve the platform's architecture, security, performance, and
    operational excellence.

    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._proposals: list[EvolutionProposal] = []
        self._history_path = Path("json/evolution_history.json")
        self._load_history()

    # ── Analysis ──────────────────────────────────────────────────────────

    def analyze_and_propose(self) -> list[EvolutionProposal]:
        """Run analysis across all categories and generate proposals.

        Returns:
            List of new EvolutionProposal objects.
        """
        t0 = time.time()
        proposals: list[EvolutionProposal] = []

        # Gather evidence from available sources
        evidence = self._gather_evidence()

        # Architecture proposals
        proposals.extend(self._analyze_architecture(evidence))

        # Security proposals
        proposals.extend(self._analyze_security(evidence))

        # Testing proposals
        proposals.extend(self._analyze_testing(evidence))

        # Observability proposals
        proposals.extend(self._analyze_observability(evidence))

        # Documentation proposals
        proposals.extend(self._analyze_documentation(evidence))

        # Governance proposals
        proposals.extend(self._analyze_governance(evidence))

        # Deduplicate by title
        seen_titles: set[str] = set()
        unique: list[EvolutionProposal] = []
        for p in proposals:
            if p.title not in seen_titles:
                seen_titles.add(p.title)
                unique.append(p)

        now = time.time()
        for i, p in enumerate(unique):
            p.proposal_id = f"EVO-{int(now)}-{i + 1}"
            p.created_at = now

        with self._lock:
            self._proposals.extend(unique)
            self._persist_history()

        _log.info("[EVOLUTION] Generated %d unique proposals in %.0fms", len(unique), (time.time() - t0) * 1000)
        return unique

    def get_proposals(self, category: str = "", priority: str = "",
                      limit: int = 50) -> list[EvolutionProposal]:
        """Get evolution proposals with optional filters."""
        with self._lock:
            proposals = list(self._proposals)
        if category:
            proposals = [p for p in proposals if p.category == category.upper()]
        if priority:
            proposals = [p for p in proposals if p.priority == priority.upper()]
        return sorted(proposals, key=lambda p: _priority_sort_key(p.priority))[:limit]

    def get_report(self) -> EvolutionProposalResult:
        """Generate aggregated evolution report."""
        with self._lock:
            proposals = list(self._proposals)

        categories = sorted(set(p.category for p in proposals))
        priorities = [p.priority for p in proposals]
        top_priority = "LOW"
        for p in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "IDEA"):
            if p in priorities:
                top_priority = p
                break

        return EvolutionProposalResult(
            proposals=proposals[:50],
            total_proposals=len(proposals),
            categories_covered=categories,
            top_priority=top_priority,
            generated_at=time.time(),
        )

    def get_improvement_velocity(self) -> float:
        """Compute improvement velocity (proposals per month over last 90 days)."""
        with self._lock:
            cutoff = time.time() - (90 * 86400)
            recent = [p for p in self._proposals if p.created_at >= cutoff]
            return len(recent) / 3.0  # ~90 days = 3 months

    def get_stats(self) -> dict[str, Any]:
        """Get evolution engine statistics."""
        with self._lock:
            total = len(self._proposals)
            by_category: dict[str, int] = {}
            by_priority: dict[str, int] = {}
            for p in self._proposals:
                by_category[p.category] = by_category.get(p.category, 0) + 1
                by_priority[p.priority] = by_priority.get(p.priority, 0) + 1

            return {
                "total_proposals": total,
                "by_category": by_category,
                "by_priority": by_priority,
                "improvement_velocity_monthly": round(self.get_improvement_velocity(), 1),
                "categories_covered": list(by_category.keys()),
            }

    # ── Analysis Methods ──────────────────────────────────────────────────

    def _gather_evidence(self) -> dict[str, Any]:
        """Gather evidence from available data sources."""
        evidence: dict[str, Any] = {}

        # Check if key modules exist
        import importlib
        evidence["has_architecture_analyzer"] = importlib.util.find_spec("core.architecture_analyzer") is not None
        evidence["has_security_auditor"] = importlib.util.find_spec("core.security_auditor") is not None
        evidence["has_test_generator"] = importlib.util.find_spec("core.intelligent_test_generator") is not None
        evidence["has_synthetic_monitor"] = importlib.util.find_spec("core.synthetic_monitor") is not None
        evidence["has_living_documentation"] = importlib.util.find_spec("core.living_documentation") is not None

        # Check test directory
        test_dir = Path("tests")
        if test_dir.is_dir():
            test_files = list(test_dir.glob("test_*.py"))
            evidence["test_file_count"] = len(test_files)

        # Check VERSION
        ver_file = Path("VERSION")
        if ver_file.is_file():
            evidence["version"] = ver_file.read_text().strip()

        return evidence

    def _analyze_architecture(self, evidence: dict[str, Any]) -> list[EvolutionProposal]:
        """Generate architecture-related proposals."""
        proposals: list[EvolutionProposal] = []

        # Check if feature flags exist
        import importlib
        if not importlib.util.find_spec("core.feature_flags"):
            proposals.append(EvolutionProposal(
                title="Implement Feature Flags System",
                description="Add a feature flag/toggle system for gradual rollouts, A/B testing, and kill-switches",
                category="ARCHITECTURE",
                priority="HIGH",
                effort_estimate="Small",
                impact_estimate="High",
                affected_modules=["core/feature_flags.py"],
                evidence="Feature Flags listed in Architecture Standards but not implemented",
            ))

        # Check if event sourcing exists
        if not importlib.util.find_spec("core.event_sourcing"):
            proposals.append(EvolutionProposal(
                title="Implement Event Sourcing",
                description="Add event sourcing for deterministic state recovery and audit trail",
                category="ARCHITECTURE",
                priority="MEDIUM",
                effort_estimate="Large",
                impact_estimate="High",
                affected_modules=["core/event_sourcing.py"],
                evidence="Event Sourcing listed in Architecture Standards but not implemented",
            ))

        return proposals

    def _analyze_security(self, evidence: dict[str, Any]) -> list[EvolutionProposal]:
        """Generate security-related proposals."""
        proposals: list[EvolutionProposal] = []

        # Check if secrets vault exists
        import importlib
        if not importlib.util.find_spec("core.secrets_vault"):
            proposals.append(EvolutionProposal(
                title="Implement Secrets Vault",
                description="Add centralized secrets management with encryption at rest, rotation, and audit",
                category="SECURITY",
                priority="CRITICAL",
                effort_estimate="Medium",
                impact_estimate="Critical",
                affected_modules=["core/secrets_vault.py"],
                evidence="Secrets Management listed in Security standards but not implemented",
            ))

        # Check if threat intel exists
        if not importlib.util.find_spec("core.threat_intel"):
            proposals.append(EvolutionProposal(
                title="Integrate Threat Intelligence Feeds",
                description="Add external threat intelligence integration for CVE feeds and known bad indicators",
                category="SECURITY",
                priority="HIGH",
                effort_estimate="Medium",
                impact_estimate="High",
                affected_modules=["core/threat_intel.py"],
                evidence="Threat Intelligence listed in Security standards but not implemented",
            ))

        return proposals

    def _analyze_testing(self, evidence: dict[str, Any]) -> list[EvolutionProposal]:
        """Generate testing-related proposals."""
        proposals: list[EvolutionProposal] = []
        test_count = evidence.get("test_file_count", 0)

        if test_count > 0:
            proposals.append(EvolutionProposal(
                title="Maintain Test Coverage Above 95%",
                description=f"Current test file count: {test_count}. Continue expanding test coverage to meet the 95% target",
                category="TESTING",
                priority="HIGH",
                effort_estimate="Medium",
                impact_estimate="High",
                evidence=f"Test directory contains {test_count} files",
            ))

        return proposals

    def _analyze_observability(self, evidence: dict[str, Any]) -> list[EvolutionProposal]:
        """Generate observability-related proposals."""
        proposals: list[EvolutionProposal] = []

        # Check if distributed tracing exists
        import importlib
        if not importlib.util.find_spec("core.distributed_tracing"):
            proposals.append(EvolutionProposal(
                title="Implement Distributed Tracing",
                description="Add OpenTelemetry-compatible distributed tracing for cross-module request tracking",
                category="OBSERVABILITY",
                priority="MEDIUM",
                effort_estimate="Medium",
                impact_estimate="High",
                affected_modules=["core/distributed_tracing.py"],
                evidence="Distributed Tracing listed in SRE standards but not implemented",
            ))

        return proposals

    def _analyze_documentation(self, evidence: dict[str, Any]) -> list[EvolutionProposal]:
        """Generate documentation-related proposals."""
        proposals: list[EvolutionProposal] = []

        # Count doc files
        docs_dir = Path("docs")
        if docs_dir.is_dir():
            doc_files = list(docs_dir.rglob("*.md"))
            if len(doc_files) < 20:
                proposals.append(EvolutionProposal(
                    title="Expand Documentation Coverage",
                    description=f"Current documentation: {len(doc_files)} files. Target: 100% coverage",
                    category="DOCUMENTATION",
                    priority="MEDIUM",
                    effort_estimate="Large",
                    impact_estimate="Medium",
                    evidence=f"docs/ contains {len(doc_files)} .md files",
                ))

        return proposals

    def _analyze_governance(self, evidence: dict[str, Any]) -> list[EvolutionProposal]:
        """Generate governance-related proposals."""
        proposals: list[EvolutionProposal] = []

        proposals.append(EvolutionProposal(
            title="Schedule Regular Constitution Scorecard Reviews",
            description="Run constitution scorecard weekly to track compliance against all 12 layers and 23 categories",
            category="GOVERNANCE",
            priority="MEDIUM",
            effort_estimate="Small",
            impact_estimate="High",
            evidence="Constitution v4.0 defines 12 enterprise layers and 23 scoring categories",
        ))

        return proposals

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist_history(self) -> None:
        """Persist proposals to JSON."""
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            data = [p.to_dict() for p in self._proposals[-500:]]
            self._history_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[EVOLUTION] Persist error: %s", exc)

    def _load_history(self) -> None:
        """Load proposals from JSON."""
        try:
            if self._history_path.is_file():
                data = json.loads(self._history_path.read_text(encoding="utf-8"))
                for item in data:
                    self._proposals.append(EvolutionProposal(
                        **{k: v for k, v in item.items()
                           if k in EvolutionProposal.__dataclass_fields__}
                    ))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[EVOLUTION] Load error: %s", exc)

    def clear_all(self) -> None:
        """Clear all proposals (for testing)."""
        with self._lock:
            self._proposals.clear()
            if self._history_path.exists():
                self._history_path.unlink()


def _priority_sort_key(priority: str) -> int:
    return {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "IDEA": 4}.get(priority, 99)


# ── Singleton ──────────────────────────────────────────────────────────────

_instance: EnterpriseEvolutionEngine | None = None
_instance_lock = threading.RLock()


def get_evolution_engine() -> EnterpriseEvolutionEngine:
    """Get the singleton EnterpriseEvolutionEngine instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = EnterpriseEvolutionEngine()
        return _instance


def reset_evolution_engine() -> None:
    """Force-reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "EnterpriseEvolutionEngine",
    "EvolutionProposal",
    "EvolutionProposalResult",
    "EvolutionTrend",
    "get_evolution_engine",
    "reset_evolution_engine",
]
