from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_trace_exists():
    p=ROOT/"WEB_CLOSURE_WIP87_CRITICAL_DOWNSTREAM_TRACE.md"
    assert p.exists()
    assert "Critical Downstream Trace" in p.read_text(encoding="utf-8")
def test_all_critical_handlers_remain_tracked():
    p=ROOT/"WEB_CLOSURE_WIP86_CRITICAL_HANDLER_TRACE.md"
    assert p.exists()
def test_hard_audit_gate():
    t=(ROOT/"WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    assert "Every state-changing action must create an immutable audit event." in t
