"""WIP48 SSO callback URL contract."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_opb_callback_uses_canonical_action_builder():
    text = (ROOT / "core/auth/routes.py").read_text(encoding="utf-8")
    assert "build_action_url" in text
    assert '"/api/auth/sso/callback"' in text


def test_provider_configuration_is_not_replaced_by_app_base_url():
    text = (ROOT / "core/auth/sso.py").read_text(encoding="utf-8")
    # The SSO client must retain provider configuration concepts.
    assert "authorization" in text.lower()
    assert "token" in text.lower()


def test_public_url_resolver_has_admin_override():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text
