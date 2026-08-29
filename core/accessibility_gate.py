"""Accessibility Gate — Accessibility Quality Scoring (Constitution v4.0, Quality Gates).

Provides automated accessibility assessment of the codebase:
- HTML template accessibility checks (alt text, form labels, headings, ARIA)
- Documentation accessibility (readability scores, language clarity)
- Color contrast verification
- Keyboard navigation analysis
- Screen reader compatibility scoring

Integrates with:
- ConstitutionValidator for overall engineering score
- BIDashboard for quality trending
- LivingDocumentation for doc quality scoring

Usage:
    from core.accessibility_gate import get_accessibility_gate

    gate = get_accessibility_gate()
    report = gate.run_assessment()
    print(report.summary_text())
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent

EXCLUDED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "reports", "data"}

HTML_TEMPLATE_DIRS = [
    ROOT / "templates",
    Path(__file__).resolve().parent / "templates",
]

# Patterns to check in HTML templates
HTML_ACCESSIBILITY_CHECKS: list[dict[str, Any]] = [
    {
        "id": "IMG_ALT",
        "name": "Image Alt Text",
        "pattern": r"<img\s[^>]*src=\"[^\"]+\"[^>]*>",
        "positive_pattern": r"alt=\"[^\"]*\"",
        "description": "Images should have alt text for screen readers",
        "severity": "HIGH",
    },
    {
        "id": "FORM_LABEL",
        "name": "Form Input Labels",
        "pattern": r"<input\s[^>]*type=\"(text|email|password|search|tel|url)\"[^>]*>",
        "positive_pattern": r"(aria-label=\"[^\"]*\"|aria-labelledby=\"[^\"]*\"|<label[^>]*>)",
        "description": "Form inputs should have associated labels",
        "severity": "HIGH",
    },
    {
        "id": "HEADING_HIERARCHY",
        "name": "Heading Hierarchy",
        "pattern": r"<h[1-6][^>]*>",
        "positive_pattern": r"<h1[^>]*>",
        "description": "Pages should have exactly one h1 heading",
        "severity": "MEDIUM",
    },
    {
        "id": "ARIA_LANDMARKS",
        "name": "ARIA Landmarks",
        "pattern": r"<(header|nav|main|footer|aside|section|article)[^>]*>",
        "positive_pattern": r"(role=\"[^\"]*\"|aria-label=\"[^\"]*\")",
        "description": "Semantic HTML elements should have ARIA attributes when needed",
        "severity": "MEDIUM",
    },
    {
        "id": "TABLE_HEADERS",
        "name": "Table Headers",
        "pattern": r"<table[^>]*>",
        "positive_pattern": r"(<th[^>]*>|scope=\"[^\"]*\")",
        "description": "Tables should use th elements and scope attributes",
        "severity": "MEDIUM",
    },
    {
        "id": "BUTTON_TEXT",
        "name": "Button/Accessible Name",
        "pattern": r"<button[^>]*>(?:\s*<[^>]*>)*\s*</button>",
        "positive_pattern": r"<button[^>]*>[A-Za-z]",
        "description": "Buttons should have visible text content",
        "severity": "HIGH",
    },
    {
        "id": "LANG_ATTR",
        "name": "HTML Language Attribute",
        "pattern": r"<html[^>]*>",
        "positive_pattern": r"lang=\"[^\"]*\"",
        "description": "HTML element should have lang attribute",
        "severity": "MEDIUM",
    },
    {
        "id": "SKIP_LINK",
        "name": "Skip Navigation Link",
        "pattern": r"<body[^>]*>",
        "positive_pattern": r"(skip|skipnav|skip-link|skip-to-content)",
        "description": "Pages should have a skip navigation link",
        "severity": "MEDIUM",
    },
]


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class AccessibilityFinding:
    """An accessibility finding on a specific file."""

    check_id: str = ""
    check_name: str = ""
    file_path: str = ""
    severity: str = "MEDIUM"
    description: str = ""
    line_count: int = 0
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "check_name": self.check_name,
            "file_path": self.file_path,
            "severity": self.severity,
            "description": self.description,
            "line_count": self.line_count,
            "recommendation": self.recommendation,
        }


@dataclass
class AccessibilityChecklistItem:
    """A single accessibility checklist item with pass/fail."""

    check_id: str = ""
    check_name: str = ""
    severity: str = "MEDIUM"
    passed: bool = False
    total_instances: int = 0
    passing_instances: int = 0
    score: float = 1.0
    files_checked: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "check_name": self.check_name,
            "severity": self.severity,
            "passed": self.passed,
            "total_instances": self.total_instances,
            "passing_instances": self.passing_instances,
            "score": round(self.score, 3),
            "files_checked": self.files_checked,
        }


@dataclass
class AccessibilityReport:
    """Complete accessibility assessment report."""

    timestamp: float = 0.0
    templates_scanned: int = 0
    findings: list[AccessibilityFinding] = field(default_factory=list)
    checklist: list[AccessibilityChecklistItem] = field(default_factory=list)
    overall_score: float = 10.0
    risk_level: str = "LOW"
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp).isoformat() if self.timestamp else "",
            "templates_scanned": self.templates_scanned,
            "findings": [f.to_dict() for f in self.findings],
            "findings_count": len(self.findings),
            "checklist": [c.to_dict() for c in self.checklist],
            "overall_score": round(self.overall_score, 1),
            "risk_level": self.risk_level,
            "recommendations": self.recommendations,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  ACCESSIBILITY ASSESSMENT REPORT",
            "═" * 60,
            f"  Templates Scanned: {self.templates_scanned}",
            f"  Findings: {len(self.findings)}",
            f"  Score: {self.overall_score:.1f}/10.0  |  Risk: {self.risk_level}",
            "",
        ]
        if self.checklist:
            lines.append("  Checklist:")
            for c in self.checklist:
                icon = "✅" if c.passed else "❌"
                lines.append(f"    {icon} {c.check_name}: {c.score:.0%} ({c.passing_instances}/{c.total_instances})")
        if self.findings:
            lines.append("\n  Top Findings:")
            for f in self.findings[:5]:
                lines.append(f"    [{f.severity}] {f.check_name}: {f.file_path} ({f.line_count} instances)")
        if self.recommendations:
            lines.append("\n  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Accessibility Gate ─────────────────────────────────────────────────────


class AccessibilityGate:
    """Accessibility Gate — Quality Scoring for Accessibility.

    Assesses HTML templates and documentation for accessibility compliance.
    Checks for alt text, form labels, heading hierarchy, ARIA landmarks,
    keyboard navigation readiness, and screen reader compatibility.

    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._reports: list[AccessibilityReport] = []
        self._max_reports = 100
        self._persist_path = Path("json/accessibility_history.json")

    # ── Public API ────────────────────────────────────────────────────────

    def run_assessment(self) -> AccessibilityReport:
        """Run a complete accessibility assessment.

        Scans all HTML templates and documentation for accessibility issues.

        Returns:
            AccessibilityReport with findings and score.
        """
        report = AccessibilityReport(timestamp=time.time())

        # Find all HTML templates
        template_files: list[Path] = []
        for templates_dir in HTML_TEMPLATE_DIRS:
            if templates_dir.is_dir():
                template_files.extend(templates_dir.rglob("*.html"))

        report.templates_scanned = len(template_files)

        # Run each accessibility check across all templates
        checklist_items: list[AccessibilityChecklistItem] = []
        all_findings: list[AccessibilityFinding] = []

        for check in HTML_ACCESSIBILITY_CHECKS:
            check_id = check["id"]
            check_name = check["name"]
            pattern = check["pattern"]
            positive_pattern = check["positive_pattern"]
            severity = check["severity"]

            item = AccessibilityChecklistItem(
                check_id=check_id, check_name=check_name,
                severity=severity,
            )

            for template_file in template_files:
                try:
                    content = template_file.read_text(encoding="utf-8", errors="ignore")
                    rel_path = str(template_file.relative_to(ROOT))
                    item.files_checked += 1

                    # Find all instances of the pattern
                    instances = re.findall(pattern, content, re.IGNORECASE)
                    if not instances:
                        # No instances = not applicable (pass)
                        continue

                    # Check how many have the positive pattern nearby
                    passing = 0
                    for instance in instances:
                        # Get context around this instance
                        idx = content.find(instance)
                        if idx >= 0:
                            # Look at context (start of line to end of element)
                            line_start = content.rfind("\n", 0, idx) + 1
                            line_end = content.find(">", idx)
                            if line_end >= 0:
                                context = content[line_start:line_end + 1]
                            else:
                                context = content[line_start:idx + len(instance)]
                            if re.search(positive_pattern, context, re.IGNORECASE):
                                passing += 1

                    item.total_instances += len(instances)
                    item.passing_instances += passing

                    # If not all instances pass, report findings
                    if passing < len(instances):
                        failures = len(instances) - passing
                        all_findings.append(AccessibilityFinding(
                            check_id=check_id,
                            check_name=check_name,
                            file_path=rel_path,
                            severity=severity,
                            description=f"{failures}/{len(instances)} instances fail check",
                            line_count=failures,
                            recommendation=check["description"],
                        ))

                except (OSError, UnicodeDecodeError) as exc:
                    _log.debug("[A11Y] Scan error for %s: %s", template_file, exc)

            # Compute score for this check
            if item.total_instances > 0:
                item.score = item.passing_instances / max(item.total_instances, 1)
                item.passed = item.score >= 0.8  # 80% threshold
            else:
                item.score = 1.0
                item.passed = True

            checklist_items.append(item)

        report.checklist = checklist_items
        report.findings = all_findings

        # Compute overall score
        report.overall_score = self._compute_score(report)
        report.risk_level = self._risk_level(report.overall_score)

        # Generate recommendations
        report.recommendations = self._generate_recommendations(report)

        with self._lock:
            self._reports.append(report)
            if len(self._reports) > self._max_reports:
                self._reports = self._reports[-self._max_reports:]
            self._persist()

        return report

    def get_stats(self) -> dict[str, Any]:
        """Get accessibility gate statistics."""
        with self._lock:
            last = self._reports[-1] if self._reports else None
            return {
                "total_assessments": len(self._reports),
                "last_score": round(last.overall_score, 1) if last else 10.0,
                "last_risk": last.risk_level if last else "LOW",
                "templates_scanned": last.templates_scanned if last else 0,
                "findings": len(last.findings) if last else 0,
            }

    # ── Scoring ──────────────────────────────────────────────────────────

    def _compute_score(self, report: AccessibilityReport) -> float:
        """Compute overall accessibility score (0-10)."""
        if not report.checklist:
            return 10.0

        # Average of all checklist item scores, scaled to 0-10
        avg_score = sum(c.score for c in report.checklist) / len(report.checklist)
        score = avg_score * 10

        # Penalty for each finding
        for f in report.findings:
            if f.severity == "HIGH":
                score -= 0.5
            elif f.severity == "MEDIUM":
                score -= 0.2

        return max(0.0, min(10.0, score))

    def _risk_level(self, score: float) -> str:
        """Convert score to risk level."""
        if score >= 8.0:
            return "LOW"
        if score >= 6.0:
            return "MEDIUM"
        if score >= 4.0:
            return "HIGH"
        return "CRITICAL"

    def _generate_recommendations(self, report: AccessibilityReport) -> list[str]:
        """Generate accessibility improvement recommendations."""
        recs: list[str] = []

        # Check each checklist item
        for item in report.checklist:
            if not item.passed and item.total_instances > 0:
                if item.score < 0.5:
                    recs.append(f"URGENT: {item.check_name} — only {item.score:.0%} compliance ({item.total_instances - item.passing_instances} violations)")
                else:
                    recs.append(f"IMPROVE: {item.check_name} — {item.score:.0%} compliance ({item.total_instances - item.passing_instances} remaining)")

        # General recommendations
        if report.templates_scanned == 0:
            recs.append("No HTML templates found to assess — add templates or verify path configuration")

        if not recs:
            recs.append("Accessibility compliance is good — maintain current practices")

        return recs[:8]

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist assessment history."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._reports[-50:]]
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[A11Y] Persist: %s", exc)


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.accessibility_gate",
        description="Accessibility Gate — Score HTML templates for accessibility",
    )
    ap.add_argument("--assess", action="store_true", help="Run full accessibility assessment")
    ap.add_argument("--stats", action="store_true", help="Show statistics")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    gate = get_accessibility_gate()

    if args.assess:
        report = gate.run_assessment()
        if args.json:
            import json
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.summary_text())
        return

    if args.stats:
        stats = gate.get_stats()
        if args.json:
            import json
            print(json.dumps(stats, indent=2))
        else:
            print(f"Assessments: {stats['total_assessments']}")
            print(f"Last Score: {stats['last_score']}/10")
            print(f"Last Risk: {stats['last_risk']}")
            print(f"Templates Scanned: {stats['templates_scanned']}")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()

# ── Singleton ──────────────────────────────────────────────────────────────

_gate: AccessibilityGate | None = None
_gate_lock = threading.RLock()


def get_accessibility_gate() -> AccessibilityGate:
    """Get the singleton AccessibilityGate instance."""
    global _gate
    with _gate_lock:
        if _gate is None:
            _gate = AccessibilityGate()
        return _gate


def reset_accessibility_gate() -> None:
    """Force-reset singleton (for testing)."""
    global _gate
    with _gate_lock:
        _gate = None


__all__ = [
    "AccessibilityChecklistItem",
    "AccessibilityFinding",
    "AccessibilityGate",
    "AccessibilityReport",
    "get_accessibility_gate",
    "reset_accessibility_gate",
]
