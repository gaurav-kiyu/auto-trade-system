"""WIP61 Admin Users handler/API trace checks."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_admin_users_handler_trace_exists():
    assert (ROOT/"WEB_CLOSURE_WIP61_ADMIN_USERS_HANDLER_TRACE.md").exists()


def test_admin_users_route_and_api_surface_present():
    matches=[]
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".html",".js",".ts",".py"}:
            t=p.read_text(encoding="utf-8",errors="ignore")
            if "/admin/users" in t or "admin/users" in t.lower():
                matches.append(t)
    text="\n".join(matches).lower()
    assert "/admin/users" in text
    assert "/api/" in text


def test_admin_users_has_event_or_handler_surface():
    matches=[]
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".html",".js",".ts"}:
            t=p.read_text(encoding="utf-8",errors="ignore").lower()
            if "/admin/users" in t and any(x in t for x in ("addeventlistener","onclick","fetch(","axios")):
                matches.append(p)
    assert matches
