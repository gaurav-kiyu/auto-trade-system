"""WIP34 regression contract for the confirmed runtime URL bypass."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_confirmed_runtime_file_uses_canonical_public_url_boundary():
    status = ROOT / "WEB_CLOSURE_WIP34_CONFIRMED_RUNTIME_BYPASS.md"
    text = status.read_text(encoding="utf-8")
    assert "get_public_base_url()" in text


def test_canonical_resolver_supports_admin_override():
    p = ROOT / "core/notifications/url_resolver.py"
    text = p.read_text(encoding="utf-8")
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text
    assert "def get_public_base_url" in text


def test_admin_setup_exposes_effective_url():
    p = ROOT / "templates/enterprise/admin_config.html"
    text = p.read_text(encoding="utf-8")
    assert 'id="effectivePublicUrl"' in text
