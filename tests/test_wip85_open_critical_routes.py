"""WIP85 open critical audit route inventory."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_open_critical_route_inventory_exists():
    p=ROOT/"WEB_CLOSURE_WIP85_OPEN_CRITICAL_AUDIT_ROUTES.md"
    assert p.exists()
    assert "Open Critical Audit Routes" in p.read_text(encoding="utf-8")


def test_critical_audit_gate_is_still_hard():
    text=(ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    assert "Every state-changing action must create an immutable audit event." in text


def test_reject_rollback_reason_rule_is_still_hard():
    text=(ROOT/"WEB_CLOSURE_WIP75_STATUS.md").read_text(encoding="utf-8")
    assert "Reason is mandatory." in text
