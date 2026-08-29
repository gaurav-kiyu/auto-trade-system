"""WIP36 guardrails for the canonical public URL boundary."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sso_callback_is_centralized():
    text = (ROOT / "core/auth/routes.py").read_text(encoding="utf-8")
    assert 'build_action_url(' in text
    assert '"/api/auth/sso/callback"' in text


def test_admin_override_is_runtime_resolvable():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text
    assert "def get_public_base_url" in text


def test_setup_ui_exposes_deployment_admin_and_effective_urls():
    text = (ROOT / "templates/enterprise/admin_config.html").read_text(encoding="utf-8")
    for field in ("deploymentPublicUrl", "adminPublicUrlOverride", "effectivePublicUrl"):
        assert f'id="{field}"' in text
