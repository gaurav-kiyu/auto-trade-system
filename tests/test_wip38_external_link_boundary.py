"""WIP38 external-link boundary regression contracts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_external_link_builder():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "def build_action_url" in text
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text


def test_setup_configuration_exposes_url_layers():
    text = (ROOT / "templates/enterprise/admin_config.html").read_text(encoding="utf-8")
    assert 'id="deploymentPublicUrl"' in text
    assert 'id="adminPublicUrlOverride"' in text
    assert 'id="effectivePublicUrl"' in text


def test_sso_external_callback_is_centralized():
    text = (ROOT / "core/auth/routes.py").read_text(encoding="utf-8")
    assert "build_action_url" in text
    assert '"/api/auth/sso/callback"' in text
