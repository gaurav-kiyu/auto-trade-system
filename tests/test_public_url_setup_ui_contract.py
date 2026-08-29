"""Regression contracts for the two-layer Public URL setup model."""
from pathlib import Path
import os

from core.notifications.url_resolver import (
    DEFAULT_DEV_URL,
    DEFAULT_PRODUCTION_URL,
    get_deployment_base_url,
    get_public_base_url,
)


ROOT = Path(__file__).resolve().parents[1]


def test_deployment_url_ignores_admin_override(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://deployment.example.com")
    cfg = {"PUBLIC_BASE_URL": "https://config.example.com",
           "PUBLIC_BASE_URL_ADMIN_OVERRIDE": "https://admin.example.com"}
    assert get_deployment_base_url(cfg) == "https://deployment.example.com"


def test_admin_override_is_effective_url(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://deployment.example.com")
    cfg = {"PUBLIC_BASE_URL_ADMIN_OVERRIDE": "https://admin.example.com"}
    assert get_public_base_url(cfg) == "https://admin.example.com"


def test_setup_ui_contains_both_url_layers():
    p = ROOT / "templates/enterprise/admin_config.html"
    text = p.read_text(encoding="utf-8")
    assert "Deployment URL" in text
    assert "Admin URL Override" in text
    assert 'id="deploymentPublicUrl"' in text
    assert 'id="adminPublicUrlOverride"' in text
    assert 'readonly aria-readonly="true"' in text


def test_generic_system_grid_does_not_duplicate_deployment_url_field():
    p = ROOT / "templates/enterprise/admin_config.html"
    text = p.read_text(encoding="utf-8")
    assert "system: ['PUBLIC_BASE_URL_ADMIN_OVERRIDE','BASE_CAPITAL'" in text


def test_config_api_exposes_public_url_metadata():
    p = ROOT / "core/enterprise_dashboard/routes/admin.py"
    text = p.read_text(encoding="utf-8")
    assert '"deployment_url_editable": False' in text
    assert '"admin_override_configurable": True' in text
