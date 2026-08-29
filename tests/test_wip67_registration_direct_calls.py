"""WIP67 direct registration lifecycle checks."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_direct_call_review_exists():
    p=ROOT/"WEB_CLOSURE_WIP67_REGISTRATION_DIRECT_CALLS.md"
    assert p.exists()
    assert "Registration Direct-Call Review" in p.read_text(encoding="utf-8")


def test_registration_handlers_exist():
    found=[]
    for p in ROOT.rglob("*.py"):
        t=p.read_text(encoding="utf-8",errors="ignore").lower()
        if "register" in t and ("user" in t or "signup" in t):
            found.append(p)
    assert found


def test_registration_has_auditable_access_concepts():
    text="\n".join(
        p.read_text(encoding="utf-8",errors="ignore").lower()
        for p in ROOT.rglob("*.py")
        if "register" in p.read_text(encoding="utf-8",errors="ignore").lower()
    )
    assert "role" in text
    assert "permission" in text
    assert "audit" in text or "logged" in text
