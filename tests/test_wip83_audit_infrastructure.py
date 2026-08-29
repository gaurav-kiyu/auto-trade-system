"""WIP83 audit infrastructure checks."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def test_audit_infrastructure_report_exists():
    p = ROOT / "WEB_CLOSURE_WIP83_AUDIT_INFRASTRUCTURE_CLOSURE.md"
    assert p.exists()
    assert "Audit Infrastructure Closure" in p.read_text(encoding="utf-8")

def test_shared_audit_writer_exists_somewhere():
    found = []
    for p in ROOT.rglob("*.py"):
        t = p.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"(def|async def)\s+\w*(audit|activity|security|event|history)\w*\s*\(", t, re.I):
            found.append(p)
    assert found

def test_hard_audit_gate_is_preserved():
    p = ROOT / "WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md"
    text = p.read_text(encoding="utf-8")
    assert "Every state-changing action must create an immutable audit event." in text
    assert "Sensitive secrets/passwords/tokens must never be written to audit logs." in text

def test_reject_rollback_reason_is_preserved():
    text = (ROOT / "WEB_CLOSURE_WIP74_SETUP_CONFIG_PRIVILEGED_CHANGE_WORKFLOW.md").read_text(encoding="utf-8")
    assert "Mandatory reason requirement" in text
    assert "Minimum length: 10 characters." in text
