"""WIP79 audit call-chain mapping checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_unresolved_callchain_map_exists():
    p=ROOT/"WEB_CLOSURE_WIP79_UNRESOLVED_AUDIT_CALLCHAINS.md"
    assert p.exists()
    assert "Unresolved Audit Call-Chain Map" in p.read_text(encoding="utf-8")


def test_universal_audit_contract_remains_hard_gate():
    p=ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md"
    text=p.read_text(encoding="utf-8")
    assert "Every state-changing action must create an immutable audit event." in text


def test_no_secret_logging_contract_remains():
    text=(ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    assert "Sensitive secrets/passwords/tokens must never be written to audit logs." in text
