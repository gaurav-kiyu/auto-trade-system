"""Change Risk Scorer — Continuous Risk Assessment (Pillar 9).

Every change receives a risk score based on:
- Complexity (lines changed, files touched)
- Criticality (core vs peripheral module)
- Security impact
- Performance impact
- Business impact
- Dependencies (number of downstream consumers)
- Historical defect density
- Test coverage

Classifies changes as: LOW, MEDIUM, HIGH, or CRITICAL risk.

Usage:
    from core.change_risk_scorer import ChangeRiskScorer

    scorer = ChangeRiskScorer()
    score = scorer.score_change(
        files_changed=["core/risk_service.py"],
        lines_added=50,
        lines_deleted=10,
    )
    print(score.risk_level, score.risk_score)
    print(score.recommendations)
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ── Constants ───────────────────────────────────────────────────────────────

CRITICAL_MODULES = {
    "risk_service", "execution_service", "broker_adapters", "safety_state",
    "order_manager", "constitution", "index_trader",
}

HIGH_RISK_MODULES = {
    "portfolio_service", "position_service", "signal", "strategy",
    "risk", "execution", "broker", "auth", "telegram",
}

SECURITY_SENSITIVE_PATTERNS = [
    r"password|secret|token|auth|credential|certificate|encrypt|decrypt",
    r"sql|inject|exec|eval|pickle|marshal|subprocess",
    r"chmod|chown|suid|sgid|setuid",
]

PERFORMANCE_SENSITIVE_PATTERNS = [
    r"for\s+\w+\s+in\s+(range|list|dict|set)\s*\(",  # loop over large collections
    r"\.(read|write|open)\s*\(",  # I/O operations
    r"import\s+(pandas|numpy|yfinance|lightgbm|sklearn)",  # heavy imports in hot path
    r"(recursive|recursion|\.depth)",  # recursion
]

HIGH_BUSINESS_IMPACT_KEYWORDS = [
    "halt", "kill", "pause", "resume", "stop", "shutdown",
    "capital", "portfolio", "position", "margin", "leverage",
]


# ── Data Models ─────────────────────────────────────────────────────────────


@dataclass
class RiskScore:
    """Complete risk score for a change."""

    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    risk_score: float = 0.0  # 0.0 to 1.0
    complexity_score: float = 0.0
    criticality_score: float = 0.0
    security_score: float = 0.0
    performance_score: float = 0.0
    dependency_score: float = 0.0
    coverage_score: float = 0.0
    defect_score: float = 0.0
    recommendations: list[str] = field(default_factory=list)
    risk_factors: list[dict[str, Any]] = field(default_factory=list)
    scored_files: list[dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "risk_score": round(self.risk_score, 3),
            "complexity_score": round(self.complexity_score, 3),
            "criticality_score": round(self.criticality_score, 3),
            "security_score": round(self.security_score, 3),
            "performance_score": round(self.performance_score, 3),
            "dependency_score": round(self.dependency_score, 3),
            "coverage_score": round(self.coverage_score, 3),
            "defect_score": round(self.defect_score, 3),
            "recommendations": self.recommendations,
            "risk_factors": self.risk_factors,
            "scored_files": self.scored_files,
        }

    def summary_text(self) -> str:
        return (
            f"Risk Assessment: {self.risk_level} (score={self.risk_score:.2f})\n"
            f"  Complexity: {self.complexity_score:.2f}  |  "
            f"Criticality: {self.criticality_score:.2f}\n"
            f"  Security:   {self.security_score:.2f}  |  "
            f"Performance: {self.performance_score:.2f}\n"
            f"  Dependency: {self.dependency_score:.2f}  |  "
            f"Coverage:    {self.coverage_score:.2f}  |  "
            f"Defect:      {self.defect_score:.2f}\n"
            + ("\n".join(f"  → {r}" for r in self.recommendations[:5]) if self.recommendations else "")
        )


# ── Change Risk Scorer ──────────────────────────────────────────────────────


class ChangeRiskScorer:
    """Scores the risk of a code change across multiple dimensions.

    Analyzes:
    - Complexity: lines changed, files touched, AST complexity
    - Criticality: which module is being changed (core vs peripheral)
    - Security: patterns that may introduce vulnerabilities
    - Performance: patterns that may cause regressions
    - Dependencies: number of downstream consumers affected
    - Coverage: test coverage of the changed module
    - Defect rate: historical defect density of the module
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._defect_history: dict[str, int] = {}  # module_path -> defect_count
        self._change_history: dict[str, int] = {}  # module_path -> change_count
        self._coverage_cache: dict[str, float] = {}  # module_path -> coverage_pct
        self._load_defect_history()

    # ── Public API ────────────────────────────────────────────────────────

    def score_change(
        self,
        files_changed: list[str],
        lines_added: int = 0,
        lines_deleted: int = 0,
        author: str = "",
        commit_message: str = "",
    ) -> RiskScore:
        """Score the risk of a set of file changes.

        Args:
            files_changed: List of file paths that were changed.
            lines_added: Total lines added.
            lines_deleted: Total lines deleted.
            author: Optional author identifier.
            commit_message: Optional commit message for extra context.

        Returns:
            RiskScore with all scores and recommendations.
        """
        result = RiskScore()

        # Score each file individually
        for file_path in files_changed:
            file_score = self._score_file(file_path, lines_added, lines_deleted)
            result.scored_files.append(file_score)

        # Aggregate scores
        n_files = len(files_changed)
        if n_files > 0:
            result.complexity_score = max(f.get("complexity", 0) for f in result.scored_files)
            result.criticality_score = max(f.get("criticality", 0) for f in result.scored_files)
            result.security_score = max(f.get("security", 0) for f in result.scored_files)
            result.performance_score = max(f.get("performance", 0) for f in result.scored_files)
            result.dependency_score = max(f.get("dependency", 0) for f in result.scored_files)
            result.coverage_score = max(f.get("coverage", 0) for f in result.scored_files)
            result.defect_score = max(f.get("defect", 0) for f in result.scored_files)

        # Global adjustments
        # If many files changed, increase complexity
        if n_files > 10:
            result.complexity_score = min(1.0, result.complexity_score + 0.15)
        elif n_files > 5:
            result.complexity_score = min(1.0, result.complexity_score + 0.05)

        # If commit message mentions risk keywords
        commit_lower = commit_message.lower()
        if any(kw in commit_lower for kw in ["fix", "security", "vulnerability", "urgent", "critical"]):
            result.security_score = min(1.0, result.security_score + 0.1)

        # Compute overall risk score (weighted average)
        weights = {
            "complexity": 0.15,
            "criticality": 0.25,
            "security": 0.20,
            "performance": 0.10,
            "dependency": 0.15,
            "coverage": 0.10,
            "defect": 0.05,
        }
        result.risk_score = (
            result.complexity_score * weights["complexity"] +
            result.criticality_score * weights["criticality"] +
            result.security_score * weights["security"] +
            result.performance_score * weights["performance"] +
            result.dependency_score * weights["dependency"] +
            result.coverage_score * weights["coverage"] +
            result.defect_score * weights["defect"]
        )

        # Determine risk level
        result.risk_level = self._score_to_level(result.risk_score)

        # Generate recommendations
        result.recommendations = self._generate_recommendations(result, files_changed)

        # Record risk factors
        result.risk_factors = self._collect_risk_factors(result, files_changed)

        # Update change history
        for file_path in files_changed:
            self._record_change(file_path)

        return result

    def score_single_file(self, file_path: str) -> RiskScore:
        """Convenience: score a single file as if it's the only change."""
        return self.score_change(files_changed=[file_path])

    def get_module_risk_profile(self, file_path: str) -> dict[str, Any]:
        """Get the historical risk profile of a module."""
        path_key = file_path.replace("\\", "/")
        return {
            "path": file_path,
            "defect_count": self._defect_history.get(path_key, 0),
            "change_count": self._change_history.get(path_key, 0),
            "defect_rate": (
                self._defect_history.get(path_key, 0) / max(self._change_history.get(path_key, 1), 1)
            ),
        }

    def report_defect(self, file_path: str) -> None:
        """Record a defect for a module (reported after incident)."""
        path_key = file_path.replace("\\", "/")
        with self._lock:
            self._defect_history[path_key] = self._defect_history.get(path_key, 0) + 1
            self._save_defect_history()

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate risk scoring stats."""
        with self._lock:
            return {
                "modules_tracked": len(self._defect_history),
                "total_defects": sum(self._defect_history.values()),
                "total_changes": sum(self._change_history.values()),
                "defect_rate": (
                    sum(self._defect_history.values()) / max(sum(self._change_history.values()), 1)
                ),
            }

    # ── Private Scoring ───────────────────────────────────────────────────

    def _score_file(
        self, file_path: str, lines_added: int, lines_deleted: int
    ) -> dict[str, Any]:
        """Score a single file across all risk dimensions."""
        path_key = file_path.replace("\\", "/")
        Path(file_path)

        return {
            "file": file_path,
            "complexity": self._score_complexity(file_path, lines_added, lines_deleted),
            "criticality": self._score_criticality(path_key),
            "security": self._score_security(file_path),
            "performance": self._score_performance(file_path),
            "dependency": self._score_dependency(path_key),
            "coverage": self._score_coverage(path_key),
            "defect": self._score_defect_rate(path_key),
        }

    def _score_complexity(self, file_path: str, added: int, deleted: int) -> float:
        """Score complexity based on lines changed and file size."""
        score = 0.0

        # Lines changed
        total_changed = added + deleted
        if total_changed > 500:
            score += 0.5
        elif total_changed > 200:
            score += 0.3
        elif total_changed > 50:
            score += 0.15

        # File size
        f = Path(file_path)
        if f.is_file():
            try:
                lines = len(f.read_text(encoding="utf-8", errors="ignore").splitlines())
                if lines > 2000:
                    score += 0.4
                elif lines > 1000:
                    score += 0.2
                elif lines > 500:
                    score += 0.1
            except OSError:
                pass

        return min(1.0, score)

    def _score_criticality(self, path_key: str) -> float:
        """Score criticality based on module importance."""
        path_lower = path_key.lower()

        # Check critical modules
        for mod in CRITICAL_MODULES:
            if mod in path_lower:
                return 0.9

        # Check high-risk modules
        for mod in HIGH_RISK_MODULES:
            if mod in path_lower:
                return 0.7

        # Check if core module
        if path_lower.startswith("core/"):
            return 0.4

        # Check if index_app
        if path_lower.startswith("index_app/"):
            return 0.3

        # Test files are lower risk
        if path_lower.startswith("tests/"):
            return 0.1

        return 0.2

    def _score_security(self, file_path: str) -> float:
        """Score security risk based on code patterns."""
        f = Path(file_path)
        if not f.is_file():
            return 0.0

        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            score = 0.0

            for pattern in SECURITY_SENSITIVE_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    score += 0.2

            return min(1.0, score)
        except OSError:
            return 0.0

    def _score_performance(self, file_path: str) -> float:
        """Score performance impact based on code patterns."""
        f = Path(file_path)
        if not f.is_file():
            return 0.0

        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            score = 0.0

            for pattern in PERFORMANCE_SENSITIVE_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    score += 0.2

            return min(1.0, score)
        except OSError:
            return 0.0

    def _score_dependency(self, path_key: str) -> float:
        """Score dependency impact based on downstream consumers."""
        try:
            # Try to use ImpactAnalysisEngine's reverse graph if available
            from core.impact_analysis_engine import get_impact_engine
            engine = get_impact_engine()
            dependents = engine.get_dependents(path_key)
            n = len(dependents)
            if n > 30:
                return 0.9
            if n > 15:
                return 0.7
            if n > 5:
                return 0.4
            if n > 0:
                return 0.2
        except ImportError:
            pass
        return 0.1

    def _score_coverage(self, path_key: str) -> float:
        """Score based on test coverage of the module."""
        base_name = Path(path_key).stem
        test_file = f"tests/test_{base_name}.py"

        if Path(test_file).is_file():
            # Check if test file is substantial
            try:
                test_lines = len(Path(test_file).read_text(encoding="utf-8").splitlines())
                if test_lines > 200:
                    return 0.1  # Well covered = low risk
                if test_lines > 50:
                    return 0.3
                return 0.5  # Minimal coverage = medium risk
            except OSError:
                pass
        return 0.7  # No tests = high risk

    def _score_defect_rate(self, path_key: str) -> float:
        """Score based on historical defect rate."""
        with self._lock:
            defects = self._defect_history.get(path_key, 0)
            changes = self._change_history.get(path_key, 1)
            rate = defects / max(changes, 1)

            if rate > 0.5:
                return 0.8
            if rate > 0.3:
                return 0.5
            if rate > 0.1:
                return 0.3
            return 0.1

    def _record_change(self, file_path: str) -> None:
        """Record a change for historical tracking."""
        path_key = file_path.replace("\\", "/")
        with self._lock:
            self._change_history[path_key] = self._change_history.get(path_key, 0) + 1

    # ── Utilities ─────────────────────────────────────────────────────────

    def _score_to_level(self, score: float) -> str:
        """Convert a numeric score to a risk level."""
        if score >= 0.75:
            return "CRITICAL"
        if score >= 0.5:
            return "HIGH"
        if score >= 0.25:
            return "MEDIUM"
        return "LOW"

    def _generate_recommendations(
        self, result: RiskScore, files_changed: list[str]
    ) -> list[str]:
        """Generate actionable recommendations based on risk factors."""
        recs: list[str] = []

        if result.risk_level == "CRITICAL":
            recs.append("REQUIRED: Two-person code review required before merge")
            recs.append("REQUIRED: Full regression test suite must pass")
        elif result.risk_level == "HIGH":
            recs.append("REQUIRED: Peer code review required")
            recs.append("Run relevant integration tests before merge")

        if result.security_score > 0.5:
            recs.append("Security-sensitive patterns detected — conduct security review")
        if result.performance_score > 0.5:
            recs.append("Performance-sensitive patterns detected — profile before deploy")
        if result.criticality_score > 0.7:
            recs.append("Change affects critical module — notify operators before deploy")
        if result.coverage_score > 0.5:
            recs.append("Module has low test coverage — add tests for changed logic")
        if result.complexity_score > 0.6:
            recs.append("Large change set — consider splitting into smaller commits")

        # File-specific recommendations
        for f in result.scored_files:
            if f.get("coverage", 0) > 0.5:
                recs.append(f"Add tests for {f['file']}")
            break  # Only one file recommendation

        return recs[:8]

    def _collect_risk_factors(
        self, result: RiskScore, files_changed: list[str]
    ) -> list[dict[str, Any]]:
        """Collect all risk factors that contributed to the score."""
        factors: list[dict[str, Any]] = []

        for f in result.scored_files:
            contributing = []
            for dim in ["complexity", "criticality", "security", "performance",
                         "dependency", "coverage", "defect"]:
                if f.get(dim, 0) > 0.3:
                    contributing.append(dim)
            if contributing:
                factors.append({
                    "file": f["file"],
                    "contributing_factors": contributing,
                    "max_dimension": max(
                        ((d, f.get(d, 0)) for d in ["complexity", "criticality", "security"]),
                        key=lambda x: x[1],
                    )[0],
                })

        return factors

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_defect_history(self) -> None:
        """Load defect history from JSON file."""
        path = Path("json/defect_history.json")
        try:
            if path.is_file():
                data = path.read_text(encoding="utf-8")
                parsed = json.loads(data)
                self._defect_history = parsed.get("defects", {})
                self._change_history = parsed.get("changes", {})
        except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
            _log.debug("[RISK] Defect history load failed: %s", exc)

    def _save_defect_history(self) -> None:
        """Save defect history to JSON file."""
        path = Path("json/defect_history.json")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "defects": self._defect_history,
                "changes": self._change_history,
            }, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            _log.debug("[RISK] Defect history save failed: %s", exc)


# ── Singleton ───────────────────────────────────────────────────────────────


_scorer: ChangeRiskScorer | None = None
_scorer_lock = threading.RLock()


def get_risk_scorer() -> ChangeRiskScorer:
    """Get the singleton ChangeRiskScorer instance."""
    global _scorer
    with _scorer_lock:
        if _scorer is None:
            _scorer = ChangeRiskScorer()
        return _scorer


def reset_risk_scorer() -> None:
    """Force-reset singleton (for testing)."""
    global _scorer
    with _scorer_lock:
        _scorer = None


def score_change_risk(
    files_changed: list[str],
    lines_added: int = 0,
    lines_deleted: int = 0,
    commit_message: str = "",
) -> RiskScore:
    """Convenience function: score a change."""
    return get_risk_scorer().score_change(
        files_changed=files_changed,
        lines_added=lines_added,
        lines_deleted=lines_deleted,
        commit_message=commit_message,
    )


__all__ = [
    "ChangeRiskScorer",
    "RiskScore",
    "get_risk_scorer",
    "reset_risk_scorer",
    "score_change_risk",
]
