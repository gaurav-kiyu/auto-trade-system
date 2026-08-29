"""WIP44 SSO URL semantic regression contracts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sso_module_exposes_canonical_url_boundary():
    text = (ROOT / "core/auth/sso.py").read_text(encoding="utf-8")
    # The module must be able to use the centralized resolver/builder rather
    # than inventing a public origin.
    assert (
        "build_action_url" in text
        or "get_public_base_url" in text
    )


def test_sso_routes_keep_canonical_callback():
    text = (ROOT / "core/auth/routes.py").read_text(encoding="utf-8")
    assert "build_action_url" in text
    assert '"/api/auth/sso/callback"' in text


def test_public_url_override_is_supported():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text
    assert "def get_public_base_url" in text
