"""Regression contract for canonical SSO external URL generation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sso_uses_central_action_url_builder():
    text = (ROOT / "core/auth/routes.py").read_text(encoding="utf-8")
    assert 'build_action_url(' in text
    assert '"/api/auth/sso/callback"' in text


def test_action_url_builder_uses_canonical_public_url():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "def build_action_url" in text
    assert "get_public_base_url" in text


def test_admin_override_is_part_of_canonical_resolution():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text
