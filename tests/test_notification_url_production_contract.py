import os
from core.notifications.url_resolver import (
    DEFAULT_PRODUCTION_URL,
    build_action_url,
    get_public_base_url,
)


def test_production_loopback_base_url_never_escapes(monkeypatch):
    monkeypatch.setenv("OPB_ENV", "production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")
    assert get_public_base_url() == DEFAULT_PRODUCTION_URL
    assert build_action_url("/my-signals", base_url="http://127.0.0.1:8000") == (
        DEFAULT_PRODUCTION_URL + "/my-signals"
    )


def test_production_config_loopback_base_url_never_escapes(monkeypatch):
    monkeypatch.setenv("OPB_ENV", "production")
    cfg = {"PUBLIC_BASE_URL": "http://localhost:8000"}
    assert get_public_base_url(cfg) == DEFAULT_PRODUCTION_URL
    assert build_action_url("/admin/signals", cfg=cfg) == DEFAULT_PRODUCTION_URL + "/admin/signals"


def test_production_public_url_is_preserved(monkeypatch):
    monkeypatch.setenv("OPB_ENV", "production")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    assert get_public_base_url({"PUBLIC_BASE_URL": "https://gaurav-cockpit.servegame.com"}) == (
        "https://gaurav-cockpit.servegame.com"
    )
