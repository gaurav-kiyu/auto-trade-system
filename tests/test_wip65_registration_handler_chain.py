"""WIP65 concrete registration handler chain checks."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_handler_chain_evidence_exists():
    p=ROOT/"WEB_CLOSURE_WIP65_REGISTRATION_HANDLER_CHAIN.md"
    assert p.exists()
    assert "Registration Handler Chain" in p.read_text(encoding="utf-8")


def test_registration_route_candidates_are_present():
    text=(ROOT/"WEB_CLOSURE_WIP65_REGISTRATION_HANDLER_CHAIN.md").read_text(encoding="utf-8")
    assert "Registration route candidates" in text


def test_registration_code_has_persistence_or_user_creation():
    hits=[]
    for p in ROOT.rglob("*.py"):
        t=p.read_text(encoding="utf-8",errors="ignore").lower()
        if "register" in t and any(x in t for x in ("create_user","add_user","db.add","commit")):
            hits.append(p)
    assert hits


def test_lifecycle_has_email_or_notification_and_role_permission():
    chunks=[]
    for p in ROOT.rglob("*.py"):
        t=p.read_text(encoding="utf-8",errors="ignore").lower()
        if "register" in t:
            chunks.append(t)
    text="\n".join(chunks)
    assert ("email" in text or "notification" in text)
    assert "role" in text
    assert "permission" in text
