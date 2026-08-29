"""Release Intelligence — Release Readiness Scoring & Deployment Decisions (Pillar x).

Evaluates release readiness across:
- Release Readiness Score (0-100)
- Rollback Readiness (migration has rollback plan)
- Migration Safety (DB schema changes)
- Dependency Readiness (all deps are compatible)
- Infrastructure Readiness (configs, env vars)
- Performance Prediction (expected impact)
- Risk Prediction (regression risk)
- Canary Recommendation (canary percentage)
- Blue-Green Recommendation
- Feature Flag Recommendation
- Deployment Approval Score

Usage:
    from core.release_intelligence import get_release_intelligence

    ri = get_release_intelligence()
    assessment = ri.assess_release(
        version="v2.57.0",
        files_changed=["core/risk_service.py"],
        has_db_migration=False,
        has_config_changes=True,
        has_dependency_changes=False,
    )
    print(assessment.release_readiness_score)
    print(assessment.approval_recommendation)
    print(assessment.rollback_plan)

Design:
- Thread-safe singleton with RLock
- JSON persistence for release history
- Integrates with ChangeRiskScorer for risk prediction
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

RELEASE_HISTORY_FILE = "json/release_history.json"
MAX_RELEASE_HISTORY = 200

# Canary stages
CANARY_STAGES = {
    "NONE": 0,
    "TEN_PERCENT": 10,
    "TWENTY_FIVE_PERCENT": 25,
    "FIFTY_PERCENT": 50,
    "ALL": 100,
}

# Rollback plan templates
ROLLBACK_TEMPLATES = {
    "config": "Restore previous config version from git: git checkout HEAD~1 config.json",
    "db_migration": "Run rollback migration: python scripts/rollback_migration.py",
    "dependency": "Restore previous requirements files: git checkout HEAD~1 requirements*.txt",
    "code": "Revert to previous tag: git revert --no-commit HEAD~N",
}


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class ReleaseAssessment:
    """Complete release readiness assessment."""

    version: str
    release_readiness_score: float = 0.0  # 0-100
    assessed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Component scores
    risk_score: float = 0.0  # 0-100 (higher = riskier)
    migration_safety_score: float = 100.0
    dependency_readiness_score: float = 100.0
    infrastructure_readiness_score: float = 100.0

    # Recommendations
    approval_recommendation: str = "PENDING"  # APPROVED, CONDITIONAL, BLOCKED
    canary_recommendation_pct: int = 100  # 0, 10, 25, 50, 100
    blue_green_recommended: bool = False
    feature_flag_recommended: bool = False

    # Rollback
    has_rollback_plan: bool = False
    rollback_plan_steps: list[str] = field(default_factory=list)
    rollback_estimated_minutes: int = 15

    # Details
    n_files_changed: int = 0
    has_db_migration: bool = False
    has_config_changes: bool = False
    has_dependency_changes: bool = False
    predicted_performance_impact: str = "NONE"
    predicted_regression_risk: str = "LOW"
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "release_readiness_score": round(self.release_readiness_score, 1),
            "assessed_at": self.assessed_at,
            "risk_score": round(self.risk_score, 1),
            "migration_safety_score": round(self.migration_safety_score, 1),
            "dependency_readiness_score": round(self.dependency_readiness_score, 1),
            "infrastructure_readiness_score": round(self.infrastructure_readiness_score, 1),
            "approval_recommendation": self.approval_recommendation,
            "canary_recommendation_pct": self.canary_recommendation_pct,
            "blue_green_recommended": self.blue_green_recommended,
            "feature_flag_recommended": self.feature_flag_recommended,
            "has_rollback_plan": self.has_rollback_plan,
            "rollback_plan_steps": self.rollback_plan_steps[:5],
            "rollback_estimated_minutes": self.rollback_estimated_minutes,
            "n_files_changed": self.n_files_changed,
            "has_db_migration": self.has_db_migration,
            "has_config_changes": self.has_config_changes,
            "has_dependency_changes": self.has_dependency_changes,
            "predicted_performance_impact": self.predicted_performance_impact,
            "predicted_regression_risk": self.predicted_regression_risk,
            "warnings": self.warnings[:10],
            "recommendations": self.recommendations[:10],
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            f"  RELEASE INTELLIGENCE: {self.version}",
            "═" * 60,
            f"  Readiness Score: {self.release_readiness_score:.1f}/100",
            f"  Approval: {self.approval_recommendation}",
            f"  Canary: {self.canary_recommendation_pct}%  |  "
            f"Blue-Green: {self.blue_green_recommended}  |  "
            f"Feature Flag: {self.feature_flag_recommended}",
            "",
            "  Scores:",
            f"    Risk Score:           {self.risk_score:.1f}/100",
            f"    Migration Safety:     {self.migration_safety_score:.1f}/100",
            f"    Dependency Readiness: {self.dependency_readiness_score:.1f}/100",
            f"    Infrastructure:       {self.infrastructure_readiness_score:.1f}/100",
            "",
            f"  Files Changed: {self.n_files_changed}",
            f"  DB Migration: {self.has_db_migration}  |  "
            f"Config: {self.has_config_changes}  |  "
            f"Deps: {self.has_dependency_changes}",
            f"  Perf Impact: {self.predicted_performance_impact}  |  "
            f"Regression Risk: {self.predicted_regression_risk}",
            "",
            f"  Rollback Plan: {'Yes' if self.has_rollback_plan else 'No'} "
            f"(~{self.rollback_estimated_minutes} min)",
        ]
        if self.rollback_plan_steps:
            for step in self.rollback_plan_steps[:3]:
                lines.append(f"    → {step}")
        if self.warnings:
            lines.append("\n  Warnings:")
            for w in self.warnings[:3]:
                lines.append(f"    ⚠ {w}")
        if self.recommendations:
            lines.append("\n  Recommendations:")
            for r in self.recommendations[:3]:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


@dataclass
class ReleaseRecord:
    """Historical release record."""

    version: str
    readiness_score: float
    approved: bool
    deployed_successfully: bool | None
    timestamp: str
    n_incidents_post_release: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "readiness_score": round(self.readiness_score, 1),
            "approved": self.approved,
            "deployed_successfully": self.deployed_successfully,
            "timestamp": self.timestamp,
            "n_incidents_post_release": self.n_incidents_post_release,
        }


# ── Release Intelligence Engine ──────────────────────────────────────────────


class ReleaseIntelligenceEngine:
    """Assesses release readiness and provides deployment recommendations.

    Evaluates:
    - Risk from ChangeRiskScorer
    - Migration safety
    - Dependency readiness
    - Infrastructure readiness
    - Perform prediction
    - Rollback plan availability
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._release_history: list[ReleaseRecord] = []
        self._load_history()

    # ── Public API ─────────────────────────────────────────────────────────

    def assess_release(
        self,
        version: str,
        files_changed: list[str] | None = None,
        has_db_migration: bool = False,
        has_config_changes: bool = False,
        has_dependency_changes: bool = False,
        risk_score: float | None = None,
    ) -> ReleaseAssessment:
        """Assess release readiness.

        Args:
            version: Release version string (e.g., "v2.57.0").
            files_changed: List of files changed.
            has_db_migration: Whether this release includes DB migration.
            has_config_changes: Whether config files changed.
            has_dependency_changes: Whether dependencies changed.
            risk_score: Optional pre-computed risk score (0-100). Auto-computed if None.

        Returns:
            ReleaseAssessment with readiness scores and recommendations.
        """
        files_changed = files_changed or []
        assessment = ReleaseAssessment(
            version=version,
            n_files_changed=len(files_changed),
            has_db_migration=has_db_migration,
            has_config_changes=has_config_changes,
            has_dependency_changes=has_dependency_changes,
        )

        with self._lock:
            # 1. Risk score
            if risk_score is not None:
                assessment.risk_score = risk_score
            else:
                assessment.risk_score = self._compute_risk_score(files_changed)
            fire_score = assessment.risk_score

            # 2. Migration safety
            if has_db_migration:
                assessment.migration_safety_score = self._score_migration_safety(
                    files_changed
                )

            # 3. Dependency readiness
            if has_dependency_changes:
                assessment.dependency_readiness_score = (
                    self._score_dependency_readiness()
                )

            # 4. Infrastructure readiness
            if has_config_changes:
                assessment.infrastructure_readiness_score = (
                    self._score_infrastructure_readiness(files_changed)
                )

            # 5. Performance prediction
            assessment.predicted_performance_impact = (
                self._predict_performance_impact(files_changed)
            )

            # 6. Regression risk
            assessment.predicted_regression_risk = (
                self._predict_regression_risk(
                    files_changed, has_db_migration, fire_score
                )
            )

            # 7. Compute overall readiness score
            assessment.release_readiness_score = self._compute_readiness_score(
                assessment
            )

            # 8. Determine approval
            assessment.approval_recommendation = self._determine_approval(
                assessment
            )

            # 9. Canary / Blue-Green / Feature flag recommendation
            (
                assessment.canary_recommendation_pct,
                assessment.blue_green_recommended,
                assessment.feature_flag_recommended,
            ) = self._determine_deployment_strategy(assessment)

            # 10. Rollback plan
            (
                assessment.has_rollback_plan,
                assessment.rollback_plan_steps,
                assessment.rollback_estimated_minutes,
            ) = self._generate_rollback_plan(assessment)

            # 11. Warnings and recommendations
            assessment.warnings = self._generate_warnings(assessment)
            assessment.recommendations = self._generate_recommendations(
                assessment
            )

            # Record the release assessment
            self._release_history.append(ReleaseRecord(
                version=version,
                readiness_score=assessment.release_readiness_score,
                approved=assessment.approval_recommendation == "APPROVED",
                deployed_successfully=None,
                timestamp=assessment.assessed_at,
            ))
            self._save_history()

        return assessment

    def record_deployment_outcome(
        self, version: str, success: bool, n_incidents: int = 0
    ) -> bool:
        """Record deployment outcome for historical tracking."""
        with self._lock:
            for rec in self._release_history:
                if rec.version == version:
                    rec.deployed_successfully = success
                    rec.n_incidents_post_release = n_incidents
                    self._save_history()
                    return True
            return False

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get release assessment history."""
        with self._lock:
            return [r.to_dict() for r in self._release_history[-limit:]]

    def get_stats(self) -> dict[str, Any]:
        """Get release intelligence statistics."""
        with self._lock:
            total = len(self._release_history)
            approved = sum(1 for r in self._release_history if r.approved)
            successful = sum(
                1 for r in self._release_history if r.deployed_successfully is True
            )
            return {
                "total_releases_assessed": total,
                "approved": approved,
                "deployed_successfully": successful,
                "failed_deployments": sum(
                    1 for r in self._release_history
                    if r.deployed_successfully is False
                ),
                "avg_readiness_score": round(
                    sum(r.readiness_score for r in self._release_history) / max(total, 1),
                    1,
                ),
            }

    # ── Private Scoring ────────────────────────────────────────────────────

    def _compute_risk_score(self, files: list[str]) -> float:
        """Compute risk score from ChangeRiskScorer."""
        try:
            from core.change_risk_scorer import get_risk_scorer

            risk = get_risk_scorer().score_change(files_changed=files)
            return risk.risk_score * 100
        except ImportError:
            # Fallback: estimate from file count
            if len(files) > 20:
                return 60.0
            if len(files) > 10:
                return 40.0
            if len(files) > 5:
                return 20.0
            return 10.0

    def _score_migration_safety(self, files: list[str]) -> float:
        """Score migration safety based on patterns."""
        score = 60.0  # Start at 60 for any DB migration

        for file_path in files:
            f = Path(file_path)
            if f.suffix != ".py" or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore").lower()
                # Check for safety patterns
                if "if not exists" in content:
                    score += 5.0
                if "alter table" in content and "add column" in content:
                    # Adding columns is safer
                    if "if not exists" in content:
                        score += 5.0
                if "drop" in content:
                    score -= 15.0  # Drops are risky
                if "backup" in content:
                    score += 10.0
            except OSError:
                pass

        return max(0.0, min(100.0, score))

    def _score_dependency_readiness(self) -> float:
        """Score dependency readiness."""
        score = 70.0
        req_files = ["requirements.txt", "requirements-dev.txt", "pyproject.toml"]

        # Check if requirements files compile
        for req_file in req_files:
            f = Path(req_file)
            if f.is_file():
                score += 5.0

        return min(100.0, score)

    def _score_infrastructure_readiness(self, files: list[str]) -> float:
        """Score infrastructure readiness."""
        score = 80.0

        for file_path in files:
            if "docker" in file_path.lower() or "Dockerfile" in file_path:
                score -= 5.0
            if "config" in file_path.lower() and file_path.endswith(".json"):
                score -= 3.0
            if ".env" in file_path or "secret" in file_path.lower():
                score -= 5.0
                score = max(0.0, score)

        return score

    def _predict_performance_impact(self, files: list[str]) -> str:
        """Predict performance impact of the release."""
        impact_level = "NONE"

        for file_path in files:
            f = Path(file_path)
            if f.suffix != ".py" or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                if any(
                    kw in content
                    for kw in ["async", "asyncio", "concurrent", "threading"]
                ):
                    impact_level = "LOW"
                if any(
                    kw in content
                    for kw in ["pandas", "numpy", "large loop", "for range"]
                ):
                    if impact_level != "HIGH":
                        impact_level = "MODERATE"
                if any(
                    kw in content
                    for kw in ["yfinance", "broker", "websocket"]
                ):
                    impact_level = "HIGH"
            except OSError:
                pass

        return impact_level

    def _predict_regression_risk(
        self, files: list[str], has_db: bool, risk_score: float
    ) -> str:
        """Predict regression risk."""
        if risk_score > 70 or has_db:
            return "HIGH"
        if risk_score > 40 or len(files) > 15:
            return "MODERATE"
        if risk_score > 20 or len(files) > 5:
            return "LOW"
        return "VERY_LOW"

    def _compute_readiness_score(self, assessment: ReleaseAssessment) -> float:
        """Compute overall release readiness score."""
        # Weights
        weights = {
            "risk": 0.30,
            "migration": 0.15,
            "dependency": 0.10,
            "infrastructure": 0.10,
            "file_count": 0.15,
            "regression": 0.20,
        }

        # Invert risk score (higher risk = lower readiness)
        risk_readiness = 100.0 - assessment.risk_score

        # File count penalty
        n = assessment.n_files_changed
        if n > 30:
            file_readiness = 30.0
        elif n > 20:
            file_readiness = 50.0
        elif n > 10:
            file_readiness = 70.0
        elif n > 5:
            file_readiness = 85.0
        else:
            file_readiness = 95.0

        # Regression risk mapping
        regression_map = {
            "VERY_LOW": 95.0,
            "LOW": 80.0,
            "MODERATE": 60.0,
            "HIGH": 35.0,
        }

        score = (
            risk_readiness * weights["risk"]
            + assessment.migration_safety_score * weights["migration"]
            + assessment.dependency_readiness_score * weights["dependency"]
            + assessment.infrastructure_readiness_score * weights["infrastructure"]
            + file_readiness * weights["file_count"]
            + regression_map.get(
                assessment.predicted_regression_risk, 50.0
            ) * weights["regression"]
        )

        return round(min(100.0, max(0.0, score)), 1)

    def _determine_approval(
        self, assessment: ReleaseAssessment
    ) -> str:
        """Determine approval recommendation."""
        if assessment.release_readiness_score >= 80:
            return "APPROVED"
        if assessment.release_readiness_score >= 50:
            return "CONDITIONAL"
        return "BLOCKED"

    def _determine_deployment_strategy(
        self, assessment: ReleaseAssessment
    ) -> tuple[int, bool, bool]:
        """Determine recommended deployment strategy."""
        readiness = assessment.release_readiness_score
        risk = assessment.risk_score
        has_db = assessment.has_db_migration
        regression = assessment.predicted_regression_risk

        if readiness >= 85 and risk < 20:
            return (100, False, False)  # Direct deployment
        if readiness >= 70 and risk < 40:
            return (50, False, False)  # 50% canary
        if regression == "HIGH" or has_db:
            return (10, True, True)  # 10% canary + blue-green + feature flag
        if risk >= 50:
            return (25, True, True)  # 25% canary + blue-green
        return (50, False, False)

    def _generate_rollback_plan(
        self, assessment: ReleaseAssessment
    ) -> tuple[bool, list[str], int]:
        """Generate rollback plan based on release characteristics."""
        steps: list[str] = []
        eta = 5

        if assessment.has_db_migration:
            steps.append(ROLLBACK_TEMPLATES["db_migration"])
            eta += 10

        if assessment.has_config_changes:
            steps.append(ROLLBACK_TEMPLATES["config"])
            eta += 5

        if assessment.has_dependency_changes:
            steps.append(ROLLBACK_TEMPLATES["dependency"])
            eta += 5

        steps.append("git revert --no-commit HEAD~1")
        steps.append("git commit -m 'Rollback to previous version'")
        eta += 5

        return (True, steps, eta)

    def _generate_warnings(self, assessment: ReleaseAssessment) -> list[str]:
        """Generate warnings for the release."""
        warnings: list[str] = []

        if assessment.has_db_migration:
            warnings.append(
                "Database migration detected — ensure rollback migration is ready"
            )
        if assessment.has_config_changes:
            warnings.append(
                "Configuration changes — verify in target environment"
            )
        if assessment.n_files_changed > 20:
            warnings.append(
                f"Large release ({assessment.n_files_changed} files) — "
                "consider splitting"
            )
        if assessment.risk_score > 60:
            warnings.append("High risk score — conduct thorough testing")
        if assessment.predicted_performance_impact in ("MODERATE", "HIGH"):
            warnings.append(
                f"Performance impact expected ({assessment.predicted_performance_impact}) "
                "- benchmark before and after"
            )

        return warnings[:5]

    def _generate_recommendations(
        self, assessment: ReleaseAssessment
    ) -> list[str]:
        """Generate actionable recommendations."""
        recs: list[str] = []

        if assessment.approval_recommendation == "BLOCKED":
            recs.append("REQUIRED: Address all warnings before release")
        elif assessment.approval_recommendation == "CONDITIONAL":
            recs.append("Address the following conditions before release")

        if assessment.canary_recommendation_pct < 100:
            recs.append(
                f"Deploy with {assessment.canary_recommendation_pct}% canary "
                "and monitor for 24 hours"
            )
        if assessment.blue_green_recommended:
            recs.append("Use blue-green deployment to minimize downtime")
        if assessment.feature_flag_recommended:
            recs.append(
                "Use feature flags to isolate risky changes"
            )
        if assessment.predicted_regression_risk in ("HIGH", "MODERATE"):
            recs.append(
                "Run full regression test suite before production deployment"
            )
        if not assessment.has_rollback_plan:
            recs.append("Create a rollback plan before deployment")

        return recs[:8]

    # ── Persistence ────────────────────────────────────────────────────────

    def _load_history(self) -> None:
        """Load release history from JSON file."""
        try:
            path = Path(RELEASE_HISTORY_FILE)
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                self._release_history = [
                    ReleaseRecord(**r) for r in data.get("releases", [])
                ]
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.debug("[RI] Load history failed: %s", exc)

    def _save_history(self) -> None:
        """Save release history to JSON file."""
        try:
            path = Path(RELEASE_HISTORY_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "releases": [r.to_dict() for r in self._release_history],
            }, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            _log.debug("[RI] Save history failed: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────

_engine: ReleaseIntelligenceEngine | None = None
_engine_lock = threading.RLock()


def get_release_intelligence() -> ReleaseIntelligenceEngine:
    """Get the singleton ReleaseIntelligenceEngine instance."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = ReleaseIntelligenceEngine()
        return _engine


def reset_release_intelligence() -> None:
    """Force-reset singleton (for testing)."""
    global _engine
    with _engine_lock:
        _engine = None


def _cli() -> None:
    """Command-line interface.

    Usage:
        python -m core.release_intelligence --version v2.57.0 --files core/foo.py
        python -m core.release_intelligence --version v2.57.0 --db --config
        python -m core.release_intelligence --stats
        python -m core.release_intelligence --history
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Release Intelligence — Release Readiness Scoring",
    )
    parser.add_argument("--version", type=str, help="Release version")
    parser.add_argument("--files", nargs="+", default=[], help="Changed files")
    parser.add_argument("--db", action="store_true", help="Has DB migration")
    parser.add_argument("--config", action="store_true", help="Has config changes")
    parser.add_argument("--deps", action="store_true", help="Has dependency changes")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--history", action="store_true", help="Show history")
    parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()
    ri = get_release_intelligence()

    if args.stats:
        stats = ri.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("═" * 50)
            print("Release Intelligence — Statistics")
            print("═" * 50)
            for k, v in stats.items():
                print(f"  {k.replace('_', ' ').title():30s}: {v}")
        return

    if args.history:
        history = ri.get_history()
        if args.json:
            print(json.dumps(history, indent=2))
        else:
            print(f"Release History ({len(history)} records):")
            for h in history:
                print(
                    f"  {h['version']}: score={h['readiness_score']:.1f}, "
                    f"approved={h['approved']}, success={h['deployed_successfully']}"
                )
        return

    if args.version:
        assessment = ri.assess_release(
            version=args.version,
            files_changed=args.files,
            has_db_migration=args.db,
            has_config_changes=args.config,
            has_dependency_changes=args.deps,
        )
        if args.json:
            print(json.dumps(assessment.to_dict(), indent=2))
        else:
            print(assessment.summary_text())
        return

    parser.print_help()


if __name__ == "__main__":
    _cli()


__all__ = [
    "ReleaseAssessment",
    "ReleaseIntelligenceEngine",
    "ReleaseRecord",
    "get_release_intelligence",
    "reset_release_intelligence",
]
