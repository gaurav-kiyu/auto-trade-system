from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_report_exists():
    p=ROOT/"WEB_CLOSURE_WIP88_AUDIT_AND_LOGGING_GAP_TRACE.md"
    assert p.exists()
    assert "Proper Logging Gap Trace" in p.read_text(encoding="utf-8")
def test_audit_and_logging_are_distinct():
    t=(ROOT/"WEB_CLOSURE_WIP88_AUDIT_AND_LOGGING_GAP_TRACE.md").read_text(encoding="utf-8")
    assert "Audit logs are immutable security records" in t
    assert "Operational logs record useful execution/error context" in t
def test_secret_exclusion():
    t=(ROOT/"WEB_CLOSURE_WIP88_AUDIT_AND_LOGGING_GAP_TRACE.md").read_text(encoding="utf-8")
    assert "secrets/passwords/tokens are never logged" in t
def test_reason_rule():
    t=(ROOT/"WEB_CLOSURE_WIP88_AUDIT_AND_LOGGING_GAP_TRACE.md").read_text(encoding="utf-8")
    assert "Reject/Rollback requires a reason" in t
