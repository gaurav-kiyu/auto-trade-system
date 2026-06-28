"""
Constitution data models — extracted from core/constitution.py for SRP compliance.

Provides ScoreEvidence, CategoryScore, ValidationResult, and ScoreReport
dataclasses used by the ConstitutionValidator and constitution scoring framework.

Usage:
    from core.constitution.models import ScoreEvidence, CategoryScore, ScoreReport
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


__all__ = [
    "CategoryScore",
    "ScoreEvidence",
    "ScoreReport",
    "ValidationResult",
]


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
