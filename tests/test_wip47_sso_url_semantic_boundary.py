"""WIP47 SSO URL semantic boundary tests."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sso_authorization_and_callback_functions_exist():
    text = (ROOT / "core/auth/sso.py").read_text(encoding="utf-8")
    assert "def get_authorization_url" in text
    assert "def handle_callback" in text


def test_sso_route_uses_application_public_url_boundary():
    text = (ROOT / "core/auth/routes.py").read_text(encoding="utf-8")
    assert "build_action_url" in text
    assert '"/api/auth/sso/callback"' in text


def test_canonical_resolver_supports_admin_override():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text
