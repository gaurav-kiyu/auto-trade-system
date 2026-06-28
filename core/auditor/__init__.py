"""
Independent Auditor Subsystem (Phase 16).

The Auditor's job is to BREAK the system before production.

Auditor MUST:
- Challenge assumptions
- Challenge architecture
- Challenge risk controls
- Challenge strategies
- Challenge execution
- Challenge scoring

Every audit result provides objective evidence for Constitution Scoring.
"""

# Import data models from models.py and the auditor class from auditor.py
from core.auditor.auditor import (
    IndependentAuditor,
    get_auditor,
    reset_auditor,
)
from core.auditor.models import (
    AuditCategory,
    AuditEvidence,
    AuditFinding,
    AuditReport,
    AuditResult,
    AuditSeverity,
    AuditStatus,
)

__all__ = [
    "AuditCategory",
    "AuditEvidence",
    "AuditFinding",
    "AuditReport",
    "AuditResult",
    "AuditSeverity",
    "AuditStatus",
    "IndependentAuditor",
    "get_auditor",
    "reset_auditor",
]
