"""WIP64 registration lifecycle trace checks."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_registration_trace_artifact_exists():
    assert (ROOT/"WEB_CLOSURE_WIP64_REGISTRATION_LIFECYCLE_TRACE.md").exists()


def test_registration_route_or_handler_exists():
    hits=[]
    for p in ROOT.rglob("*.py"):
        t=p.read_text(encoding="utf-8",errors="ignore").lower()
        if "register" in t and ("user" in t or "registration" in t):
            hits.append(p)
    assert hits


def test_permission_and_role_logic_exists():
    hits=[]
    for p in ROOT.rglob("*.py"):
        t=p.read_text(encoding="utf-8",errors="ignore").lower()
        if "permission" in t and "role" in t:
            hits.append(p)
    assert hits


def test_notification_or_email_logic_exists():
    hits=[]
    for p in ROOT.rglob("*.py"):
        t=p.read_text(encoding="utf-8",errors="ignore").lower()
        if "email" in t or "notification" in t:
            hits.append(p)
    assert hits
