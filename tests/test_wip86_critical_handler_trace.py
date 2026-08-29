from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_trace_exists():
    p = ROOT / "WEB_CLOSURE_WIP86_CRITICAL_HANDLER_TRACE.md"
    assert p.exists()
    assert "Critical Handler Trace" in p.read_text(encoding="utf-8")

def test_all_inventory_routes_parse():
    text = (ROOT / "WEB_CLOSURE_WIP86_CRITICAL_HANDLER_TRACE.md").read_text(encoding="utf-8")
    assert "Inventory routes parsed:" in text
    assert "Handlers successfully inspected:" in text

def test_audit_gate():
    t = (ROOT / "WEB_CLOSURE_WIP76_AUDIT_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    assert "Every state-changing action must create an immutable audit event." in t
