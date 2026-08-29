"""Regression contract: externally generated runtime URLs must use the canonical resolver."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def test_notification_url_resolver_is_central():
    text = _read("core/notifications/url_resolver.py")
    assert "def get_public_base_url" in text
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text


def test_ssO_uses_canonical_public_url():
    text = _read("core/auth/routes.py")
    assert "build_action_url" in text


def test_admin_setup_exposes_two_layer_public_url_model():
    text = _read("templates/enterprise/admin_config.html")
    assert 'id="deploymentPublicUrl"' in text
    assert 'id="adminPublicUrlOverride"' in text
    assert 'id="effectivePublicUrl"' in text


def test_loopback_protection_exists():
    text = _read("core/notifications/url_resolver.py").lower()
    for token in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        assert token in text
