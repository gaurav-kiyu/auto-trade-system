from core.notifications.url_resolver import (
    DEFAULT_PRODUCTION_URL,
    get_public_base_url,
    invalidate_public_url_cache,
)


def test_admin_override_wins_over_environment(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://env.example.com")
    cfg = {"PUBLIC_BASE_URL_ADMIN_OVERRIDE": "https://admin.example.com"}
    assert get_public_base_url(cfg) == "https://admin.example.com"


def test_legacy_environment_override_still_works_without_admin_override(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://env.example.com")
    assert get_public_base_url({}) == "https://env.example.com"


def test_loopback_admin_override_falls_back_in_production():
    cfg = {"PUBLIC_BASE_URL_ADMIN_OVERRIDE": "http://localhost:8000", "ENVIRONMENT": "production"}
    assert get_public_base_url(cfg) == DEFAULT_PRODUCTION_URL


def test_cache_can_be_invalidated():
    invalidate_public_url_cache()
    assert get_public_base_url({"PUBLIC_BASE_URL_ADMIN_OVERRIDE": "https://one.example.com"}) == "https://one.example.com"
    invalidate_public_url_cache()
    assert get_public_base_url({"PUBLIC_BASE_URL_ADMIN_OVERRIDE": "https://two.example.com"}) == "https://two.example.com"


def test_sso_callback_uses_canonical_public_base_url():
    from core.notifications.url_resolver import build_action_url

    cfg = {
        "ENVIRONMENT": "production",
        "PUBLIC_BASE_URL_ADMIN_OVERRIDE": "https://ops.example.com",
    }
    assert build_action_url("/api/auth/sso/callback", cfg=cfg) == (
        "https://ops.example.com/api/auth/sso/callback"
    )
