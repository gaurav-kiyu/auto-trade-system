"""WIP81 persistence-to-audit review checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_persistence_audit_gap_report_exists():
    p=ROOT/"WEB_CLOSURE_WIP81_PERSISTENCE_AUDIT_GAPS.md"
    assert p.exists()
    assert "Persistence → Audit Gap Review" in p.read_text(encoding="utf-8")


def test_universal_audit_contract_is_retained():
    p=ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md"
    text=p.read_text(encoding="utf-8")
    assert "Every state-changing action must create an immutable audit event." in text


def test_reject_rollback_reason_is_retained():
    text=(ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    assert "Reject and rollback require a reason and record that reason." in text
