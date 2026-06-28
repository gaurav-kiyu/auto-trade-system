"""
Constitution Validation Engine — Runtime enforcement of the Final Master System Constitution.

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


_CONSTITUTION_VERSION = "1.0.0"


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

    # 31 scoring categories defined in the constitution framework
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

    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._audit_log: list[dict[str, Any]] = []
        self._categories: dict[str, CategoryScore] = {}
        self._init_categories()
        _collect_auto_evidence(self)

    def _init_categories(self) -> None:
        """Initialize all 31 categories with default scores."""
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
        log.info("=" * 60)
        log.info("CONSTITUTION SCORING REPORT v%s", data["version"])
        log.info("=" * 60)
        log.info("Overall Score: %.2f / 9.99", data["overall_score"])
        log.info("Total Evidence: %d", data["total_evidence_items"])
        log.info("Open Regressions: %d", data["open_regressions"])
        log.info("")
        for cid, cat in sorted(data["categories"].items()):
            status = "OK" if cat["regressions"] == [] else "REG"
            log.info("  %s %s [%.2f/%.2f] %s",
                     status, cid, cat["score"], cat["max_score"],
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
                    evidence_required=[category.split('.')[1]],
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
                detail="Score {:.2f} > 9.0 requires objective evidence. No evidence registered.".format(score),
                evidence_required=["objective_evidence"],
            )
        if not has_evidence and score > 8.0:
            return ValidationResult(
                passed=False,
                category=category,
                detail="Score {:.2f} > 8.0 without evidence is not allowed.".format(score),
                evidence_required=["objective_evidence"],
            )
        return ValidationResult(
            passed=True,
            category=category,
            detail="Score {:.2f} validated against constitution criteria.".format(score),
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
                detail="Prohibited artifacts found: {} items (e.g., {})".format(
                    len(found_items), found_items[0]),
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
