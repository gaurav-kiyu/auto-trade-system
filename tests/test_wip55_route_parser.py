"""WIP55 route parser regression checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_true_route_inventory_exists():
    p=ROOT/"WEB_CLOSURE_WIP55_TRUE_ROUTE_INVENTORY.md"
    assert p.exists()
    text=p.read_text(encoding="utf-8")
    assert "True route-like UI references" in text


def test_navigation_forensic_inventory_exists():
    assert (ROOT/"WEB_CLOSURE_WIP52_NAVIGATION_FORENSIC_INVENTORY.md").exists()
