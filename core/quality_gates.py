"""Quality Gates System — PR Quality Scoring Across 15 Dimensions (Pillar x).

Every PR receives a scorecard across:
- Architecture compliance
- Maintainability
- Performance
- Security
- Accessibility
- Scalability
- Reliability
- Observability
- Documentation coverage
- Testability / Test coverage
- Technical debt impact
- AI confidence (governance compliance)
- Business risk
- Deployment readiness
- Overall Engineering Score

Integrates with:
- ChangeRiskScorer for risk dimensions
- Constitution_AI_Gate for AI governance compliance
- ImpactAnalysisEngine for dependency/criticality scoring
- AccessibilityGate for accessibility scoring

Usage:
    from core.quality_gates import get_quality_gates

    gates = get_quality_gates()
    result = gates.evaluate_pr(
        files_changed=["core/risk_service.py"],
        lines_added=50,
        lines_deleted=10,
        commit_message="fix: critical risk edge case",
        author="dev-user",
    )
    print(result.engineering_score)  # 0.0 - 10.0
    print(result.overall_verdict)    # PASS, CONDITIONAL, BLOCKED
    print(result.recommendations)
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

# ── Constants ────────────────────────────────────────────────────────────────

GATE_DIMENSIONS = (
    "architecture", "maintainability", "performance", "security",
    "accessibility", "scalability", "reliability", "observability",
    "documentation", "testability", "technical_debt", "ai_confidence",
    "business_risk", "deployment_readiness", "engineering_score",
)

VERDICT_PASS = "PASS"
VERDICT_CONDITIONAL = "CONDITIONAL"
VERDICT_BLOCKED = "BLOCKED"

MIN_SCORE_PASS = 7.0
MIN_SCORE_CONDITIONAL = 5.0

# Patterns for detecting documentation changes
DOC_PATTERNS = [
    r"docs/.*\.md",
    r"README\.md",
    r"CHANGELOG\.md",
    r"CLAUDE\.md",
    r".*\.rst",
    r".*\.txt",
]

# Patterns for detecting test changes
TEST_PATTERNS = [
    r"tests/.*\.py",
    r"test_.*\.py",
    r".*_test\.py",
    r"conftest\.py",
]


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class GateDimensionScore:
    """Score for a single gate dimension."""

    name: str
    score: float = 0.0  # 0.0 to 10.0
    weight: float = 1.0
    findings: list[str] = field(default_factory=list)
    details: str = ""

    def weighted_score(self) -> float:
        return self.score * self.weight

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 2),
            "weight": self.weight,
            "weighted_score": round(self.weighted_score(), 2),
            "findings": self.findings[:5],
            "details": self.details[:200],
        }


@dataclass
class QGResult:
    """Complete quality gate evaluation result for a PR."""

    overall_verdict: str = VERDICT_PASS  # PASS, CONDITIONAL, BLOCKED
    engineering_score: float = 0.0  # 0.0 - 10.0 aggregate
    gate_scores: list[GateDimensionScore] = field(default_factory=list)
    blocking_findings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    n_files_changed: int = 0
    n_lines_added: int = 0
    n_lines_deleted: int = 0
    risk_level: str = "LOW"
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        """Convert dict gate_scores to GateDimensionScore objects after loading."""
        converted: list[GateDimensionScore] = []
        for g in self.gate_scores:
            if isinstance(g, dict):
                converted.append(GateDimensionScore(**g))
            else:
                converted.append(g)
        self.gate_scores = converted

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_verdict": self.overall_verdict,
            "engineering_score": round(self.engineering_score, 2),
            "gate_scores": [g.to_dict() for g in self.gate_scores],
            "blocking_findings": self.blocking_findings[:10],
            "warnings": self.warnings[:10],
            "recommendations": self.recommendations[:10],
            "n_files_changed": self.n_files_changed,
            "n_lines_added": self.n_lines_added,
            "n_lines_deleted": self.n_lines_deleted,
            "risk_level": self.risk_level,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  QUALITY GATES EVALUATION",
            "═" * 60,
            f"  Overall Verdict: {self.overall_verdict}",
            f"  Engineering Score: {self.engineering_score:.1f}/10.0",
            f"  Files: {self.n_files_changed}  |  "
            f"+{self.n_lines_added}/-{self.n_lines_deleted} lines",
            f"  Risk Level: {self.risk_level}",
            "",
            "  Gate Scores:",
        ]
        for g in self.gate_scores:
            bar = "■" * int(g.score) + "□" * (10 - int(g.score))
            lines.append(f"    {g.name:20s}  {bar}  {g.score:.1f}")
        if self.blocking_findings:
            lines.append("\n  BLOCKING:")
            for bf in self.blocking_findings[:5]:
                lines.append(f"    ✗ {bf}")
        if self.warnings:
            lines.append("\n  Warnings:")
            for w in self.warnings[:5]:
                lines.append(f"    ⚠ {w}")
        if self.recommendations:
            lines.append("\n  Recommendations:")
            for r in self.recommendations[:5]:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Quality Gates Engine ─────────────────────────────────────────────────────


class QualityGatesEngine:
    """Evaluates PRs across 15 quality gate dimensions.

    Thread-safe singleton. Integrates with ChangeRiskScorer, ImpactAnalysisEngine,
    ConstitutionAIGate, and AccessibilityGate for comprehensive scoring.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._evaluation_history: list[QGResult] = []
        self._max_history = 500
        self._history_file = Path("json/quality_gates_history.json")
        self._load_history()

    # ── Public API ─────────────────────────────────────────────────────────

    def evaluate_pr(
        self,
        files_changed: list[str],
        lines_added: int = 0,
        lines_deleted: int = 0,
        commit_message: str = "",
        author: str = "",
    ) -> QGResult:
        """Evaluate a PR across all quality gate dimensions.

        Args:
            files_changed: List of file paths that were changed.
            lines_added: Total lines added.
            lines_deleted: Total lines deleted.
            commit_message: Commit message / PR description.
            author: Author identifier.

        Returns:
            QGResult with scores, findings, and verdict.
        """
        result = QGResult(
            n_files_changed=len(files_changed),
            n_lines_added=lines_added,
            n_lines_deleted=lines_deleted,
        )

        # Score each dimension
        self._score_architecture(result, files_changed)
        self._score_maintainability(result, files_changed, lines_added, lines_deleted)
        self._score_performance(result, files_changed)
        self._score_security(result, files_changed)
        self._score_accessibility(result, files_changed)
        self._score_scalability(result, files_changed)
        self._score_reliability(result, files_changed)
        self._score_observability(result, files_changed)
        self._score_documentation(result, files_changed, commit_message)
        self._score_testability(result, files_changed)
        self._score_technical_debt(result, files_changed, lines_added, lines_deleted)
        self._score_ai_confidence(result, files_changed, commit_message)
        self._score_business_risk(result, files_changed, commit_message)
        self._score_deployment_readiness(result, files_changed)

        # Compute aggregate engineering score
        total_weight = sum(g.weight for g in result.gate_scores) or 1.0
        weighted_sum = sum(g.weighted_score() for g in result.gate_scores)
        result.engineering_score = weighted_sum / total_weight

        # Determine verdict
        result.overall_verdict = self._determine_verdict(result)

        # Generate recommendations
        result.recommendations = self._generate_recommendations(result)

        # Determine risk level
        try:
            from core.change_risk_scorer import get_risk_scorer
            risk = get_risk_scorer().score_change(
                files_changed=files_changed,
                lines_added=lines_added,
                lines_deleted=lines_deleted,
                commit_message=commit_message,
            )
            result.risk_level = risk.risk_level
        except ImportError:
            pass

        # Store in history
        with self._lock:
            self._evaluation_history.append(result)
            if len(self._evaluation_history) > self._max_history:
                self._evaluation_history = self._evaluation_history[-self._max_history:]
            self._save_history()

        return result

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent quality gate evaluations."""
        with self._lock:
            return [r.to_dict() for r in self._evaluation_history[-limit:]]

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate quality gate statistics."""
        with self._lock:
            total = len(self._evaluation_history)
            passed = sum(1 for r in self._evaluation_history if r.overall_verdict == VERDICT_PASS)
            blocked = sum(1 for r in self._evaluation_history if r.overall_verdict == VERDICT_BLOCKED)
            avg_score = sum(r.engineering_score for r in self._evaluation_history) / max(total, 1)
            return {
                "total_evaluations": total,
                "passed": passed,
                "conditional": total - passed - blocked,
                "blocked": blocked,
                "pass_rate_pct": round((passed / max(total, 1)) * 100, 1),
                "avg_engineering_score": round(avg_score, 2),
                "gates_active": len(GATE_DIMENSIONS),
            }

    # ── Dimension Scoring ──────────────────────────────────────────────────

    def _score_architecture(self, result: QGResult, files: list[str]) -> None:
        """Score architecture compliance."""
        score = 8.0
        findings: list[str] = []

        # Check for forbidden patterns
        forbidden_patterns = {
            r"from\s+kiteconnect": "Direct Kite SDK import — use broker_adapters.py",
            r"from\s+angelbroking": "Direct Angel SDK import — use broker_adapters.py",
            r"datetime\.now\(\)": "Use core.datetime_ist.now_ist() instead of datetime.now()",
        }

        for file_path in files:
            f = Path(file_path)
            if f.suffix != ".py" or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for pattern, msg in forbidden_patterns.items():
                    if re.search(pattern, content):
                        findings.append(f"{file_path}: {msg}")
                        score -= 1.5
            except OSError:
                pass

        # Check for layered architecture violations
        for file_path in files:
            if file_path.startswith("index_app/") and not file_path.startswith("index_app/gui/"):
                f = Path(file_path)
                if f.suffix == ".py" and f.is_file():
                    try:
                        content = f.read_text(encoding="utf-8", errors="ignore")
                        # Check for direct infrastructure imports
                        if "from infrastructure" in content or "import infrastructure" in content:
                            findings.append(
                                f"{file_path}: Direct infrastructure import from app layer"
                            )
                            score -= 2.0
                    except OSError:
                        pass

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="architecture",
            score=score,
            weight=1.2,
            findings=findings,
            details=f"Architecture violations: {len(findings)}",
        ))
        if findings:
            result.blocking_findings.extend(
                f"Architecture: {f}" for f in findings[:3]
            )

    def _score_maintainability(
        self, result: QGResult, files: list[str], added: int, deleted: int
    ) -> None:
        """Score maintainability based on change size and file complexity."""
        findings: list[str] = []
        score = 8.0

        # Large changes reduce maintainability
        if added + deleted > 500:
            score -= 2.0
            findings.append("Very large change set (>500 lines) — consider splitting")
        elif added + deleted > 200:
            score -= 1.0
        elif added + deleted > 50:
            score -= 0.3

        # Many files reduces maintainability
        if len(files) > 15:
            score -= 1.5
            findings.append("Many files changed (>15) — consider focused changes")
        elif len(files) > 8:
            score -= 0.5

        # Check for very large files
        for file_path in files:
            f = Path(file_path)
            if f.suffix == ".py" and f.is_file():
                try:
                    lines = len(f.read_text(encoding="utf-8", errors="ignore").splitlines())
                    if lines > 1500:
                        score -= 0.5
                        findings.append(f"{file_path}: Large file ({lines} lines)")
                except OSError:
                    pass

        # Check for TODO/FIXME/HACK in changed files
        for file_path in files:
            f = Path(file_path)
            if f.suffix == ".py" and f.is_file():
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    for marker in ["TODO", "FIXME", "HACK", "XXX"]:
                        count = content.count(marker)
                        if count > 0:
                            findings.append(f"{file_path}: {count}x {marker}")
                            score -= 0.2 * min(count, 5)
                except OSError:
                    pass

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="maintainability",
            score=score,
            weight=1.0,
            findings=findings,
            details=f"Files: {len(files)}, Lines: {added + deleted}",
        ))

    def _score_performance(self, result: QGResult, files: list[str]) -> None:
        """Score performance based on patterns in changed files."""
        findings: list[str] = []
        score = 8.0

        perf_patterns = [
            (r"for\s+\w+\s+in\s+(range|list|dict|set)\s*\(", "Large loop over collection"),
            (r"\.(read|write|open)\s*\(", "I/O operation in hot path"),
            (r"(recursive|recursion)", "Recursive call — check depth"),
            (r"import\s+(pandas|numpy)\s", "Heavy import — check if lazy loading possible"),
            (r"time\.sleep\s*\(", "Sleep in hot path — blocks thread"),
        ]

        for file_path in files:
            f = Path(file_path)
            if f.suffix != ".py" or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for pattern, msg in perf_patterns:
                    if re.search(pattern, content):
                        score -= 0.5
                        findings.append(f"{file_path}: {msg}")
            except OSError:
                pass

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="performance",
            score=score,
            weight=0.8,
            findings=findings,
            details=f"Performance patterns detected: {len(findings)}",
        ))

    def _score_security(self, result: QGResult, files: list[str]) -> None:
        """Score security based on sensitive patterns."""
        findings: list[str] = []
        try:
            from core.change_risk_scorer import get_risk_scorer
            # Aggregate security score from risk scorer
            max_sec = 0.0
            for file_path in files:
                f = Path(file_path)
                if f.is_file():
                    risk = get_risk_scorer().score_single_file(file_path)
                    if risk.security_score > max_sec:
                        max_sec = risk.security_score
                        if risk.security_score > 0.3:
                            findings.append(f"{file_path}: Security patterns detected")
            score = 10.0 - (max_sec * 10.0)
        except ImportError:
            score = 8.0

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="security",
            score=score,
            weight=1.5,  # Security has higher weight
            findings=findings,
            details="Security score from ChangeRiskScorer",
        ))
        if score < 5.0:
            result.blocking_findings.extend(
                f"Security: {f}" for f in findings[:3]
            )

    def _score_accessibility(self, result: QGResult, files: list[str]) -> None:
        """Score accessibility for UI-related changes."""
        findings: list[str] = []
        has_ui_changes = any("gui" in f.lower() or "ui" in f.lower() or "html" in f.lower() for f in files)

        if not has_ui_changes:
            score = 10.0  # No UI changes = no accessibility concern
        else:
            # Check for common accessibility patterns
            score = 7.0
            for file_path in files:
                f = Path(file_path)
                if not f.is_file():
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore").lower()
                    if f.suffix in (".html", ".htm", ".jinja", ".jinja2"):
                        # Check for alt text on images
                        if "alt=" not in content and "<img" in content:
                            score -= 1.0
                            findings.append(f"{file_path}: Images missing alt text")
                        # Check for form labels
                        if "<input" in content and "label" not in content:
                            score -= 0.5
                            findings.append(f"{file_path}: Form inputs may lack labels")
                        # Check for ARIA attributes
                        if "role=" not in content and ("button" in content or "nav" in content):
                            score -= 0.3
                            findings.append(f"{file_path}: Consider adding ARIA roles")
                except OSError:
                    pass

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="accessibility",
            score=score,
            weight=0.5,
            findings=findings,
            details=f"UI changes: {has_ui_changes}",
        ))

    def _score_scalability(self, result: QGResult, files: list[str]) -> None:
        """Score scalability based on patterns affecting concurrency."""
        findings: list[str] = []
        score = 8.0

        for file_path in files:
            f = Path(file_path)
            if f.suffix != ".py" or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                # Check for global state without locks
                if "global " in content and "Lock" not in content and "RLock" not in content:
                    score -= 0.5
                    findings.append(f"{file_path}: Global state without locks")
                # Check for blocking I/O in async context
                if "async def" in content:
                    blocking_calls = ["time.sleep", "requests.get", "requests.post"]
                    for bc in blocking_calls:
                        if bc in content:
                            score -= 0.3
                            findings.append(
                                f"{file_path}: Blocking call '{bc}' in async context"
                            )
            except OSError:
                pass

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="scalability",
            score=score,
            weight=0.6,
            findings=findings,
            details=f"Scalability findings: {len(findings)}",
        ))

    def _score_reliability(self, result: QGResult, files: list[str]) -> None:
        """Score reliability based on error handling patterns."""
        findings: list[str] = []
        score = 8.0

        for file_path in files:
            f = Path(file_path)
            if f.suffix != ".py" or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                # Check for bare except clauses
                if re.search(r"except\s*:", content):
                    score -= 0.5
                    findings.append(f"{file_path}: Bare 'except:' clause — specify exception type")
                # Check for silent failures
                if "except:\n        pass" in content or "except:\n    pass" in content:
                    score -= 0.5
                    findings.append(f"{file_path}: Silent exception passing")
                # Check for missing timeout on network calls
                if "requests." in content and "timeout" not in content.lower():
                    score -= 0.3
                    findings.append(f"{file_path}: Network call without timeout")
            except OSError:
                pass

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="reliability",
            score=score,
            weight=1.0,
            findings=findings,
            details=f"Reliability findings: {len(findings)}",
        ))

    def _score_observability(self, result: QGResult, files: list[str]) -> None:
        """Score observability based on logging patterns."""
        findings: list[str] = []
        score = 8.0

        for file_path in files:
            f = Path(file_path)
            if f.suffix != ".py" or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                # Check if file has logging
                has_logger = "logging.getLogger" in content or "logger =" in content
                # Check for print statements instead of logging
                if "print(" in content and not has_logger:
                    score -= 0.5
                    findings.append(f"{file_path}: Uses print() instead of logging")
            except OSError:
                pass

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="observability",
            score=score,
            weight=0.6,
            findings=findings,
            details=f"Observability findings: {len(findings)}",
        ))

    def _score_documentation(self, result: QGResult, files: list[str], commit_msg: str) -> None:
        """Score documentation coverage for the change."""
        findings: list[str] = []
        has_doc_changes = any(re.match(p, f) for f in files for p in DOC_PATTERNS)
        has_new_features = any(k in commit_msg.lower() for k in ["feat", "feature", "add", "new"])

        if has_new_features and not has_doc_changes:
            score = 5.0
            findings.append("New feature detected without documentation changes")
        elif has_doc_changes:
            score = 9.0
            findings.append("Documentation updated alongside code changes")
        else:
            score = 8.0  # No doc changes needed for routine fixes

        # Check for missing docstrings in new/changed Python files
        for file_path in files:
            f = Path(file_path)
            if f.suffix != ".py" or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                # Check for functions/classes without docstrings
                funcs_no_doc = re.findall(r"def\s+(\w+)\s*\(", content)
                docstrings = content.count('"""')
                if len(funcs_no_doc) > 3 and docstrings < 2:
                    score -= 0.5
                    findings.append(
                        f"{file_path}: Functions without docstrings"
                    )
            except OSError:
                pass

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="documentation",
            score=score,
            weight=0.7,
            findings=findings,
            details=f"Doc changes: {has_doc_changes}, New features: {has_new_features}",
        ))
        if has_new_features and not has_doc_changes:
            result.warnings.append("New feature without documentation update")

    def _score_testability(self, result: QGResult, files: list[str]) -> None:
        """Score test coverage for the change."""
        findings: list[str] = []
        has_test_changes = any(re.match(p, f) for f in files for p in TEST_PATTERNS)
        has_source_changes = any(
            f.startswith("core/") or f.startswith("index_app/") or f.startswith("infrastructure/")
            for f in files
        )

        if has_source_changes and not has_test_changes:
            score = 4.0
            findings.append("Source code changed without corresponding test changes")
            result.warnings.append("Source changed without tests — add test coverage")
        elif has_source_changes and has_test_changes:
            score = 9.0
            findings.append("Tests updated alongside source changes")
        elif not has_source_changes:
            score = 8.0  # Only tests/docs changed
        else:
            score = 6.0

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="testability",
            score=score,
            weight=1.0,
            findings=findings,
            details=f"Test changes: {has_test_changes}, Source changes: {has_source_changes}",
        ))
        if has_source_changes and not has_test_changes:
            result.warnings.append("Consider adding tests for changed source code")

    def _score_technical_debt(self, result: QGResult, files: list[str], added: int, deleted: int) -> None:
        """Score technical debt impact of the change."""
        findings: list[str] = []
        score = 8.0

        # Ratio of deletion to addition (cleaning up debt vs adding)
        if added > 0 and deleted > 0:
            cleanup_ratio = deleted / max(added, 1)
            if cleanup_ratio > 1.5:
                score += 1.0  # Cleaning up more than adding
                findings.append("Net reduction in code size — debt decreasing")
        elif deleted > 0 and added == 0:
            score += 1.5  # Pure cleanup
            findings.append("Pure deletion — debt decreasing significantly")

        # New files increase surface area
        for file_path in files:
            f = Path(file_path)
            if not f.exists():
                score -= 0.3
                findings.append(f"{file_path}: New file — increases surface area")

        # Check for patterns that increase debt
        debt_patterns = [
            (r"#\s*(TODO|FIXME|HACK|XXX|WORKAROUND)", "Technical debt markers found"),
            (r"type:\s*ignore", "Type ignore comments — weakens type safety"),
            (r"noqa", "Lint suppression — consider fixing instead"),
        ]

        for file_path in files:
            f = Path(file_path)
            if f.suffix != ".py" or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for pattern, msg in debt_patterns:
                    if re.search(pattern, content):
                        score -= 0.3
                        findings.append(f"{file_path}: {msg}")
            except OSError:
                pass

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="technical_debt",
            score=score,
            weight=0.7,
            findings=findings,
            details=f"Net change: +{added}/-{deleted} lines",
        ))

    def _score_ai_confidence(self, result: QGResult, files: list[str], commit_msg: str) -> None:
        """Score AI governance compliance."""
        findings: list[str] = []
        score = 8.0

        try:
            from core.constitution_ai_gate import AIGovernanceGate

            gate = AIGovernanceGate()
            validation = gate.validate(
                constitution_acknowledged=True,
                claude_read=True,
                architecture_reviewed=True,
                changed_files=files,
            )
            if not validation.passed:
                score -= min(len(validation.failures) * 2.0, 5.0)
                findings.extend(validation.failures[:3])
        except ImportError:
            pass

        # Check commit message for governance keywords
        gov_keywords = ["risk", "security", "compliance", "governance", "audit"]
        if any(kw in commit_msg.lower() for kw in gov_keywords):
            score += 0.5

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="ai_confidence",
            score=score,
            weight=0.5,
            findings=findings,
            details="AI governance compliance check",
        ))

    def _score_business_risk(self, result: QGResult, files: list[str], commit_msg: str) -> None:
        """Score business risk of the change."""
        findings: list[str] = []
        try:
            from core.change_risk_scorer import get_risk_scorer
            risk = get_risk_scorer().score_change(
                files_changed=files,
                commit_message=commit_msg,
            )
            # Convert risk score (0-1) to business risk (10-0)
            score = 10.0 - (risk.risk_score * 10.0)
            if risk.risk_level in ("HIGH", "CRITICAL"):
                findings.append(
                    f"Change risk is {risk.risk_level}: "
                    + "; ".join(risk.recommendations[:2])
                )
        except Exception:
            score = 7.0

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="business_risk",
            score=score,
            weight=1.0,
            findings=findings,
            details="Business risk assessment",
        ))
        if score < 5.0:
            result.blocking_findings.extend(findings[:3])

    def _score_deployment_readiness(self, result: QGResult, files: list[str]) -> None:
        """Score deployment readiness."""
        findings: list[str] = []
        score = 8.0

        # Check for config changes
        has_config_changes = any(
            "config" in f.lower() or ".json" in f or ".yaml" in f or ".yml" in f
            for f in files
        )
        if has_config_changes:
            score -= 0.5
            findings.append("Configuration changed — verify in target environment")

        # Check for migration-related changes
        has_db_changes = any(
            "migration" in f.lower() or "schema" in f.lower() or ".db" in f.lower()
            for f in files
        )
        if has_db_changes:
            score -= 1.0
            findings.append("Database migration detected — verify rollback plan")
            result.warnings.append("DB migration — ensure rollback is tested")

        # Check for requirement changes
        has_req_changes = any(
            "requirements" in f.lower() or "pyproject" in f.lower()
            for f in files
        )
        if has_req_changes:
            score -= 0.3
            findings.append("Dependencies changed — verify compatibility")

        # Check for Dockerfile changes
        has_docker_changes = any(
            "docker" in f.lower() or "Dockerfile" in f
            for f in files
        )
        if has_docker_changes:
            score -= 0.5
            findings.append("Docker configuration changed — rebuild and test")

        score = max(0.0, min(10.0, score))
        result.gate_scores.append(GateDimensionScore(
            name="deployment_readiness",
            score=score,
            weight=0.8,
            findings=findings,
            details=f"Config: {has_config_changes}, DB: {has_db_changes}, Docker: {has_docker_changes}",
        ))

    # ── Utilities ──────────────────────────────────────────────────────────

    def _determine_verdict(self, result: QGResult) -> str:
        """Determine overall verdict based on scores and findings."""
        if result.blocking_findings:
            return VERDICT_BLOCKED
        if result.engineering_score < MIN_SCORE_PASS:
            return VERDICT_CONDITIONAL
        # Check critical gates
        for gate in result.gate_scores:
            if gate.name in ("security", "business_risk") and gate.score < 5.0:
                return VERDICT_BLOCKED
        return VERDICT_PASS

    def _generate_recommendations(self, result: QGResult) -> list[str]:
        """Generate actionable recommendations based on gate scores."""
        recs: list[str] = []

        if result.overall_verdict == VERDICT_BLOCKED:
            recs.append("REQUIRED: Address blocking findings before merge")
        elif result.overall_verdict == VERDICT_CONDITIONAL:
            recs.append("REQUIRED: Improve engineering score above 7.0")

        # Dimension-specific recommendations
        for gate in result.gate_scores:
            if gate.score < 5.0:
                recs.append(f"Critical: {gate.name} score is {gate.score:.1f}")
            elif gate.score < 7.0:
                recs.append(f"Improve: {gate.name} score ({gate.score:.1f})")

        if result.n_files_changed > 10:
            recs.append("Consider splitting into smaller, focused PRs")

        return recs[:8]

    # ── Persistence ────────────────────────────────────────────────────────

    def _load_history(self) -> None:
        """Load evaluation history from JSON file."""
        try:
            if self._history_file.is_file():
                data = json.loads(self._history_file.read_text(encoding="utf-8"))
                for item in data.get("evaluations", []):
                    try:
                        result = QGResult(**{
                            k: v for k, v in item.items()
                            if k in QGResult.__dataclass_fields__
                        })
                        self._evaluation_history.append(result)
                    except (TypeError, ValueError):
                        pass
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.debug("[QG] Load history failed: %s", exc)

    def _save_history(self) -> None:
        """Save evaluation history to JSON file."""
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._evaluation_history[-self._max_history:]]
            self._history_file.write_text(
                json.dumps({"evaluations": data}, indent=2),
                encoding="utf-8",
            )
        except (OSError, ValueError, TypeError) as exc:
            _log.debug("[QG] Save history failed: %s", exc)

    # ── CLI ────────────────────────────────────────────────────────────────

    def _cli_evaluate(self, files: list[str], commit_msg: str = "") -> QGResult:
        """Evaluate a PR from CLI arguments."""
        return self.evaluate_pr(
            files_changed=files,
            commit_message=commit_msg,
        )


# ── Singleton ────────────────────────────────────────────────────────────────

_engine: QualityGatesEngine | None = None
_engine_lock = threading.RLock()


def get_quality_gates() -> QualityGatesEngine:
    """Get the singleton QualityGatesEngine instance."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = QualityGatesEngine()
        return _engine


def reset_quality_gates() -> None:
    """Force-reset singleton (for testing)."""
    global _engine
    with _engine_lock:
        _engine = None


def evaluate_pr(
    files_changed: list[str],
    lines_added: int = 0,
    lines_deleted: int = 0,
    commit_message: str = "",
    author: str = "",
) -> QGResult:
    """Convenience function: evaluate a PR through quality gates."""
    return get_quality_gates().evaluate_pr(
        files_changed=files_changed,
        lines_added=lines_added,
        lines_deleted=lines_deleted,
        commit_message=commit_message,
        author=author,
    )


def _cli() -> None:
    """Command-line interface.

    Usage:
        python -m core.quality_gates --files core/foo.py tests/test_foo.py
        python -m core.quality_gates --files core/risk_service.py --msg "Fix risk edge case"
        python -m core.quality_gates --stats
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Quality Gates System — PR quality scoring",
    )
    parser.add_argument("--files", nargs="+", help="Files changed in the PR")
    parser.add_argument("--msg", default="", help="Commit message")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--stats", action="store_true", help="Show statistics")

    args = parser.parse_args()
    gates = get_quality_gates()

    if args.stats:
        stats = gates.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("═" * 50)
            print("Quality Gates — Statistics")
            print("═" * 50)
            for k, v in stats.items():
                print(f"  {k.replace('_', ' ').title():30s}: {v}")
        return

    if args.files:
        result = gates.evaluate_pr(
            files_changed=args.files,
            commit_message=args.msg,
        )
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(result.summary_text())
        return

    parser.print_help()


if __name__ == "__main__":
    _cli()


__all__ = [
    "GateDimensionScore",
    "QGResult",
    "QualityGatesEngine",
    "evaluate_pr",
    "get_quality_gates",
    "reset_quality_gates",
]
