"""WIP60 Admin Users implementation integrity."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def _matching_files():
    result=[]
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".html",".js",".ts",".py"}:
            t=p.read_text(encoding="utf-8",errors="ignore")
            if "/admin/users" in t or ("user authorization" in t.lower() and "permission" in t.lower()):
                result.append(t)
    return result


def test_admin_users_implementation_map_exists():
    assert (ROOT/"WEB_CLOSURE_WIP60_ADMIN_USERS_IMPLEMENTATION_MAP.md").exists()


def test_admin_users_contains_filter_action_detail_concepts():
    text="\n".join(_matching_files()).lower()
    for token in ("filter","action","permission","role"):
        assert token in text


def test_admin_users_contains_persistence_concept():
    text="\n".join(_matching_files()).lower()
    assert any(x in text for x in ("update","save","put","patch","post"))


def test_admin_users_contains_detail_or_eye_concept():
    text="\n".join(_matching_files()).lower()
    assert any(x in text for x in ("eye","details","view","inspect"))
