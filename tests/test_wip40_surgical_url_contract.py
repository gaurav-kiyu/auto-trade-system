"""WIP40 surgical URL repair regression contracts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_resolver_and_builder_exist():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "def build_action_url" in text
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text


def test_sso_callback_remains_canonical():
    text = (ROOT / "core/auth/routes.py").read_text(encoding="utf-8")
    assert "build_action_url" in text
    assert '"/api/auth/sso/callback"' in text


def test_setup_has_three_url_states():
    text = (ROOT / "templates/enterprise/admin_config.html").read_text(encoding="utf-8")
    for field in ("deploymentPublicUrl", "adminPublicUrlOverride", "effectivePublicUrl"):
        assert f'id="{field}"' in text


def test_loopback_protection_remains_present():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8").lower()
    for token in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        assert token in text
