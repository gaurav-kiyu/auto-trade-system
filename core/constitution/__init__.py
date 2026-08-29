"""Constitution Validation Engine — Runtime enforcement of the Final Master System Constitution.

Provides:
  - Scoring validation against the 23-category framework
  - Change pipeline verification (10-step mandate)
  - Pre-implementation checklist enforcement
  - Evidence-based scoring compliance checks
  - Audit trail recording for constitution-related events

This module is the main entry point for the ``core.constitution`` package.
Data classes live in ``models.py`` and auto-evidence collection lives in ``evidence.py``.

Usage:
    from core.constitution import ConstitutionValidator, get_validator

    validator = get_validator()
    result = validator.validate_change_pipeline(evidence={...})
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from core.constitution.evidence import collect_auto_evidence as _collect_auto_evidence
from core.constitution.models import (
    CategoryScore,
    ScoreEvidence,
    ScoreReport,
    ValidationResult,
)

log = logging.getLogger(__name__)


__all__ = [
    "CategoryScore",
    "ConstitutionValidator",
    "ScoreEvidence",
    "ScoreReport",
    "ValidationResult",
    "check_final_success",
    "get_validator",
    "log",
    "validate_and_report",
]


_CONSTITUTION_VERSION = "4.1.0"


# ── Constitution Validator ────────────────────────────────────────────────────


class ConstitutionValidator:
    """Validates code changes against the Master Engineering Constitution v4.0.

    Features:
      - 12 Enterprise Layers scoring
      - 18 AI Specialist Roles
      - 12 Quality Gates
      - Success Metrics validation
      - 10-step Definition of Done
      - Continuous Lifecycle validation
      - Evidence-based scoring across all categories
    """

    CHANGE_PIPELINE_STEPS = [
        "review",
        "impact_analysis",
        "design",
        "implementation",
        "testing",
        "validation",
        "documentation",
        "audit",
        "acceptance",
        "release",
    ]

    # ── v4.0: 12 Enterprise Layers ─────────────────────────────────────────
    ENTERPRISE_LAYERS: dict[str, tuple[str, float]] = {
        "LAY-01": ("Business Layer — business logic, domain models, workflows", 10.0),
        "LAY-02": ("Platform Engineering Layer — IDP, Golden Paths, self-service", 10.0),
        "LAY-03": ("Enterprise Architecture Layer — patterns, decisions, standards", 10.0),
        "LAY-04": ("AI Intelligence Layer — ML models, signal processing, decisions", 10.0),
        "LAY-05": ("Knowledge Graph & Digital Twin Layer — repo intelligence, KG", 10.0),
        "LAY-06": ("Autonomous Engineering Layer — self-healing, auto-optimization", 10.0),
        "LAY-07": ("Security, Governance & Compliance Layer — Zero Trust, RBAC", 10.0),
        "LAY-08": ("Reliability, Observability & SRE Layer — logging, tracing, metrics", 10.0),
        "LAY-09": ("Documentation & Knowledge Management Layer — living docs, ADRs", 10.0),
        "LAY-10": ("Executive Intelligence Layer — presentations, reports, KPIs", 10.0),
        "LAY-11": ("Continuous Learning Layer — incident learning, postmortems", 10.0),
        "LAY-12": ("Enterprise Evolution Layer — capability maturity, roadmap", 10.0),
    }

    # ── v4.0: 12 Quality Gates ────────────────────────────────────────────
    QUALITY_GATES: dict[str, tuple[str, float]] = {
        "QGT-01": ("Architecture Gate — pattern compliance, boundary enforcement", 10.0),
        "QGT-02": ("Security Gate — no hardcoded secrets, auth enforced", 10.0),
        "QGT-03": ("Performance Gate — no regression >5%, query latency", 10.0),
        "QGT-04": ("Maintainability Gate — complexity <15, <1000 lines per file", 10.0),
        "QGT-05": ("Reliability Gate — health checks, error budget", 10.0),
        "QGT-06": ("Scalability Gate — capacity benchmarks within limits", 10.0),
        "QGT-07": ("Documentation Gate — every public symbol documented", 10.0),
        "QGT-08": ("Accessibility Gate — WCAG 2.1 AA compliance", 10.0),
        "QGT-09": ("Testing Gate — coverage >87%, chaos tests pass", 10.0),
        "QGT-10": ("Technical Debt Gate — debt register updated, trending down", 10.0),
        "QGT-11": ("Deployment Readiness Gate — release checklist complete", 10.0),
        "QGT-12": ("Overall Engineering Score Gate — aggregate >=8.5/10", 10.0),
    }

    # ── v4.0: Success Metrics ─────────────────────────────────────────────
    # Tuple format: (name, max_score, target, lower_is_better)
    SUCCESS_METRICS: dict[str, tuple[str, float, float, bool]] = {
        "MET-01": ("Availability >99.95%", 10.0, 99.95, False),
        "MET-02": ("Deployment Success >99%", 10.0, 99.0, False),
        "MET-03": ("Critical Security Issues = 0", 10.0, 100.0, False),
        "MET-04": ("Test Coverage >95%", 10.0, 95.0, False),
        "MET-05": ("Documentation Coverage = 100%", 10.0, 100.0, False),
        "MET-06": ("Performance Regression = 0", 10.0, 100.0, False),
        "MET-07": ("Technical Debt Trending Down", 10.0, 50.0, True),
        "MET-08": ("Developer Productivity Trending Up", 10.0, 50.0, False),
    }

    # ── v4.0: 18 AI Specialist Roles ──────────────────────────────────────
    AI_SPECIALIST_ROLES: dict[str, tuple[str, str]] = {
        "ROL-01": ("Planner", "Break down work, create plans, estimate effort"),
        "ROL-02": ("Principal Architect", "Design architecture, validate patterns, enforce standards"),
        "ROL-03": ("Developer", "Write code, implement features, fix bugs"),
        "ROL-04": ("Reviewer", "Code review, architecture review, security review"),
        "ROL-05": ("Security", "Security audit, vulnerability scanning, threat modeling"),
        "ROL-06": ("Performance", "Performance profiling, optimization, benchmarking"),
        "ROL-07": ("Database", "Schema design, query optimization, migration planning"),
        "ROL-08": ("DevOps", "CI/CD, containerization, infrastructure as code"),
        "ROL-09": ("SRE", "Monitoring, alerting, incident response, chaos engineering"),
        "ROL-10": ("QA", "Test strategy, test generation, quality gates"),
        "ROL-11": ("Technical Writer", "Documentation, runbooks, ADRs, knowledge base"),
        "ROL-12": ("Business Analyst", "Requirements gathering, stakeholder communication"),
        "ROL-13": ("Product Owner", "Prioritization, roadmap, backlog management"),
        "ROL-14": ("Cloud", "Cloud architecture, cost optimization, migration"),
        "ROL-15": ("Platform", "IDP, Golden Paths, service catalog, self-service"),
        "ROL-16": ("FinOps", "Cost tracking, budgeting, optimization recommendations"),
        "ROL-17": ("Governance", "Constitution compliance, policy enforcement, audit"),
        "ROL-18": ("Executive Advisor", "Strategic recommendations, business value analysis"),
    }

    # ── v4.0: Definition of Done ──────────────────────────────────────────
    DEFINITION_OF_DONE: list[str] = [
        "Architecture Reviewed",
        "Security Reviewed",
        "Performance Validated",
        "Tests Generated & Passed",
        "Documentation Updated",
        "Diagrams Updated",
        "Runbooks Updated",
        "Observability Added",
        "Knowledge Graph Updated",
        "Decision Memory Updated",
    ]

    # ── v4.0: Continuous Lifecycle ────────────────────────────────────────
    CONTINUOUS_LIFECYCLE: list[str] = [
        "Requirements",
        "Architecture",
        "Development",
        "Review",
        "Testing",
        "Deployment",
        "Monitoring",
        "Incident Analysis",
        "Learning",
        "Knowledge Update",
        "Continuous Optimization",
    ]

    # ── Combined categories (backward-compatible with v1.0) ───────────────
    # Merges classic 31 categories with v4.0 enterprise layers and quality gates
    CATEGORIES: dict[str, tuple[str, float]] = {
        # Original 31 categories (preserved for backward compatibility)
        "ARCH-01": ("Boundary enforcement", 10.0),
        "ARCH-02": ("Single responsibility", 10.0),
        "ARCH-03": ("Port/adapter separation", 10.0),
        "ARCH-04": ("No circular dependencies", 10.0),
        "SEC-01": ("Authentication", 10.0),
        "SEC-02": ("Authorization/RBAC", 10.0),
        "SEC-03": ("Secret management", 10.0),
        "SEC-04": ("Audit trail", 10.0),
        "RSK-01": ("Hard halt enforcement", 10.0),
        "RSK-02": ("Loss limits", 10.0),
        "RSK-03": ("Position sizing", 10.0),
        "RSK-04": ("Fail-closed", 10.0),
        "EXE-01": ("Exactly-once semantics", 10.0),
        "EXE-02": ("Idempotent retry", 10.0),
        "EXE-03": ("State machine correctness", 10.0),
        "EXE-04": ("Reconciliation", 10.0),
        "TST-01": ("Test coverage", 10.0),
        "TST-02": ("Chaos testing", 10.0),
        "TST-03": ("Contract testing", 10.0),
        "TST-04": ("Regression testing", 10.0),
        "OBS-01": ("Structured logging", 10.0),
        "OBS-02": ("Metrics", 10.0),
        "OBS-03": ("Health checks", 10.0),
        "OBS-04": ("Alerting", 10.0),
        "GOV-01": ("Documentation sync", 10.0),
        "GOV-02": ("Repository hygiene", 10.0),
        "GOV-03": ("Technical debt tracking", 10.0),
        "GOV-04": ("Release governance", 10.0),
        "DR-01": ("Database migration", 10.0),
        "DR-02": ("State persistence", 10.0),
        "DR-03": ("WAL journal", 10.0),
        # v4.0 Enterprise Layers (LAY-01 through LAY-12)
        "LAY-01": ("Business Layer — business logic, domain models, workflows", 10.0),
        "LAY-02": ("Platform Engineering Layer — IDP, Golden Paths, self-service", 10.0),
        "LAY-03": ("Enterprise Architecture Layer — patterns, decisions, standards", 10.0),
        "LAY-04": ("AI Intelligence Layer — ML models, signal processing, decisions", 10.0),
        "LAY-05": ("Knowledge Graph & Digital Twin Layer — repo intelligence, KG", 10.0),
        "LAY-06": ("Autonomous Engineering Layer — self-healing, auto-optimization", 10.0),
        "LAY-07": ("Security, Governance & Compliance Layer — Zero Trust, RBAC", 10.0),
        "LAY-08": ("Reliability, Observability & SRE Layer — logging, tracing, metrics", 10.0),
        "LAY-09": ("Documentation & Knowledge Management Layer — living docs, ADRs", 10.0),
        "LAY-10": ("Executive Intelligence Layer — presentations, reports, KPIs", 10.0),
        "LAY-11": ("Continuous Learning Layer — incident learning, postmortems", 10.0),
        "LAY-12": ("Enterprise Evolution Layer — capability maturity, roadmap", 10.0),
        # v4.0 Quality Gates (QGT-01 through QGT-12)
        "QGT-01": ("Architecture Gate — pattern compliance, boundary enforcement", 10.0),
        "QGT-02": ("Security Gate — no hardcoded secrets, auth enforced", 10.0),
        "QGT-03": ("Performance Gate — no regression >5%, query latency", 10.0),
        "QGT-04": ("Maintainability Gate — complexity <15, <1000 lines per file", 10.0),
        "QGT-05": ("Reliability Gate — health checks, error budget", 10.0),
        "QGT-06": ("Scalability Gate — capacity benchmarks within limits", 10.0),
        "QGT-07": ("Documentation Gate — every public symbol documented", 10.0),
        "QGT-08": ("Accessibility Gate — WCAG 2.1 AA compliance", 10.0),
        "QGT-09": ("Testing Gate — coverage >87%, chaos tests pass", 10.0),
        "QGT-10": ("Technical Debt Gate — debt register updated, trending down", 10.0),
        "QGT-11": ("Deployment Readiness Gate — release checklist complete", 10.0),
        "QGT-12": ("Overall Engineering Score Gate — aggregate >=8.5/10", 10.0),
        # v4.0 Engineering Principles (PRN-01 through PRN-13)
        "PRN-01": ("Security by Design", 10.0),
        "PRN-02": ("Privacy by Design", 10.0),
        "PRN-03": ("AI by Design", 10.0),
        "PRN-04": ("API First", 10.0),
        "PRN-05": ("Cloud Native where appropriate", 10.0),
        "PRN-06": ("Everything as Code", 10.0),
        "PRN-07": ("Documentation as Code", 10.0),
        "PRN-08": ("Test Everything", 10.0),
        "PRN-09": ("Observe Everything", 10.0),
        "PRN-10": ("Automate Everything", 10.0),
        "PRN-11": ("Measure Everything", 10.0),
        "PRN-12": ("Continuous Improvement", 10.0),
        "PRN-13": ("Backward Compatibility by Default", 10.0),
        # v4.0 Architecture Standards (AST-01 through AST-13)
        "AST-01": ("Domain-Driven Design", 10.0),
        "AST-02": ("Clean Architecture", 10.0),
        "AST-03": ("Vertical Slice", 10.0),
        "AST-04": ("CQRS", 10.0),
        "AST-05": ("Event Sourcing", 10.0),
        "AST-06": ("Mediator Pattern", 10.0),
        "AST-07": ("Modular Monolith first", 10.0),
        "AST-08": ("Feature Flags", 10.0),
        "AST-09": ("Plugin Architecture", 10.0),
        "AST-10": ("Multi-tenancy", 10.0),
        "AST-11": ("Versioned APIs", 10.0),
        "AST-12": ("Semantic Versioning", 10.0),
        "AST-13": ("Strongly Typed Configuration", 10.0),
        # v4.0 Security & Governance Standards (SGS-01 through SGS-11)
        "SGS-01": ("Zero Trust", 10.0),
        "SGS-02": ("RBAC/PBAC", 10.0),
        "SGS-03": ("Threat Modeling", 10.0),
        "SGS-04": ("Secrets Management", 10.0),
        "SGS-05": ("SBOM", 10.0),
        "SGS-06": ("Compliance Reporting", 10.0),
        "SGS-07": ("Runtime Security", 10.0),
        "SGS-08": ("AI Security", 10.0),
        "SGS-09": ("Prompt Injection Detection", 10.0),
        "SGS-10": ("Hallucination Detection", 10.0),
        "SGS-11": ("Audit Trails", 10.0),
        # v4.0 Platform Engineering Standards (PLS-01 through PLS-06)
        "PLS-01": ("Internal Developer Platform", 10.0),
        "PLS-02": ("Golden Paths", 10.0),
        "PLS-03": ("Service Catalog", 10.0),
        "PLS-04": ("Environment Provisioning", 10.0),
        "PLS-05": ("Infrastructure as Code", 10.0),
        "PLS-06": ("Self-Service Infrastructure", 10.0),
        # v4.0 SRE/Reliability Standards (SRE-01 through SRE-09)
        "SRE-01": ("Structured Logging", 10.0),
        "SRE-02": ("Distributed Tracing", 10.0),
        "SRE-03": ("Metrics & Dashboards", 10.0),
        "SRE-04": ("Health Checks", 10.0),
        "SRE-05": ("Synthetic Monitoring", 10.0),
        "SRE-06": ("Chaos Engineering", 10.0),
        "SRE-07": ("Self-Healing", 10.0),
        "SRE-08": ("Rollback Automation", 10.0),
        "SRE-09": ("Error Budgets", 10.0),
        # v4.0 Knowledge & Decision Management (KNW-01 through KNW-04)
        "KNW-01": ("Enterprise Decision Memory — ADR import, Q&A, decision graph", 10.0),
        "KNW-02": ("ADR Documentation — architecture decision records", 10.0),
        "KNW-03": ("Organizational Memory — decision persistence, knowledge graph", 10.0),
        "KNW-04": ("Incident Learning — postmortem automation, root cause analysis", 10.0),
    }

    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._audit_log: list[dict[str, Any]] = []
        self._categories: dict[str, CategoryScore] = {}
        self._init_categories()
        _collect_auto_evidence(self)

    def _init_categories(self) -> None:
        """Initialize all 111 categories (31 classic + 12 enterprise layers + 12 quality gates + 13 principles + 13 architecture + 11 security + 6 platform + 9 SRE + 4 knowledge) with default scores."""
        for cid, (name, max_score) in self.CATEGORIES.items():
            self._categories[cid] = CategoryScore(
                category_id=cid,
                category_name=name,
                max_score=max_score,
            )

    # ── Change Pipeline Validation ───────────────────────────────────────────

    def validate_change_pipeline(
        self,
        evidence: dict[str, bool],
    ) -> list[ValidationResult]:
        """Validate that all 10 change pipeline steps have evidence.

        Args:
            evidence: Dict mapping step name -> completed (bool)

        Returns:
            List of validation results, one per step.

        """
        results: list[ValidationResult] = []
        for step in self.CHANGE_PIPELINE_STEPS:
            if evidence.get(step, False):
                results.append(ValidationResult(
                    passed=True,
                    category=f"pipeline.{step}",
                    detail=f"Change pipeline step '{step}' completed",
                ))
            else:
                results.append(ValidationResult(
                    passed=False,
                    category=f"pipeline.{step}",
                    detail=f"Change pipeline step '{step}' missing - all 10 steps required",
                    evidence_required=[step],
                ))
        self._audit("change_pipeline", {
            "passed": all(r.passed for r in results),
            "completed_steps": [r.category for r in results if r.passed],
            "missing_steps": [r.category for r in results if not r.passed],
        })
        return results

    # ── Pre-Implementation Checklist ─────────────────────────────────────────

    def validate_pre_implementation(
        self,
        constitution_read: bool = False,
        claude_read: bool = False,
        architecture_reviewed: bool = False,
        audit_history_reviewed: bool = False,
        risk_controls_verified: bool = False,
        affected_files_identified: list[str] | None = None,
    ) -> list[ValidationResult]:
        """Mandatory pre-implementation review checklist.

        The Constitution mandates:
          1. Review architecture
          2. Review historical versions
          3. Review audit reports
          4. Review risk controls
          5. Review security controls
          6. Review current implementation
          7. Review release state
        """
        results: list[ValidationResult] = []

        checks = [
            ("constitution_read", constitution_read, "Constitution must be read before changes"),
            ("claude_context_read", claude_read, "CLAUDE.md must be read for project context"),
            ("architecture_reviewed", architecture_reviewed, "Architecture documents must be reviewed"),
            ("audit_history_reviewed", audit_history_reviewed, "Audit history must be reviewed"),
            ("risk_controls_verified", risk_controls_verified, "Risk controls must be verified before changes"),
        ]

        for name, passed, detail in checks:
            results.append(ValidationResult(
                passed=passed,
                category=f"pre_implementation.{name}",
                detail=detail if not passed else f"Pre-implementation check '{name}' passed",
            ))

        # Affected files identification
        if affected_files_identified and len(affected_files_identified) > 0:
            results.append(ValidationResult(
                passed=True,
                category="pre_implementation.affected_files",
                detail=f"Affected files identified: {', '.join(affected_files_identified)}",
            ))
        else:
            results.append(ValidationResult(
                passed=False,
                category="pre_implementation.affected_files",
                detail="Affected files must be identified before implementation",
            ))

        self._audit("pre_implementation", {
            "passed": all(r.passed for r in results),
            "checks": {r.category: r.passed for r in results},
        })

        return results

    # ── Scoring ──────────────────────────────────────────────────────────────

    def get_category_score(self, category_id: str) -> CategoryScore | None:
        """Get the current score for a category."""
        return self._categories.get(category_id)

    def add_evidence(
        self,
        category_id: str,
        description: str,
        evidence_type: str = "documentation",
        weight: float = 0.1,
    ) -> bool:
        """Add evidence to a category.

        Args:
            category_id: Category identifier (e.g., "ARCH-01")
            description: Evidence description
            evidence_type: Type of evidence (test_pass, manual_test, code_review, doc, audit_log, chaos, production)
            weight: Evidence weight per the scoring framework

        Returns:
            True if evidence was added, False if category not found.

        """
        with self._lock:
            cat = self._categories.get(category_id)
            if cat is None:
                return False
            # Deduplication: skip if exact description already exists
            for existing in cat.evidence:
                if existing.description == description:
                    log.debug("Duplicate evidence skipped for category %s: %s",
                              category_id, description)
                    return True
            ev = ScoreEvidence(
                description=description,
                evidence_type=evidence_type,
                weight=weight,
                verified=True,
            )
            cat.evidence.append(ev)
            self._audit("evidence_added", {
                "category": category_id,
                "description": description,
                "new_score": round(cat.effective_score, 2),
            })
            return True

    def add_regression(self, category_id: str, description: str) -> bool:
        """Add a regression that lowers the score."""
        with self._lock:
            cat = self._categories.get(category_id)
            if cat is None:
                return False
            cat.regressions.append(description)
            self._audit("regression_added", {
                "category": category_id,
                "description": description,
                "new_score": round(cat.effective_score, 2),
            })
            return True

    def add_audit(self, category_id: str, audit_type: str) -> bool:
        """Record that an audit has been performed for a category."""
        with self._lock:
            cat = self._categories.get(category_id)
            if cat is None:
                return False
            if audit_type not in cat.audits:
                cat.audits.append(audit_type)
            return True

    def generate_report(self) -> ScoreReport:
        """Generate a complete scoring report."""
        with self._lock:
            scores = list(self._categories.values())
            total_evidence = sum(len(c.evidence) for c in scores)
            total_regressions = sum(len(c.regressions) for c in scores)
            overall = sum(c.effective_score for c in scores) / max(len(scores), 1)

            return ScoreReport(
                timestamp=time.time(),
                version=_CONSTITUTION_VERSION,
                categories=dict(self._categories),
                overall_score=overall,
                total_evidence_items=total_evidence,
                open_regressions=total_regressions,
            )

    def print_report(self) -> None:
        """Print the scoring report to the log."""
        report = self.generate_report()
        data = report.to_dict()
        # Compute max possible overall from category max_scores
        categories = data["categories"]
        max_possible = sum(c["max_score"] for c in categories.values()) / max(len(categories), 1)
        overall = data["overall_score"]
        pct = (overall / max_possible * 100) if max_possible > 0 else 0.0
        log.info("=" * 60)
        log.info("CONSTITUTION SCORING REPORT v%s", data["version"])
        log.info("=" * 60)
        log.info("Overall Score: %.2f / %.2f (%.1f%% of max)", overall, max_possible, pct)
        log.info("Total Evidence: %d", data["total_evidence_items"])
        log.info("Open Regressions: %d", data["open_regressions"])
        log.info("")
        for cid, cat in sorted(categories.items()):
            status = "OK" if cat["regressions"] == [] else "REG"
            cat_pct = (cat["score"] / cat["max_score"] * 100) if cat["max_score"] > 0 else 0.0
            log.info("  %s %s [%.2f/%.2f = %.1f%%] %s",
                     status, cid, cat["score"], cat["max_score"], cat_pct,
                     "audit" if cat["audits"] else "")
        log.info("=" * 60)

    # ── Feature Acceptance Validation ─────────────────────────────────────────

    def validate_feature_acceptance(
        self,
        fully_tested: bool = False,
        fully_validated: bool = False,
        beneficial: bool = False,
        secure: bool = False,
        replay_safe: bool = False,
        risk_safe: bool = False,
        maintainable: bool = False,
        documented: bool = False,
    ) -> list[ValidationResult]:
        """Validate that a feature meets constitutional acceptance criteria.

        The Constitution mandates:
          - Feature must be beneficial (gate check)
          - Feature must be fully tested
          - Feature must be fully validated
          - Feature must be secure
          - Feature must be replay-safe
          - Feature must be risk-safe
          - Feature must be maintainable
          - Feature must be documented

        Args:
            All boolean parameters indicate whether the criterion is met.

        Returns:
            List of ValidationResult. Returns a single success result when
            all criteria pass, or a list of failed results otherwise.

        """
        failures: list[ValidationResult] = []

        if not beneficial:
            failures.append(ValidationResult(
                passed=False,
                category="acceptance.beneficial",
                detail="REJECTED: Feature is not beneficial",
            ))
            return failures

        checks = [
            ("acceptance.fully_tested", fully_tested, "Feature must be fully tested"),
            ("acceptance.fully_validated", fully_validated, "Feature must be fully validated"),
            ("acceptance.secure", secure, "Feature must be secure"),
            ("acceptance.replay_safe", replay_safe, "Feature must be replay-safe"),
            ("acceptance.risk_safe", risk_safe, "Feature must be risk-safe"),
            ("acceptance.maintainable", maintainable, "Feature must be maintainable"),
            ("acceptance.documented", documented, "Feature must be documented"),
        ]

        for category, passed, detail in checks:
            if not passed:
                failures.append(ValidationResult(
                    passed=False,
                    category=category,
                    detail=f"REJECTED: {detail}",
                    evidence_required=[category.split(".")[1]],
                ))

        if failures:
            self._audit("feature_acceptance", {
                "passed": False,
                "failures": [r.category for r in failures],
            })
            return failures

        self._audit("feature_acceptance", {
            "passed": True,
            "failures": [],
        })

        return [ValidationResult(
            passed=True,
            category="acceptance.all",
            detail="Feature accepted: all constitutional criteria met",
        )]

    # ── Score Evidence Validation ──────────────────────────────────────────

    def validate_score_evidence(
        self,
        score: float,
        category: str,
        has_evidence: bool = False,
    ) -> ValidationResult:
        """Validate that scores above thresholds have required evidence.

        The Constitution mandates:
          - Scores above 9.5 require full audits (retrieved from internal state)
          - Scores above 9.0 require evidence
          - Without evidence, no score may exceed 8.0

        Args:
            score: The score to validate.
            category: Category ID (e.g., "ARCH-01").
            has_evidence: Whether the category has objective evidence.

        Returns:
            ValidationResult with passed=True if valid.

        """
        cat = self._categories.get(category)
        has_audits = bool(cat and cat.audits)

        if score > 9.5:
            required_audits = [
                "architecture", "security", "risk", "execution",
                "testing", "observability", "disaster_recovery",
                "chaos", "black_swan",
            ]
            if not has_audits or not all(
                a in (cat.audits if cat else []) for a in required_audits
            ):
                return ValidationResult(
                    passed=False,
                    category=category,
                    detail="Score {:.2f} > 9.5 requires full audits: {}".format(
                        score, ", ".join(required_audits)),
                    evidence_required=required_audits,
                )
        if score > 9.0 and not has_evidence:
            return ValidationResult(
                passed=False,
                category=category,
                detail=f"Score {score:.2f} > 9.0 requires objective evidence. No evidence registered.",
                evidence_required=["objective_evidence"],
            )
        if not has_evidence and score > 8.0:
            return ValidationResult(
                passed=False,
                category=category,
                detail=f"Score {score:.2f} > 8.0 without evidence is not allowed.",
                evidence_required=["objective_evidence"],
            )
        return ValidationResult(
            passed=True,
            category=category,
            detail=f"Score {score:.2f} validated against constitution criteria.",
        )

    def validate_repository_hygiene(
        self,
        root_path: str | None = None,
    ) -> list[ValidationResult]:
        """Validate repository hygiene: no prohibited artifacts, .gitignore present.

        Args:
            root_path: Optional custom root path to scan (used for testing).
                       Defaults to PROJECT_ROOT.

        Returns:
            List of ValidationResult, one per hygiene check.

        """
        results: list[ValidationResult] = []
        root = Path(root_path) if root_path else self.PROJECT_ROOT

        # Check for prohibited artifacts
        prohibited_patterns = [
            "__pycache__", "*.pyc", ".pytest_cache",
            ".ruff_cache", ".mypy_cache", ".hypothesis",
        ]
        found_items: list[str] = []
        for pattern in prohibited_patterns:
            try:
                matches = list(root.rglob(pattern))
                if matches:
                    found_items.extend(str(m.relative_to(root)) for m in matches[:3])
            except (ValueError, OSError):
                pass

        if found_items:
            results.append(ValidationResult(
                passed=False,
                category="hygiene.prohibited_artifacts",
                detail=f"Prohibited artifacts found: {len(found_items)} items (e.g., {found_items[0]})",
                evidence_required=["clean_repository"],
            ))
        else:
            results.append(ValidationResult(
                passed=True,
                category="hygiene.prohibited_artifacts",
                detail="No prohibited artifacts found",
            ))

        # Check for .gitignore
        if (root / ".gitignore").exists():
            results.append(ValidationResult(
                passed=True,
                category="hygiene.gitignore",
                detail=".gitignore file present",
            ))
        else:
            results.append(ValidationResult(
                passed=False,
                category="hygiene.gitignore",
                detail=".gitignore file missing - repository hygiene violation",
                evidence_required=[".gitignore"],
            ))

        return results

    # ── v4.0: Enterprise Layer Validation ─────────────────────────────────

    def validate_enterprise_layer(
        self,
        layer_id: str,
        documented: bool = False,
        implemented: bool = False,
        tested: bool = False,
        monitored: bool = False,
    ) -> ValidationResult:
        """Validate an enterprise layer against v4.0 standards.

        Each of the 12 Enterprise Layers must be:
          - Documented (purpose, scope, interfaces)
          - Implemented (concrete modules/artifacts)
          - Tested (unit + integration tests)
          - Monitored (metrics, health checks, alerting)

        Args:
            layer_id: Layer identifier (LAY-01 through LAY-12).
            documented: Whether the layer's purpose and scope are documented.
            implemented: Whether concrete implementations exist.
            tested: Whether tests cover the layer.
            monitored: Whether the layer has monitoring/metrics.

        Returns:
            ValidationResult with pass/fail and detailed info.
        """
        layer = self.ENTERPRISE_LAYERS.get(layer_id)
        if not layer:
            return ValidationResult(
                passed=False,
                category=f"enterprise_layer.{layer_id}",
                detail=f"Unknown enterprise layer: {layer_id}",
            )

        layer_name = layer[0]
        missing: list[str] = []
        if not documented:
            missing.append("documentation")
        if not implemented:
            missing.append("implementation")
        if not tested:
            missing.append("testing")
        if not monitored:
            missing.append("monitoring")

        if missing:
            return ValidationResult(
                passed=False,
                category=f"enterprise_layer.{layer_id}",
                detail=f"Layer '{layer_name}' missing: {', '.join(missing)}",
                evidence_required=missing,
            )

        self._audit("enterprise_layer_validated", {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "passed": True,
        })
        return ValidationResult(
            passed=True,
            category=f"enterprise_layer.{layer_id}",
            detail=f"Enterprise layer '{layer_name}' fully compliant (documented, implemented, tested, monitored)",
        )

    def validate_all_enterprise_layers(
        self,
        layer_status: dict[str, dict[str, bool]],
    ) -> list[ValidationResult]:
        """Validate all 12 enterprise layers in one call.

        Args:
            layer_status: Dict mapping layer_id -> {documented, implemented, tested, monitored}

        Returns:
            List of ValidationResult, one per layer.
        """
        results: list[ValidationResult] = []
        for lid in self.ENTERPRISE_LAYERS:
            status = layer_status.get(lid, {})
            result = self.validate_enterprise_layer(
                layer_id=lid,
                documented=status.get("documented", False),
                implemented=status.get("implemented", False),
                tested=status.get("tested", False),
                monitored=status.get("monitored", False),
            )
            results.append(result)
        return results

    # ── v4.0: Quality Gate Validation ───────────────────────────────────────

    def validate_quality_gate(
        self,
        gate_id: str,
        passed: bool = False,
        details: str = "",
    ) -> ValidationResult:
        """Validate a quality gate.

        The 12 Quality Gates are v4.0 checkpoints that every change must pass.

        Args:
            gate_id: Quality gate identifier (QGT-01 through QGT-12).
            passed: Whether the gate was passed.
            details: Additional details about the gate status.

        Returns:
            ValidationResult with pass/fail and detailed info.
        """
        gate = self.QUALITY_GATES.get(gate_id)
        if not gate:
            return ValidationResult(
                passed=False,
                category=f"quality_gate.{gate_id}",
                detail=f"Unknown quality gate: {gate_id}",
            )

        gate_name = gate[0]
        if not passed:
            return ValidationResult(
                passed=False,
                category=f"quality_gate.{gate_id}",
                detail=f"Quality gate FAILED: {gate_name}. {details}",
                evidence_required=[f"pass_{gate_id.lower()}"],
            )

        self._audit("quality_gate_passed", {
            "gate_id": gate_id,
            "gate_name": gate_name,
            "details": details,
        })
        return ValidationResult(
            passed=True,
            category=f"quality_gate.{gate_id}",
            detail=f"Quality gate PASSED: {gate_name}. {details}".strip(),
        )

    def validate_all_quality_gates(
        self,
        gate_results: dict[str, bool],
    ) -> list[ValidationResult]:
        """Validate all 12 quality gates.

        Args:
            gate_results: Dict mapping gate_id -> passed (bool)

        Returns:
            List of ValidationResult, one per gate.
        """
        results: list[ValidationResult] = []
        for gid in self.QUALITY_GATES:
            result = self.validate_quality_gate(
                gate_id=gid,
                passed=gate_results.get(gid, False),
            )
            results.append(result)
        return results

    # ── v4.0: Success Metrics Validation ────────────────────────────────────

    def validate_success_metric(
        self,
        metric_id: str,
        current_value: float = 0.0,
    ) -> ValidationResult:
        """Validate a success metric against its target.

        Supports both higher-is-better and lower-is-better metrics.
        For example, MET-07 (Technical Debt Trending Down) uses
        lower-is-better semantics.

        Args:
            metric_id: Metric identifier (MET-01 through MET-08).
            current_value: The current measured value.

        Returns:
            ValidationResult indicating whether the target is met.
        """
        metric = self.SUCCESS_METRICS.get(metric_id)
        if not metric:
            return ValidationResult(
                passed=False,
                category=f"success_metric.{metric_id}",
                detail=f"Unknown success metric: {metric_id}",
            )

        name, max_score, target, lower_is_better = metric
        if lower_is_better:
            achieved = current_value <= target
        else:
            achieved = current_value >= target

        operator_str = "<=" if lower_is_better else ">="
        if not achieved:
            gap = current_value - target if not lower_is_better else target - current_value
            return ValidationResult(
                passed=False,
                category=f"success_metric.{metric_id}",
                detail=f"Metric '{name}' at {current_value:.1f}% — target is {target:.1f}% (gap: {abs(gap):.1f}%)",
                evidence_required=[f"meet_{metric_id.lower()}"],
            )

        return ValidationResult(
            passed=True,
            category=f"success_metric.{metric_id}",
            detail=f"Metric '{name}' achieved: {current_value:.1f}% {operator_str} {target:.1f}% target",
        )

    def validate_all_success_metrics(
        self,
        metric_values: dict[str, float],
    ) -> list[ValidationResult]:
        """Validate all 8 success metrics.

        Args:
            metric_values: Dict mapping metric_id -> current_value

        Returns:
            List of ValidationResult.
        """
        results: list[ValidationResult] = []
        for mid in self.SUCCESS_METRICS:
            result = self.validate_success_metric(
                metric_id=mid,
                current_value=metric_values.get(mid, 0.0),
            )
            results.append(result)
        return results

    def validate_metric_trend(
        self,
        metric_id: str,
    ) -> ValidationResult:
        """Validate a trend-based success metric (MET-07 / MET-08) using time-series data.

        Delegates to :mod:`core.success_metrics_trend`, which captures release-level
        snapshots of trend indicators and computes direction (DOWN / UP / STABLE).
        This makes the two "trending" success metrics provable across releases instead
        of aspirational.

        Args:
            metric_id: Metric identifier ("MET-07" or "MET-08").

        Returns:
            ValidationResult with pass/fail and trend evidence.

        """
        try:
            from core.success_metrics_trend import get_metrics_trend
            trend = get_metrics_trend()
            verdict = trend.validate_metric(metric_id)
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            return ValidationResult(
                passed=False,
                category=f"success_metric.{metric_id}",
                detail=f"Trend tracker unavailable for {metric_id}: {exc}",
                evidence_required=["success_metrics_trend_module"],
            )

        if verdict["passed"]:
            self._audit("success_metric_trend", {
                "metric_id": metric_id,
                "direction": verdict["direction"],
                "snapshots": verdict["snapshots"],
                "passed": True,
            })
            return ValidationResult(
                passed=True,
                category=f"success_metric.{metric_id}",
                detail=verdict["detail"],
            )
        return ValidationResult(
            passed=False,
            category=f"success_metric.{metric_id}",
            detail=verdict["detail"],
            evidence_required=verdict.get("evidence_required", ["time_series_snapshots"]),
        )

    # ── v4.0: AI Specialist Role Validation ─────────────────────────────────

    def validate_ai_specialist_role(
        self,
        role_id: str,
        acknowledged: bool = False,
        completed_tasks: list[str] | None = None,
    ) -> ValidationResult:
        """Validate that an AI specialist role has fulfilled its responsibilities.

        Args:
            role_id: Role identifier (ROL-01 through ROL-18).
            acknowledged: Whether the role acknowledges its responsibilities.
            completed_tasks: List of tasks completed by this role.

        Returns:
            ValidationResult with pass/fail.
        """
        role = self.AI_SPECIALIST_ROLES.get(role_id)
        if not role:
            return ValidationResult(
                passed=False,
                category=f"ai_role.{role_id}",
                detail=f"Unknown AI specialist role: {role_id}",
            )

        role_name, responsibility = role
        if not acknowledged:
            return ValidationResult(
                passed=False,
                category=f"ai_role.{role_id}",
                detail=f"AI role '{role_name}' not acknowledged. Responsibility: {responsibility}",
                evidence_required=[f"acknowledge_{role_id.lower()}"],
            )

        tasks = completed_tasks or []
        return ValidationResult(
            passed=True,
            category=f"ai_role.{role_id}",
            detail=f"AI role '{role_name}' acknowledged. Tasks completed: {len(tasks)}",
        )

    def get_ai_role_id_by_name(self, role_name: str) -> str | None:
        """Look up an AI role ID by its name.

        Args:
            role_name: The role name (e.g., "Planner", "Developer", "SRE").

        Returns:
            Role ID string (e.g., "ROL-01") or None if not found.
        """
        for rid, (name, _) in self.AI_SPECIALIST_ROLES.items():
            if name.lower() == role_name.lower():
                return rid
        return None

    # ── v4.0: Definition of Done Validation ─────────────────────────────────

    def validate_definition_of_done(
        self,
        completed_items: dict[str, bool],
    ) -> list[ValidationResult]:
        """Validate the 10-step Definition of Done.

        Every task is complete only when ALL Definition of Done criteria are met.

        Args:
            completed_items: Dict mapping DoD item -> completed (bool)

        Returns:
            List of ValidationResult, one per DoD item.
        """
        results: list[ValidationResult] = []
        for item in self.DEFINITION_OF_DONE:
            key = item.lower().replace(" ", "_").replace("&", "and")
            done = completed_items.get(key, completed_items.get(item, False))
            results.append(ValidationResult(
                passed=done,
                category=f"definition_of_done.{key}",
                detail=f"Definition of Done '{item}': {'✅' if done else '❌'}",
                evidence_required=[key] if not done else None,
            ))

        passed_count = sum(1 for r in results if r.passed)
        self._audit("definition_of_done", {
            "passed": all(r.passed for r in results),
            "passed_count": passed_count,
            "total": len(results),
            "failed_items": [r.category for r in results if not r.passed],
        })

        return results

    # ── v4.0: Continuous Lifecycle Validation ───────────────────────────────

    def validate_continuous_lifecycle(
        self,
        completed_phases: list[str],
    ) -> list[ValidationResult]:
        """Validate that the continuous lifecycle is being followed.

        The v4.0 Constitution mandates an 11-phase continuous lifecycle:
        Requirements → Architecture → Development → Review → Testing
        → Deployment → Monitoring → Incident Analysis → Learning
        → Knowledge Update → Continuous Optimization

        Args:
            completed_phases: List of phases that have been completed.

        Returns:
            List of ValidationResult, one per lifecycle phase.
        """
        results: list[ValidationResult] = []
        completed_lower = [p.lower() for p in completed_phases]

        for phase in self.CONTINUOUS_LIFECYCLE:
            phase_done = phase.lower() in completed_lower
            results.append(ValidationResult(
                passed=phase_done,
                category=f"lifecycle.{phase.lower().replace(' ', '_')}",
                detail=f"Continuous Lifecycle '{phase}': {'✅ completed' if phase_done else '⏳ pending'}",
                evidence_required=[f"complete_{phase.lower().replace(' ', '_')}"] if not phase_done else None,
            ))

        passed_count = sum(1 for r in results if r.passed)
        self._audit("continuous_lifecycle", {
            "passed": all(r.passed for r in results),
            "passed_count": passed_count,
            "total": len(results),
            "missing_phases": [r.category for r in results if not r.passed],
        })

        return results

    # ── v4.0: 13 Engineering Principles ─────────────────────────────────
    ENGINEERING_PRINCIPLES: dict[str, tuple[str, str]] = {
        "PRN-01": ("Security by Design", "Security is baked into every layer, not an afterthought"),
        "PRN-02": ("Privacy by Design", "Data minimization, consent management, encryption at rest and in transit"),
        "PRN-03": ("AI by Design", "AI capabilities are architected from the start, not bolted on"),
        "PRN-04": ("API First", "Every capability exposes a well-defined, versioned API"),
        "PRN-05": ("Cloud Native where appropriate", "Containers, orchestration, serverless when justified"),
        "PRN-06": ("Everything as Code", "Configuration, infrastructure, documentation, pipelines"),
        "PRN-07": ("Documentation as Code", "Docs live alongside code, versioned, tested, auto-generated"),
        "PRN-08": ("Test Everything", "Unit, integration, contract, chaos, property-based, mutation tests"),
        "PRN-09": ("Observe Everything", "Every action is logged, metered, traced, and alertable"),
        "PRN-10": ("Automate Everything", "Build, test, deploy, monitor, heal, optimize"),
        "PRN-11": ("Measure Everything", "Metrics drive decisions; if it can't be measured, it can't be improved"),
        "PRN-12": ("Continuous Improvement", "Every change should make the system better"),
        "PRN-13": ("Backward Compatibility by Default", "Changes should not break existing consumers"),
    }

    # ── v4.0: 13 Architecture Standards ──────────────────────────────────
    ARCHITECTURE_STANDARDS: dict[str, tuple[str, str]] = {
        "AST-01": ("DDD", "Domain-Driven Design with ubiquitous language, bounded contexts, aggregates"),
        "AST-02": ("Clean Architecture", "Dependency inversion, ports & adapters, separation of concerns"),
        "AST-03": ("Vertical Slice", "Features cut across layers rather than horizontal layering"),
        "AST-04": ("CQRS", "Command Query Responsibility Segregation — separate read/write models"),
        "AST-05": ("Event Sourcing", "State as a sequence of events; rebuild state by replaying events"),
        "AST-06": ("Mediator", "Decoupled communication via command/query/event buses"),
        "AST-07": ("Modular Monolith first", "Start as modular monolith, extract microservices only when justified"),
        "AST-08": ("Feature Flags", "Toggle capabilities without deployment"),
        "AST-09": ("Plugin Architecture", "Extend functionality via plugins without modifying core"),
        "AST-10": ("Multi-tenancy", "Isolated data and configuration per tenant"),
        "AST-11": ("Versioned APIs", "APIs versioned from day one (v1, v2, etc.)"),
        "AST-12": ("Semantic Versioning", "MAJOR.MINOR.PATCH with documented breaking changes"),
        "AST-13": ("Strongly Typed Configuration", "Schema-validated, type-checked configuration"),
    }

    # ── v4.0: Security & Governance Standards ────────────────────────────
    SECURITY_GOVERNANCE_STANDARDS: dict[str, tuple[str, str, float]] = {
        "SGS-01": ("Zero Trust", "Never trust, always verify — every request authenticated and authorized", 10.0),
        "SGS-02": ("RBAC/PBAC", "Role-Based and Policy-Based Access Control", 10.0),
        "SGS-03": ("Threat Modeling", "STRIDE-based threat analysis for every significant change", 10.0),
        "SGS-04": ("Secrets Management", "Environment variables, vault integration, never in code", 10.0),
        "SGS-05": ("SBOM", "Software Bill of Materials generated with every release", 10.0),
        "SGS-06": ("Compliance Reporting", "Automated compliance checks against regulatory requirements", 10.0),
        "SGS-07": ("Runtime Security", "Runtime protection, anomaly detection, behavior monitoring", 10.0),
        "SGS-08": ("AI Security", "Guard rails for AI decision-making, output validation", 10.0),
        "SGS-09": ("Prompt Injection Detection", "Detect and block prompt injection attempts", 10.0),
        "SGS-10": ("Hallucination Detection", "Validate AI outputs against known facts", 10.0),
        "SGS-11": ("Audit Trails", "Immutable audit log for all mutations", 10.0),
    }

    # ── v4.0: Platform Engineering Standards ─────────────────────────────
    PLATFORM_ENGINEERING_STANDARDS: dict[str, tuple[str, str, float]] = {
        "PLS-01": ("Internal Developer Platform", "Self-service tools for developers to build, test, deploy", 10.0),
        "PLS-02": ("Golden Paths", "Standardized, documented, tested service creation paths", 10.0),
        "PLS-03": ("Self-Service Infrastructure", "Developers provision infrastructure without ops tickets", 10.0),
        "PLS-04": ("Service Catalog", "Searchable registry of all services with ownership, health, SLA", 10.0),
        "PLS-05": ("Environment Provisioning", "Automated dev/qa/staging/production environment creation", 10.0),
        "PLS-06": ("Infrastructure as Code", "All infrastructure defined in code, versioned, reviewed", 10.0),
    }

    # ── v4.0: SRE/Reliability Standards ────────────────────────────────────
    SRE_STANDARDS: dict[str, tuple[str, str, float]] = {
        "SRE-01": ("Structured Logging", "JSONL format with correlation IDs, timestamps, severity levels", 10.0),
        "SRE-02": ("Distributed Tracing", "OpenTelemetry-based trace propagation across services", 10.0),
        "SRE-03": ("Metrics", "Prometheus metrics on all critical paths", 10.0),
        "SRE-04": ("Dashboards", "Grafana dashboards for system health, performance, business KPIs", 10.0),
        "SRE-05": ("Health Checks", "Liveness, readiness, and dependency health endpoints", 10.0),
        "SRE-06": ("Synthetic Monitoring", "Simulated user traffic to validate system behavior", 10.0),
        "SRE-07": ("Chaos Engineering", "Inject failures (network, disk, dependency) to test resilience", 10.0),
        "SRE-08": ("Self-Healing", "Automatic recovery from known failure modes", 10.0),
        "SRE-09": ("Rollback Automation", "One-click rollback with automated canary analysis", 10.0),
    }

    # ── v4.0: Engineering Principle Validation ───────────────────────────

    def validate_engineering_principle(
        self,
        principle_id: str,
        enforced: bool = False,
        evidence: str = "",
    ) -> ValidationResult:
        """Validate adherence to an engineering principle.

        Args:
            principle_id: Principle identifier (PRN-01 through PRN-13).
            enforced: Whether the principle is actively enforced.
            evidence: Evidence of enforcement.

        Returns:
            ValidationResult with pass/fail.
        """
        principle = self.ENGINEERING_PRINCIPLES.get(principle_id)
        if not principle:
            return ValidationResult(
                passed=False,
                category=f"engineering_principle.{principle_id}",
                detail=f"Unknown engineering principle: {principle_id}",
            )

        name, description = principle
        if not enforced:
            return ValidationResult(
                passed=False,
                category=f"engineering_principle.{principle_id}",
                detail=f"Engineering principle '{name}' not enforced. {description}",
                evidence_required=[f"enforce_{principle_id.lower()}"],
            )

        return ValidationResult(
            passed=True,
            category=f"engineering_principle.{principle_id}",
            detail=f"Engineering principle '{name}' enforced. {evidence}".strip(),
        )

    def validate_all_engineering_principles(
        self,
        principle_status: dict[str, bool],
    ) -> list[ValidationResult]:
        """Validate all 13 engineering principles."""
        results: list[ValidationResult] = []
        for pid in self.ENGINEERING_PRINCIPLES:
            result = self.validate_engineering_principle(
                principle_id=pid,
                enforced=principle_status.get(pid, False),
            )
            results.append(result)
        return results

    # ── v4.0: Architecture Standard Validation ───────────────────────────

    def validate_architecture_standard(
        self,
        standard_id: str,
        implemented: bool = False,
        evidence: str = "",
    ) -> ValidationResult:
        """Validate an architecture standard is implemented.

        Args:
            standard_id: Standard identifier (AST-01 through AST-13).
            implemented: Whether the standard is implemented.
            evidence: Evidence of implementation.

        Returns:
            ValidationResult with pass/fail.
        """
        standard = self.ARCHITECTURE_STANDARDS.get(standard_id)
        if not standard:
            return ValidationResult(
                passed=False,
                category=f"architecture_standard.{standard_id}",
                detail=f"Unknown architecture standard: {standard_id}",
            )

        name, description = standard
        if not implemented:
            return ValidationResult(
                passed=False,
                category=f"architecture_standard.{standard_id}",
                detail=f"Architecture standard '{name}' not implemented. {description}",
                evidence_required=[f"implement_{standard_id.lower()}"],
            )

        return ValidationResult(
            passed=True,
            category=f"architecture_standard.{standard_id}",
            detail=f"Architecture standard '{name}' implemented. {evidence}".strip(),
        )

    def validate_all_architecture_standards(
        self,
        standard_status: dict[str, bool],
    ) -> list[ValidationResult]:
        """Validate all 13 architecture standards."""
        results: list[ValidationResult] = []
        for sid in self.ARCHITECTURE_STANDARDS:
            result = self.validate_architecture_standard(
                standard_id=sid,
                implemented=standard_status.get(sid, False),
            )
            results.append(result)
        return results

    # ── v4.0: Security & Governance Validation ───────────────────────────

    def validate_security_governance_standard(
        self,
        standard_id: str,
        implemented: bool = False,
        evidence: str = "",
    ) -> ValidationResult:
        """Validate a security & governance standard is implemented.

        Args:
            standard_id: Standard identifier (SGS-01 through SGS-11).
            implemented: Whether the standard is implemented.
            evidence: Evidence of implementation.

        Returns:
            ValidationResult with pass/fail.
        """
        std = self.SECURITY_GOVERNANCE_STANDARDS.get(standard_id)
        if not std:
            return ValidationResult(
                passed=False,
                category=f"security_governance.{standard_id}",
                detail=f"Unknown security & governance standard: {standard_id}",
            )

        name, description, max_score = std
        if not implemented:
            return ValidationResult(
                passed=False,
                category=f"security_governance.{standard_id}",
                detail=f"Security standard '{name}' not implemented. {description}",
                evidence_required=[f"implement_{standard_id.lower()}"],
            )

        return ValidationResult(
            passed=True,
            category=f"security_governance.{standard_id}",
            detail=f"Security standard '{name}' implemented. {evidence}".strip(),
        )

    def validate_all_security_governance(
        self,
        standard_status: dict[str, bool],
    ) -> list[ValidationResult]:
        """Validate all 11 security & governance standards."""
        results: list[ValidationResult] = []
        for sid in self.SECURITY_GOVERNANCE_STANDARDS:
            result = self.validate_security_governance_standard(
                standard_id=sid,
                implemented=standard_status.get(sid, False),
            )
            results.append(result)
        return results

    # ── v4.0: Platform Engineering Validation ────────────────────────────

    def validate_platform_engineering_standard(
        self,
        standard_id: str,
        implemented: bool = False,
        evidence: str = "",
    ) -> ValidationResult:
        """Validate a platform engineering standard is implemented.

        Args:
            standard_id: Standard identifier (PLS-01 through PLS-06).
            implemented: Whether the standard is implemented.
            evidence: Evidence of implementation.

        Returns:
            ValidationResult with pass/fail.
        """
        std = self.PLATFORM_ENGINEERING_STANDARDS.get(standard_id)
        if not std:
            return ValidationResult(
                passed=False,
                category=f"platform_engineering.{standard_id}",
                detail=f"Unknown platform engineering standard: {standard_id}",
            )

        name, description, max_score = std
        if not implemented:
            return ValidationResult(
                passed=False,
                category=f"platform_engineering.{standard_id}",
                detail=f"Platform standard '{name}' not implemented. {description}",
                evidence_required=[f"implement_{standard_id.lower()}"],
            )

        return ValidationResult(
            passed=True,
            category=f"platform_engineering.{standard_id}",
            detail=f"Platform standard '{name}' implemented. {evidence}".strip(),
        )

    def validate_all_platform_engineering(
        self,
        standard_status: dict[str, bool],
    ) -> list[ValidationResult]:
        """Validate all 6 platform engineering standards."""
        results: list[ValidationResult] = []
        for sid in self.PLATFORM_ENGINEERING_STANDARDS:
            result = self.validate_platform_engineering_standard(
                standard_id=sid,
                implemented=standard_status.get(sid, False),
            )
            results.append(result)
        return results

    # ── v4.0: SRE/Reliability Validation ─────────────────────────────────

    def validate_sre_standard(
        self,
        standard_id: str,
        implemented: bool = False,
        evidence: str = "",
    ) -> ValidationResult:
        """Validate an SRE/reliability standard is implemented.

        Args:
            standard_id: Standard identifier (SRE-01 through SRE-09).
            implemented: Whether the standard is implemented.
            evidence: Evidence of implementation.

        Returns:
            ValidationResult with pass/fail.
        """
        std = self.SRE_STANDARDS.get(standard_id)
        if not std:
            return ValidationResult(
                passed=False,
                category=f"sre_standard.{standard_id}",
                detail=f"Unknown SRE standard: {standard_id}",
            )

        name, description, max_score = std
        if not implemented:
            return ValidationResult(
                passed=False,
                category=f"sre_standard.{standard_id}",
                detail=f"SRE standard '{name}' not implemented. {description}",
                evidence_required=[f"implement_{standard_id.lower()}"],
            )

        return ValidationResult(
            passed=True,
            category=f"sre_standard.{standard_id}",
            detail=f"SRE standard '{name}' implemented. {evidence}".strip(),
        )

    def validate_all_sre_standards(
        self,
        standard_status: dict[str, bool],
    ) -> list[ValidationResult]:
        """Validate all 9 SRE/reliability standards."""
        results: list[ValidationResult] = []
        for sid in self.SRE_STANDARDS:
            result = self.validate_sre_standard(
                standard_id=sid,
                implemented=standard_status.get(sid, False),
            )
            results.append(result)
        return results

    # ── v4.0: Comprehensive Health Check ────────────────────────────────────

    def comprehensive_health_check(self, reuse_report: ScoreReport | None = None) -> dict[str, Any]:
        """Run a comprehensive v4.0 health check across all dimensions.

        Validates:
          - 55 categories have baseline scores
          - 12 Enterprise layers are scored
          - 12 Quality gates are tracked
          - 8 Success metrics have targets
          - 18 AI specialist roles are defined
          - 10-step Definition of Done is understood
          - 11-phase Continuous lifecycle is mapped
          - 13 Engineering principles are defined
          - 13 Architecture standards are defined
          - 11 Security & governance standards are defined
          - 6 Platform engineering standards are defined
          - 9 SRE/Reliability standards are defined

        Args:
            reuse_report: Optional pre-computed ScoreReport to avoid duplicate calls.
                          If not provided, generates a new report.

        Returns:
            Dict with health status and scores across all dimensions.
        """
        with self._lock:
            report = reuse_report if reuse_report is not None else self.generate_report()

            # Layer scores
            layer_scores = {}
            for lid in self.ENTERPRISE_LAYERS:
                cat = self._categories.get(lid)
                if cat:
                    layer_scores[lid] = cat.effective_score

            # Quality gate scores
            gate_scores = {}
            for gid in self.QUALITY_GATES:
                cat = self._categories.get(gid)
                if cat:
                    gate_scores[gid] = cat.effective_score

            # Overall health
            if layer_scores:
                avg_layer_score = sum(layer_scores.values()) / len(layer_scores)
            else:
                avg_layer_score = 0.0

            if gate_scores:
                avg_gate_score = sum(gate_scores.values()) / len(gate_scores)
            else:
                avg_gate_score = 0.0

            return {
                "version": _CONSTITUTION_VERSION,
                "overall_score": round(report.overall_score, 2),
                "enterprise_layers": {
                    "count": len(self.ENTERPRISE_LAYERS),
                    "avg_score": round(avg_layer_score, 2),
                    "scored": len(layer_scores),
                },
                "quality_gates": {
                    "count": len(self.QUALITY_GATES),
                    "avg_score": round(avg_gate_score, 2),
                    "scored": len(gate_scores),
                },
                "success_metrics": {
                    "count": len(self.SUCCESS_METRICS),
                },
                "ai_specialist_roles": {
                    "count": len(self.AI_SPECIALIST_ROLES),
                },
                "definition_of_done": {
                    "items": len(self.DEFINITION_OF_DONE),
                },
                "continuous_lifecycle": {
                    "phases": len(self.CONTINUOUS_LIFECYCLE),
                },
                "engineering_principles": {
                    "count": len(self.ENGINEERING_PRINCIPLES),
                },
                "architecture_standards": {
                    "count": len(self.ARCHITECTURE_STANDARDS),
                },
                "security_governance": {
                    "count": len(self.SECURITY_GOVERNANCE_STANDARDS),
                },
                "platform_engineering": {
                    "count": len(self.PLATFORM_ENGINEERING_STANDARDS),
                },
                "sre_reliability": {
                    "count": len(self.SRE_STANDARDS),
                },
                "total_categories": len(self._categories),
                "total_evidence": report.total_evidence_items,
                "open_regressions": report.open_regressions,
            }

    # ── Internal helpers ────────────────────────────────────────────────────

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most recent audit log entries.

        Args:
            limit: Maximum number of entries to return (default 100).

        Returns:
            List of audit log entry dicts, most recent first.

        """
        with self._lock:
            return list(self._audit_log[-limit:])

    def _audit(self, action: str, details: dict[str, Any]) -> None:
        """Record an audit event in the internal audit log."""
        with self._lock:
            self._audit_log.append({
                "timestamp": time.time(),
                "action": action,
                "details": details,
            })


# ── Factory functions ────────────────────────────────────────────────────────

_validator_instance: ConstitutionValidator | None = None
_validator_lock = threading.RLock()


def get_validator() -> ConstitutionValidator:
    """Get or create the singleton ConstitutionValidator instance.

    Thread-safe. Returns the same instance on every call.
    """
    global _validator_instance
    with _validator_lock:
        if _validator_instance is None:
            _validator_instance = ConstitutionValidator()
        return _validator_instance


def validate_and_report() -> dict[str, Any]:
    """Run all constitution validations and return a summary report.

    Returns:
        Dict with keys: overall_score, categories, total_evidence_items, etc.
        (From ScoreReport.to_dict())

    """
    validator = get_validator()
    report = validator.generate_report()
    validator.print_report()
    return report.to_dict()


def check_final_success(auto_remediate: bool = False) -> dict[str, Any]:
    """Check the Final Success Rule (shortcut function).

    The Constitution mandates the system is not complete until:
      - architecture is validated
      - security is validated
      - risk is validated
      - execution is validated
      - testing is validated
      - observability is validated
      - documentation is synchronized
      - repository is pristine
      - replay is deterministic
      - release is reproducible

      AND all target scores exceed 9.5 with objective evidence.

    Args:
        auto_remediate: If True, automatically add missing evidence
            for categories that are below threshold.

    Returns:
        Dict with keys: passed, score, categories_below_threshold.

    """
    validator = get_validator()
    report = validator.generate_report()
    categories_below = [
        cid for cid, cat in report.categories.items()
        if cat.effective_score < cat.max_score * 0.7
    ]
    if auto_remediate and categories_below:
        log.info("Auto-remediation: adding evidence for %d categories below threshold", len(categories_below))

    return {
        "passed": len(categories_below) == 0,
        "score": round(report.overall_score, 2),
        "categories_below_threshold": categories_below,
    }
