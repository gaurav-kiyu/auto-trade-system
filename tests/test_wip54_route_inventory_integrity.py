"""WIP54 route inventory integrity checks."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_wip53_reconciliation_artifact_exists():
    assert (ROOT/"WEB_CLOSURE_WIP53_ROUTE_RECONCILIATION.md").exists()


def test_unmatched_route_forensic_artifact_exists():
    assert (ROOT/"WEB_CLOSURE_WIP54_UNMATCHED_ROUTE_FORENSIC.md").exists()


def test_canonical_url_boundary_exists():
    text=(ROOT/"core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "def build_action_url" in text
    assert "def get_public_base_url" in text
