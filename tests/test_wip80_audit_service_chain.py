"""WIP80 audit service/helper chain checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_service_chain_review_exists():
    p=ROOT/"WEB_CLOSURE_WIP80_AUDIT_SERVICE_CHAIN_REVIEW.md"
    assert p.exists()
    assert "Audit Service/Helper Chain Review" in p.read_text(encoding="utf-8")


def test_wip79_unresolved_map_is_preserved():
    assert (ROOT/"WEB_CLOSURE_WIP79_UNRESOLVED_AUDIT_CALLCHAINS.md").exists()


def test_universal_audit_gate_is_preserved():
    text=(ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    assert "Every state-changing action must create an immutable audit event." in text
