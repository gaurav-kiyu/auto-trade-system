"""WIP59 Admin Users functional surface checks."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def _files():
    out=[]
    for folder in ("templates","static","core","app"):
        p=ROOT/folder
        if p.exists():
            out.extend(x for x in p.rglob("*") if x.is_file() and x.suffix.lower() in {".html",".js",".ts",".py"})
    return out


def test_admin_users_route_exists_in_source():
    hits=[]
    for p in _files():
        t=p.read_text(encoding="utf-8",errors="ignore")
        if "/admin/users" in t:
            hits.append(p)
    assert hits


def test_admin_users_has_action_or_detail_surface():
    hits=[]
    for p in _files():
        t=p.read_text(encoding="utf-8",errors="ignore")
        low=t.lower()
        if "/admin/users" in t and any(x in low for x in ("eye","action","details","filter","search")):
            hits.append(p)
    assert hits


def test_admin_users_has_permission_surface():
    hits=[]
    for p in _files():
        t=p.read_text(encoding="utf-8",errors="ignore")
        low=t.lower()
        if "/admin/users" in t and any(x in low for x in ("permission","role","authorization","privilege")):
            hits.append(p)
    assert hits
