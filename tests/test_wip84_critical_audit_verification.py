"""WIP84 critical mutation audit verification."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_critical_verification_report_exists():
    p=ROOT/"WEB_CLOSURE_WIP84_CRITICAL_MUTATION_AUDIT_VERIFICATION.md"
    assert p.exists()
    assert "Critical Mutation Audit Verification" in p.read_text(encoding="utf-8")


def test_critical_areas_are_explicit():
    text=(ROOT/"WEB_CLOSURE_WIP84_CRITICAL_MUTATION_AUDIT_VERIFICATION.md").read_text(encoding="utf-8")
    for x in (
        "User registration and user administration",
        "Role and individual permission changes",
        "Setup Configuration changes",
        "Deployment URL / Admin URL override / Base URL",
        "Approve / Reject / Rollback",
        "Signal and stop-loss changes",
    ):
        assert x in text


def test_universal_audit_gate_remains():
    text=(ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    assert "Every state-changing action must create an immutable audit event." in text
