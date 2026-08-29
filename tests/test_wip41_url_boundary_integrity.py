"""WIP41 URL boundary integrity tests."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_url_resolver_and_builder():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "def build_action_url" in text
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text


def test_setup_url_layers():
    text = (ROOT / "templates/enterprise/admin_config.html").read_text(encoding="utf-8")
    assert 'id="deploymentPublicUrl"' in text
    assert 'id="adminPublicUrlOverride"' in text
    assert 'id="effectivePublicUrl"' in text


def test_sso_callback_boundary():
    text = (ROOT / "core/auth/routes.py").read_text(encoding="utf-8")
    assert "build_action_url" in text
    assert '"/api/auth/sso/callback"' in text
