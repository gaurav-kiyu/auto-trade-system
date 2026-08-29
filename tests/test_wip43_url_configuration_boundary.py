"""WIP43 URL configuration boundary regression tests."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_resolver():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "def build_action_url" in text
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text


def test_setup_exposes_deployment_override_effective_layers():
    text = (ROOT / "templates/enterprise/admin_config.html").read_text(encoding="utf-8")
    for field in ("deploymentPublicUrl", "adminPublicUrlOverride", "effectivePublicUrl"):
        assert f'id="{field}"' in text


def test_sso_callback_stays_on_canonical_builder():
    text = (ROOT / "core/auth/routes.py").read_text(encoding="utf-8")
    assert "build_action_url" in text
    assert '"/api/auth/sso/callback"' in text
