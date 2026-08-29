from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_final_trace_exists():
    p=ROOT/"WEB_CLOSURE_WIP89_FINAL_CRITICAL_LOG_TRACE.md"
    assert p.exists()
    assert "Final Critical Audit + Logging Trace" in p.read_text(encoding="utf-8")

def test_one_authoritative_audit_contract():
    t=(ROOT/"WEB_CLOSURE_WIP89_FINAL_CRITICAL_LOG_TRACE.md").read_text(encoding="utf-8")
    assert "exactly one authoritative server-side audit event" in t

def test_logging_contract():
    t=(ROOT/"WEB_CLOSURE_WIP89_FINAL_CRITICAL_LOG_TRACE.md").read_text(encoding="utf-8")
    assert "Operational logging must provide diagnostic context" in t

def test_sensitive_config_and_reason_contract():
    t=(ROOT/"WEB_CLOSURE_WIP89_FINAL_CRITICAL_LOG_TRACE.md").read_text(encoding="utf-8")
    assert "Deployment URL" in t and "Admin URL override" in t
    assert "Reject/Rollback requires a valid reason" in t
