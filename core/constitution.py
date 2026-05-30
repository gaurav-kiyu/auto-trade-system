"""
Constitution Validation Engine — Runtime enforcement of the Final Master System Constitution.

Provides:
  - Scoring validation against the 23-category framework
  - Change pipeline verification (10-step mandate)
  - Pre-implementation checklist enforcement
  - Evidence-based scoring compliance checks
  - Audit trail recording for constitution-related events

Usage:
    from core.constitution import ConstitutionValidator

    validator = ConstitutionValidator()
    result = validator.validate_change_pipeline(evidence={
        "review": True,
        "impact_analysis": True,
        "design": True,
        "implementation": True,
        "testing": True,
        "validation": True,
        "documentation": True,
        "audit": True,
        "acceptance": True,
        "release": True,
    })
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CONSTITUTION_VERSION = "1.0.0"

# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class ScoreEvidence:
    """A single piece of evidence supporting a score."""
    description: str
    evidence_type: str  # test_pass, manual_test, code_review, documentation, audit_log, chaos, production
    weight: float = 0.5
    verified: bool = False
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class CategoryScore:
    """Score for a single category in the 23-category framework."""
    category_id: str  # e.g., "ARCH-01"
    category_name: str
    max_score: float
    score: float = 5.0  # Base score starts at adequate
    evidence: list[ScoreEvidence] = field(default_factory=list)
    audits: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)

    @property
    def effective_score(self) -> float:
        """Calculate effective score based on evidence and regressions."""
        evidence_bonus = sum(
            ev.weight for ev in self.evidence if ev.verified
        )
        regression_penalty = 2.0 * len(self.regressions)
        raw = self.score + evidence_bonus - regression_penalty
        # Cap at max_score and enforce 8.0 ceiling without evidence
        capped = min(raw, self.max_score)
        if not self.evidence and capped > 8.0:
            capped = 8.0
        return max(0.0, capped)

    @property
    def needs_9_audit(self) -> bool:
        """Scores above 9.0 require full audits."""
        return self.effective_score >= 9.0

    @property
    def needs_95_audit(self) -> bool:
        """Scores above 9.5 require extended audits."""
        return self.effective_score >= 9.5


@dataclass
class ValidationResult:
    """Result of a constitution validation check."""
    passed: bool
    category: str
    detail: str
    evidence_required: list[str] | None = None


@dataclass
class ScoreReport:
    """Complete scoring report for all categories."""
    timestamp: float
    version: str
    categories: dict[str, CategoryScore]
    overall_score: float
    total_evidence_items: int
    open_regressions: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "version": self.version,
            "overall_score": round(self.overall_score, 2),
            "total_evidence_items": self.total_evidence_items,
            "open_regressions": self.open_regressions,
            "categories": {
                cid: {
                    "score": round(cat.effective_score, 2),
                    "max_score": cat.max_score,
                    "evidence": [ev.description for ev in cat.evidence if ev.verified],
                    "audits": cat.audits,
                    "regressions": cat.regressions,
                }
                for cid, cat in self.categories.items()
            },
        }


# ── Constitution Validator ────────────────────────────────────────────────────


class ConstitutionValidator:
    """Validates code changes against the Final Master System Constitution."""

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

    # 23 scoring categories defined in the constitution framework
    CATEGORIES: dict[str, tuple[str, float]] = {
        "ARCH-01": ("Boundary enforcement", 9.5),
        "ARCH-02": ("Single responsibility", 9.0),
        "ARCH-03": ("Port/adapter separation", 9.5),
        "ARCH-04": ("No circular dependencies", 9.0),
        "SEC-01": ("Authentication", 9.5),
        "SEC-02": ("Authorization/RBAC", 9.5),
        "SEC-03": ("Secret management", 9.5),
        "SEC-04": ("Audit trail", 9.5),
        "RSK-01": ("Hard halt enforcement", 9.9),
        "RSK-02": ("Loss limits", 9.9),
        "RSK-03": ("Position sizing", 9.0),
        "RSK-04": ("Fail-closed", 9.5),
        "EXE-01": ("Exactly-once semantics", 9.9),
        "EXE-02": ("Idempotent retry", 9.5),
        "EXE-03": ("State machine correctness", 9.5),
        "EXE-04": ("Reconciliation", 9.5),
        "TST-01": ("Test coverage", 9.0),
        "TST-02": ("Chaos testing", 9.9),
        "TST-03": ("Contract testing", 9.5),
        "TST-04": ("Regression testing", 9.0),
        "OBS-01": ("Structured logging", 9.0),
        "OBS-02": ("Metrics", 9.0),
        "OBS-03": ("Health checks", 9.0),
        "OBS-04": ("Alerting", 9.0),
        "GOV-01": ("Documentation sync", 9.5),
        "GOV-02": ("Repository hygiene", 9.0),
        "GOV-03": ("Technical debt tracking", 9.0),
        "GOV-04": ("Release governance", 9.5),
        "DR-01": ("Database migration", 9.0),
        "DR-02": ("State persistence", 9.0),
        "DR-03": ("WAL journal", 9.5),
    }

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._audit_log: list[dict[str, Any]] = []
        self._categories: dict[str, CategoryScore] = {}
        self._init_categories()

    def _init_categories(self) -> None:
        """Initialize all 23 categories with default scores."""
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
                    detail=f"Change pipeline step '{step}' missing — all 10 steps required",
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
        log.info("=" * 60)
        log.info("CONSTITUTION SCORING REPORT v%s", data["version"])
        log.info("=" * 60)
        log.info("Overall Score: %.2f / 9.99", data["overall_score"])
        log.info("Total Evidence: %d", data["total_evidence_items"])
        log.info("Open Regressions: %d", data["open_regressions"])
        log.info("")
        for cid, cat in sorted(data["categories"].items()):
            status = "✓" if cat["regressions"] == [] else "✗"
            log.info("  %s %s [%.2f/%.2f] %s",
                     status, cid, cat["score"], cat["max_score"],
                     "audit" if cat["audits"] else "")
        log.info("=" * 60)

    # ── Audit ────────────────────────────────────────────────────────────────

    def _audit(self, action: str, detail: dict[str, Any]) -> None:
        with self._lock:
            self._audit_log.append({
                "ts": time.time(),
                "action": action,
                "detail": detail,
            })

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._audit_log[-limit:])

    # ── Feature Acceptance ───────────────────────────────────────────────────

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
        """Validate that a feature meets all acceptance criteria.

        The Constitution mandates:
          - fully tested, fully validated, beneficial, secure, replay-safe,
            risk-safe, maintainable, documented

        If not beneficial: REJECT. If not safe: REJECT.
        """
        results: list[ValidationResult] = []

        if not beneficial:
            return [ValidationResult(
                passed=False,
                category="feature_acceptance.beneficial",
                detail="REJECTED: Feature is not beneficial",
            )]

        checks = [
            ("fully_tested", fully_tested, "Feature must be fully tested"),
            ("fully_validated", fully_validated, "Feature must be fully validated"),
            ("secure", secure, "Feature must be secure"),
            ("replay_safe", replay_safe, "Feature must be replay-safe"),
            ("risk_safe", risk_safe, "Feature must be risk-safe"),
            ("maintainable", maintainable, "Feature must be maintainable"),
            ("documented", documented, "Feature must be documented"),
        ]

        for name, passed, detail in checks:
            if not passed:
                results.append(ValidationResult(
                    passed=False,
                    category=f"feature_acceptance.{name}",
                    detail=f"REJECTED: {detail}",
                ))

        if not results:
            results.append(ValidationResult(
                passed=True,
                category="feature_acceptance",
                detail="All feature acceptance criteria met: ACCEPTED",
            ))

        self._audit("feature_acceptance", {
            "accepted": not any(not r.passed and "REJECTED" in r.detail for r in results),
            "failures": [r.category for r in results if not r.passed],
        })

        return results

    # ── Repository Hygiene ───────────────────────────────────────────────────

    def validate_repository_hygiene(self, project_root: str | None = None) -> list[ValidationResult]:
        """Check repository for prohibited artifacts.

        The Constitution mandates that release artifacts MUST NOT contain:
          .venv, __pycache__, .pytest_cache, .ruff_cache, build residue,
          temporary files, stale reports, orphaned assets, duplicate implementations
        """
        results: list[ValidationResult] = []
        root = Path(project_root) if project_root else Path.cwd()

        prohibited_patterns: list[tuple[list[Path], str]] = [
            (list(root.rglob("__pycache__")), "Python cache directories"),
            (list(root.rglob("*.pyc")), "Compiled Python files"),
            (list(root.rglob(".pytest_cache")), "Pytest cache"),
            (list(root.rglob(".ruff_cache")), "Ruff cache"),
            (list(root.rglob(".mypy_cache")), "Mypy cache"),
            (list(root.rglob(".hypothesis")), "Hypothesis cache"),
        ]

        violations: list[str] = []
        for matches, description in prohibited_patterns:
            if matches:
                violations.append(f"{description}: {len(matches)} items found")

        if violations:
            results.append(ValidationResult(
                passed=False,
                category="hygiene.prohibited_artifacts",
                detail=f"Repository hygiene violations: {'; '.join(violations[:5])}",
            ))
        else:
            results.append(ValidationResult(
                passed=True,
                category="hygiene.prohibited_artifacts",
                detail="No prohibited artifacts found",
            ))

        # Check .gitignore exists
        gitignore = root / ".gitignore"
        results.append(ValidationResult(
            passed=gitignore.exists(),
            category="hygiene.gitignore",
            detail=".gitignore present" if gitignore.exists() else ".gitignore missing",
        ))

        return results

    # ── Evidence-Based Scoring Check ─────────────────────────────────────────

    def validate_score_evidence(
        self,
        score: float,
        category: str,
        has_evidence: bool = False,
    ) -> ValidationResult:
        """Validate that scores above thresholds have required evidence.

        The Constitution mandates:
          - Scores above 9.0 require evidence
          - Scores above 9.5 require full audits
          - Without evidence, no score may exceed 8.0
        """
        if score > 9.5:
            cat = self._categories.get(category)
            audit_types = ["architecture", "security", "risk", "execution",
                           "testing", "observability", "disaster_recovery",
                           "chaos", "black_swan"]
            if cat:
                missing_audits = [a for a in audit_types if a not in cat.audits]
                if missing_audits:
                    return ValidationResult(
                        passed=False,
                        category=f"score_evidence.{category}",
                        detail=f"Score {score:.1f} requires audits: {', '.join(missing_audits)}",
                        evidence_required=missing_audits,
                    )

        if score > 9.0 and not has_evidence:
            return ValidationResult(
                passed=False,
                category=f"score_evidence.{category}",
                detail=f"Score {score:.1f} exceeds 9.0 but no evidence provided",
                evidence_required=["evidence"],
            )

        if not has_evidence and score > 8.0:
            return ValidationResult(
                passed=False,
                category=f"score_evidence.{category}",
                detail=f"Without evidence, score {score:.1f} capped at 8.0. Provide evidence or reduce score.",
            )

        return ValidationResult(
            passed=True,
            category=f"score_evidence.{category}",
            detail=f"Score {score:.1f} has required evidence",
        )


# ── Module-level singleton ────────────────────────────────────────────────────

_VALIDATOR: ConstitutionValidator | None = None
_VALIDATOR_LOCK = threading.Lock()


def get_validator() -> ConstitutionValidator:
    """Get or create the singleton constitution validator."""
    global _VALIDATOR
    if _VALIDATOR is None:
        with _VALIDATOR_LOCK:
            if _VALIDATOR is None:
                _VALIDATOR = ConstitutionValidator()
    return _VALIDATOR


def validate_and_report() -> dict[str, Any]:
    """Run all constitution validations and return a summary report."""
    validator = get_validator()
    report = validator.generate_report()
    validator.print_report()
    return report.to_dict()
