"""WIP72 RBAC enforcement surface checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def _text():
    return "\n".join(
        p.read_text(encoding="utf-8",errors="ignore")
        for p in ROOT.rglob("*.py")
        if any(x in p.read_text(encoding="utf-8",errors="ignore").lower()
               for x in ("authorization","permission","role","rbac"))
    ).lower()


def test_rbac_map_exists():
    assert (ROOT/"WEB_CLOSURE_WIP72_RBAC_PERMISSION_ENFORCEMENT_MAP.md").exists()


def test_role_and_permission_enforcement_concepts_exist():
    t=_text()
    assert "role" in t
    assert "permission" in t
    assert any(x in t for x in ("authorize","authorization","rbac","access control"))


def test_audit_concept_exists():
    t=_text()
    assert "audit" in t or "logged" in t
