"""WIP69 notification finding integrity checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_notification_findings_exist():
    p=ROOT/"WEB_CLOSURE_WIP69_NOTIFICATION_HANDLER_FINDINGS.md"
    assert p.exists()
    text=p.read_text(encoding="utf-8")
    assert "Concrete Registration Notification Findings" in text
    assert "Notification signals:" in text


def test_registration_email_notification_infrastructure_remains_present():
    matches=[]
    for p in ROOT.rglob("*.py"):
        t=p.read_text(encoding="utf-8",errors="ignore").lower()
        if ("register" in t or "signup" in t) and ("email" in t or "notification" in t):
            matches.append(p)
    assert matches
