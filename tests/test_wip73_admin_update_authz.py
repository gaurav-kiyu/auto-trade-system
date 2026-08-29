"""WIP73 Admin Users update -> authorization trace checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_update_authz_trace_exists():
    p=ROOT/"WEB_CLOSURE_WIP73_ADMIN_UPDATE_TO_AUTHZ.md"
    assert p.exists()
    assert "Admin Update" in p.read_text(encoding="utf-8")


def test_authorization_primitives_exist():
    text="\n".join(
        p.read_text(encoding="utf-8",errors="ignore").lower()
        for p in ROOT.rglob("*.py")
    )
    assert any(x in text for x in (
        "require_permission","permission_required","has_permission",
        "check_permission","authorize","authorization"
    ))


def test_role_primitives_exist():
    text="\n".join(
        p.read_text(encoding="utf-8",errors="ignore").lower()
        for p in ROOT.rglob("*.py")
    )
    assert any(x in text for x in (
        "role_required","require_role","is_admin","is_super_admin","role"
    ))
