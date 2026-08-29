from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_final_e2e_runbook_exists():
    p=ROOT/"FINAL_E2E_SIGNOFF_RUNBOOK.md"
    assert p.exists()
    t=p.read_text(encoding="utf-8")
    assert "Reject without reason" in t
    assert "Rollback without reason" in t
    assert "Super Admin receives immediate notification" in t
    assert "Direct API calls are denied" in t
def test_no_secret_usage_in_runbook():
    t=(ROOT/"FINAL_E2E_SIGNOFF_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Do not use production credentials/secrets" in t
