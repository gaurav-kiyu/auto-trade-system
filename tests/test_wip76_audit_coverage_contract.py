"""WIP76 audit coverage contract."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_audit_matrix_exists():
    p=ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md"
    assert p.exists()
    text=p.read_text(encoding="utf-8")
    assert "Every state-changing action must create an immutable audit event." in text


def test_audit_matrix_covers_security_and_rbac():
    text=(ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    assert "Authentication/security events must be auditable." in text
    assert "Permission/role changes record actor, subject, before/after effective access." in text


def test_sensitive_data_is_excluded():
    text=(ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    assert "Sensitive secrets/passwords/tokens must never be written to audit logs." in text


def test_reasoned_reject_rollback_is_audited():
    text=(ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    assert "Reject and rollback require a reason and record that reason." in text
