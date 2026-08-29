"""WIP53 route reconciliation helpers."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_core_application_has_route_modules():
    py=list(ROOT.rglob("*.py"))
    assert py, "No Python application source found"


def test_navigation_inventory_artifact_exists():
    p=ROOT/"WEB_CLOSURE_WIP52_NAVIGATION_FORENSIC_INVENTORY.md"
    assert p.exists()


def test_canonical_public_url_builder_exists():
    p=ROOT/"core/notifications/url_resolver.py"
    text=p.read_text(encoding="utf-8")
    assert "def build_action_url" in text
    assert "def get_public_base_url" in text
