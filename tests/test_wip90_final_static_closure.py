from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_final_static_matrix_exists():
    p = ROOT / "WEB_CLOSURE_WIP90_FINAL_STATIC_CLOSURE_MATRIX.md"
    assert p.exists()
    assert "Final Static Closure Matrix" in p.read_text(encoding="utf-8")

def test_universal_audit_requirement():
    t = (ROOT / "WEB_CLOSURE_WIP90_FINAL_STATIC_CLOSURE_MATRIX.md").read_text(encoding="utf-8")
    assert "Every durable state change must produce exactly one authoritative server-side audit event." in t

def test_logging_requirement():
    t = (ROOT / "WEB_CLOSURE_WIP90_FINAL_STATIC_CLOSURE_MATRIX.md").read_text(encoding="utf-8")
    assert "Operational/application logs must provide useful success/failure diagnostics" in t

def test_reject_rollback_requirement():
    t = (ROOT / "WEB_CLOSURE_WIP90_FINAL_STATIC_CLOSURE_MATRIX.md").read_text(encoding="utf-8")
    assert "Reject and rollback require a valid reason" in t

def test_privileged_url_requirement():
    t = (ROOT / "WEB_CLOSURE_WIP90_FINAL_STATIC_CLOSURE_MATRIX.md").read_text(encoding="utf-8")
    assert "Deployment URL, Admin URL override and Base/Public URL" in t
