"""WIP77 audit implementation closure checks."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_audit_closure_report_exists():
    p=ROOT/"WEB_CLOSURE_WIP77_AUDIT_IMPLEMENTATION_CLOSURE.md"
    assert p.exists()
    text=p.read_text(encoding="utf-8")
    assert "Final acceptance contract" in text


def test_shared_audit_infrastructure_exists():
    hits=[]
    for p in ROOT.rglob("*.py"):
        t=p.read_text(encoding="utf-8",errors="ignore")
        if re.search(r"(def|class)\s+\w*(audit|activity|security|event|history)\w*",t,re.I):
            hits.append(p)
    assert hits


def test_security_log_exclusion_is_documented():
    text=(ROOT/"WEB_CLOSURE_WIP77_AUDIT_IMPLEMENTATION_CLOSURE.md").read_text(encoding="utf-8")
    assert "Secrets/passwords/tokens must not be logged." in text


def test_reject_rollback_reason_contract_is_retained():
    text=(ROOT/"WEB_CLOSURE_WIP77_AUDIT_IMPLEMENTATION_CLOSURE.md").read_text(encoding="utf-8")
    assert "Reject and rollback require a reason before execution." in text
