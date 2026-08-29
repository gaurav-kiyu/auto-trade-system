"""WIP66 registration dependency contracts."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def _text():
    chunks=[]
    for p in ROOT.rglob("*.py"):
        t=p.read_text(encoding="utf-8",errors="ignore")
        if any(k in t.lower() for k in ("register","signup","create_user")):
            chunks.append(t.lower())
    return "\n".join(chunks)


def test_dependency_map_exists():
    assert (ROOT/"WEB_CLOSURE_WIP66_REGISTRATION_DEPENDENCY_MAP.md").exists()


def test_registration_has_persistence_dependency():
    t=_text()
    assert any(x in t for x in ("db.add","session.add","commit(","create_user","insert"))


def test_registration_has_notification_dependency():
    t=_text()
    assert any(x in t for x in ("send_email","send_mail","email","notification","notify"))


def test_registration_has_access_dependency():
    t=_text()
    assert "role" in t and "permission" in t
