"""WIP56 canonical navigation tree checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_navigation_tree_artifact_exists():
    p=ROOT/"WEB_CLOSURE_WIP56_NAVIGATION_TREE.md"
    assert p.exists()
    text=p.read_text(encoding="utf-8")
    assert "Canonical Web Navigation Tree" in text


def test_admin_setup_is_present_in_navigation_source():
    matches=[]
    for folder in ("templates","static"):
        root=ROOT/folder
        if not root.exists(): continue
        for p in root.rglob("*"):
            if p.suffix.lower() not in {".html",".js",".ts"}: continue
            text=p.read_text(encoding="utf-8",errors="ignore").lower()
            if "admin" in text and ("setup" in text or "configuration" in text):
                matches.append(p)
    assert matches


def test_logout_term_exists_in_ui_source():
    matches=[]
    for folder in ("templates","static"):
        root=ROOT/folder
        if not root.exists(): continue
        for p in root.rglob("*"):
            if p.suffix.lower() not in {".html",".js",".ts"}: continue
            if "logout" in p.read_text(encoding="utf-8",errors="ignore").lower():
                matches.append(p)
    assert matches
