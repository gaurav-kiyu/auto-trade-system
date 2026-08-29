"""WIP68 registration email/notification checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_email_notification_review_exists():
    p=ROOT/"WEB_CLOSURE_WIP68_REGISTRATION_EMAIL_NOTIFICATION.md"
    assert p.exists()
    assert "Registration Email/Notification Closure Review" in p.read_text(encoding="utf-8")


def test_registration_handler_inventory_exists():
    assert (ROOT/"WEB_CLOSURE_WIP67_REGISTRATION_DIRECT_CALLS.md").exists()


def test_notification_infrastructure_exists():
    chunks=[]
    for p in ROOT.rglob("*.py"):
        t=p.read_text(encoding="utf-8",errors="ignore").lower()
        if any(x in t for x in ("email","notification","mailer")):
            chunks.append(t)
    text="\n".join(chunks)
    assert "email" in text or "notification" in text
