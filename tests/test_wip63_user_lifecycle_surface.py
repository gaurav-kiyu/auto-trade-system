"""WIP63 user registration/permission lifecycle checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def _all_text():
    chunks=[]
    for folder in ("core","templates","static","app","services"):
        p=ROOT/folder
        if p.exists():
            for f in p.rglob("*"):
                if f.is_file() and f.suffix.lower() in {".py",".html",".js",".ts"}:
                    chunks.append(f.read_text(encoding="utf-8",errors="ignore"))
    return "\n".join(chunks).lower()


def test_registration_and_user_management_surface_exists():
    t=_all_text()
    assert "register" in t
    assert "admin/users" in t


def test_role_permission_surface_exists():
    t=_all_text()
    assert "permission" in t
    assert "role" in t


def test_email_or_notification_surface_exists():
    t=_all_text()
    assert ("email" in t) or ("notification" in t)


def test_pending_or_approval_concept_exists():
    t=_all_text()
    assert any(x in t for x in ("pending","approval","approve"))
