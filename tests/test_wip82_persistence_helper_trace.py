"""WIP82 persistence helper trace contract."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_deep_trace_exists():
    p=ROOT/"WEB_CLOSURE_WIP82_PERSISTENCE_HELPER_DEEP_TRACE.md"
    assert p.exists()
    assert "Persistence Helper Deep Trace" in p.read_text(encoding="utf-8")


def test_audit_contract_is_retained():
    p=ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md"
    text=p.read_text(encoding="utf-8")
    assert "Every state-changing action must create an immutable audit event." in text


def test_no_secret_logging_rule_is_retained():
    text=(ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    assert "Sensitive secrets/passwords/tokens must never be written to audit logs." in text
