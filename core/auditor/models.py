"""
Audit Data Models — extracted from auditor.py for SRP compliance.

Contains all enums and data classes used by the Independent Auditor.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ── Enums ─────────────────────────────────────────────────────────────────────


class AuditCategory(Enum):
    ARCHITECTURE = "architecture"
    RISK_CONTROLS = "risk_controls"
    EXECUTION = "execution"
    STRATEGY = "strategy"
    SECURITY = "security"
    SCORING = "scoring"
    REPLAY = "replay"
    RESILIENCE = "resilience"
    GOVERNANCE = "governance"
    TESTING = "testing"


class AuditSeverity(Enum):
    CRITICAL = "critical"      # Must fix before production
    HIGH = "high"              # Should fix before production
    MEDIUM = "medium"          # Should fix within the next release
    LOW = "low"                # Nice to have
    INFO = "info"              # Informational only


class AuditStatus(Enum):
    PASS = "pass"              # Evidence confirms requirement is met
    FAIL = "fail"              # Evidence shows requirement is NOT met
    WARN = "warn"              # Partial compliance, some concern
    NOT_TESTED = "not_tested"  # No evidence available
    NOT_APPLICABLE = "n/a"     # Not applicable to current configuration


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class AuditEvidence:
    """Single piece of objective evidence for an audit finding."""
    description: str
    source: str                # File path, module name, or function name
    detail: str = ""           # Additional detail (code snippet, value, etc.)
    passed: bool = True        # Whether this evidence passes the check

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "source": self.source,
            "detail": self.detail,
            "passed": self.passed,
        }


@dataclass
class AuditFinding:
    """A single audit finding with evidence."""
    category: AuditCategory
    title: str
    severity: AuditSeverity
    status: AuditStatus
    description: str
    evidence: list[AuditEvidence] = field(default_factory=list)
    recommendation: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def passed(self) -> bool:
        return self.status == AuditStatus.PASS

    def add_evidence(self, evidence: AuditEvidence) -> None:
        self.evidence.append(evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "title": self.title,
            "severity": self.severity.value,
            "status": self.status.value,
            "description": self.description,
            "recommendation": self.recommendation,
            "evidence_count": len(self.evidence),
            "evidence": [e.to_dict() for e in self.evidence],
            "passed": self.passed,
            "timestamp": self.timestamp,
        }


@dataclass
class AuditReport:
    """Complete audit report with all findings."""
    generated_at: str
    total_findings: int
    passed: int
    failed: int
    warnings: int
    not_tested: int
    findings: list[AuditFinding]
    overall_score: float = 0.0  # 0.0 - 10.0

    def print_summary(self) -> str:
        """Print a human-readable summary of the audit report."""
        lines = [
            "=" * 60,
            "  INDEPENDENT AUDIT REPORT",
            f"  Generated: {self.generated_at}",
            "=" * 60,
            f"  Overall Score: {self.overall_score:.2f} / 10.0",
            f"  Total Findings: {self.total_findings}",
            f"  ✅ Passed: {self.passed}",
            f"  ❌ Failed: {self.failed}",
            f"  ⚠️  Warnings: {self.warnings}",
            f"  🔍 Not Tested: {self.not_tested}",
            "=" * 60,
        ]

        # Group by category
        by_category: dict[str, list[AuditFinding]] = {}
        for f in self.findings:
            by_category.setdefault(f.category.value, []).append(f)

        for cat, cat_findings in sorted(by_category.items()):
            cat_passed = sum(1 for f in cat_findings if f.passed)
            cat_total = len(cat_findings)
            lines.append(f"\n  [{cat.upper()}] {cat_passed}/{cat_total} passed")
            for f in cat_findings:
                icon = "✅" if f.passed else ("❌" if f.status == AuditStatus.FAIL else "⚠️")
                lines.append(f"    {icon} [{f.severity.value}] {f.title}")
                if not f.passed:
                    lines.append(f"           {f.description}")
                    if f.recommendation:
                        lines.append(f"           → {f.recommendation}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "overall_score": self.overall_score,
            "total_findings": self.total_findings,
            "passed": self.passed,
            "failed": self.failed,
            "warnings": self.warnings,
            "not_tested": self.not_tested,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class AuditResult:
    """Container for a single audit result."""
    passed: bool
    evidence: list[AuditEvidence]
    findings: list[AuditFinding]
    score_delta: float = 0.0  # Suggested score adjustment based on findings


__all__ = [
    "AuditCategory",
    "AuditEvidence",
    "AuditFinding",
    "AuditReport",
    "AuditResult",
    "AuditSeverity",
    "AuditStatus",
]
