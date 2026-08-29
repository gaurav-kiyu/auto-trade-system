"""WIP57 navigation implementation map checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_navigation_implementation_map_exists():
    p=ROOT/"WEB_CLOSURE_WIP57_NAVIGATION_IMPLEMENTATION_MAP.md"
    assert p.exists()
    assert "Navigation Implementation Map" in p.read_text(encoding="utf-8")


def test_navigation_checklist_exists():
    p=ROOT/"WEB_CLOSURE_WIP57_NAVIGATION_CHECKLIST.csv"
    assert p.exists()
    assert "execution_status" in p.read_text(encoding="utf-8").splitlines()[0]


def test_wip56_tree_exists():
    assert (ROOT/"WEB_CLOSURE_WIP56_NAVIGATION_TREE.md").exists()
