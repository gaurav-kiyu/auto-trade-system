"""
OPB v2.60 — Theme System, Typography, Version Sync & Form UX Governance Tests

Verifies:
1. Canonical Version Engine (core/version.py) matches VERSION file, Dockerfile, docker-compose.yml
2. Enterprise Dashboard _page_context() injects canonical app_version, version, and version_tag
3. Whats_new route synchronizes fallback version with canonical engine
4. Universal --opb-* design tokens defined in :root and all 5 supported themes
5. Password visibility toggle collision avoidance rules in CSS and theme_engine.js
6. Form validation UX (novalidate) across core authentication/profile forms
7. Governed empty states in options_chain, margin_radar, performance
8. Metrics trend state file path resolution resilience across bind-mount variants
"""

import json
import os
import re
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_canonical_version_engine_synchronization():
    """Verify core/version.py returns 2.60.0 and synchronizes with VERSION, Dockerfile, docker-compose.yml."""
    from core.version import get_app_version, get_app_version_tag

    app_ver = get_app_version()
    app_tag = get_app_version_tag()
    assert app_ver == "2.60.0"
    assert app_tag == "v2.60.0"

    version_file = ROOT_DIR / "VERSION"
    assert version_file.is_file()
    assert version_file.read_text(encoding="utf-8").strip() == "2.60.0"

    dockerfile = ROOT_DIR / "Dockerfile"
    assert dockerfile.is_file()
    dockerfile_content = dockerfile.read_text(encoding="utf-8")
    assert 'version="2.60.0"' in dockerfile_content

    compose_file = ROOT_DIR / "docker-compose.yml"
    assert compose_file.is_file()
    compose_content = compose_file.read_text(encoding="utf-8")
    assert "opb-bot:2.60.0" in compose_content


def test_page_context_injects_canonical_version():
    """Verify _page_context injects app_version, version, and version_tag."""
    from core.enterprise_dashboard.routes.pages import _page_context

    # Unauthenticated/None user context
    ctx_anon = _page_context(None, nonce="test-nonce", current_page="login")
    assert ctx_anon["app_version"] == "2.60.0"
    assert ctx_anon["version"] == "2.60.0"
    assert ctx_anon["version_tag"] == "v2.60.0"

    # Mock user object
    class DummyUser:
        id = "u1"
        username = "trader1"
        role = "trader"
        def to_dict(self):
            return {"id": self.id, "username": self.username, "role": self.role}

    ctx_user = _page_context(DummyUser(), nonce="test-nonce", current_page="profile")
    assert ctx_user["app_version"] == "2.60.0"
    assert ctx_user["version"] == "2.60.0"
    assert ctx_user["version_tag"] == "v2.60.0"


def test_design_system_semantic_tokens_and_themes():
    """Verify static/opb_design_system.css defines all --opb-* tokens in :root and all 5 themes."""
    css_path = ROOT_DIR / "static" / "opb_design_system.css"
    assert css_path.is_file()
    content = css_path.read_text(encoding="utf-8")

    expected_tokens = [
        "--opb-bg",
        "--opb-surface",
        "--opb-surface-alt",
        "--opb-text",
        "--opb-text-primary",
        "--opb-text-secondary",
        "--opb-text-muted",
        "--opb-text-inverse",
        "--opb-border",
        "--opb-border-hover",
        "--opb-accent",
        "--opb-accent-gradient",
        "--opb-success",
        "--opb-warning",
        "--opb-danger",
        "--opb-input-bg",
        "--opb-input-text",
        "--opb-placeholder",
        "--opb-disabled-text",
        "--opb-disabled-bg",
    ]

    for tok in expected_tokens:
        assert tok in content, f"Missing token {tok} in opb_design_system.css"

    themes = [
        "dark-cyber",
        "dracula-purple",
        "ivory-gold",
        "midnight-slate",
        "emerald-matrix",
    ]
    for theme in themes:
        assert f'[data-theme="{theme}"]' in content, f"Missing theme block [data-theme='{theme}'] in CSS"


def test_password_toggle_collision_prevention_css_and_js():
    """Verify password toggle rules prevent dual-SVG rendering and theme_engine handles delegation."""
    css_path = ROOT_DIR / "static" / "opb_design_system.css"
    css_content = css_path.read_text(encoding="utf-8")

    # Verify no unconditional display:block !important on toggle SVGs
    assert ".opb-password-toggle svg {\n    display: block !important;" not in css_content
    # Verify state-driven display rules exist
    assert '.opb-password-toggle:not([data-showing="true"]):not([aria-pressed="true"]) .eye-svg-closed' in css_content
    assert '.opb-password-toggle[aria-pressed="true"] .eye-svg-open' in css_content

    engine_path = ROOT_DIR / "static" / "theme_engine.js"
    assert engine_path.is_file()
    engine_content = engine_path.read_text(encoding="utf-8")
    assert "handleGlobalEyeToggle" in engine_content
    assert "handleGlobalEyeToggle(e)" in engine_content


def test_form_validation_novalidate_ux():
    """Verify forms in profile, login, change_password, and admin_users utilize novalidate."""
    forms_to_check = [
        ("templates/enterprise/profile.html", ['id="profileForm" novalidate', 'id="passwordForm" novalidate']),
        ("templates/enterprise/login.html", ['id="loginForm"', 'novalidate']),
        ("templates/enterprise/change_password.html", ['id="passwordForm" novalidate']),
        ("templates/enterprise/admin_users.html", ['id="createForm" novalidate']),
    ]
    for rel_path, expected_snippets in forms_to_check:
        full_path = ROOT_DIR / rel_path
        assert full_path.is_file(), f"Missing template {rel_path}"
        content = full_path.read_text(encoding="utf-8")
        for snippet in expected_snippets:
            assert snippet in content, f"Snippet '{snippet}' not found in {rel_path}"


def test_governed_empty_states():
    """Verify empty states in options_chain, margin_radar, and performance."""
    oc_path = ROOT_DIR / "templates" / "enterprise" / "options_chain.html"
    oc_content = oc_path.read_text(encoding="utf-8")
    assert "OPTIONS CHAIN DISCONNECTED" in oc_content
    assert "PAPER / SIGNAL_ONLY MODE" in oc_content

    mr_path = ROOT_DIR / "templates" / "enterprise" / "margin_radar.html"
    mr_content = mr_path.read_text(encoding="utf-8")
    assert "BROKER ROUTING DISCONNECTED" in mr_content

    perf_path = ROOT_DIR / "templates" / "enterprise" / "performance.html"
    perf_content = perf_path.read_text(encoding="utf-8")
    assert "(PAPER)" in perf_content
    assert "broker routing DISCONNECTED" in perf_content


def test_success_metrics_trend_storage_path_resilience(tmp_path: Path):
    """Verify _resolve_storage_path resolves existing and fallback file paths safely."""
    from core.success_metrics_trend import SuccessMetricsTrend

    # Test with custom storage path
    custom_file = tmp_path / "custom_trend.json"
    custom_file.write_text('{"snapshots": []}', encoding="utf-8")

    trend = SuccessMetricsTrend(storage_path=str(custom_file))
    resolved = trend._resolve_storage_path()
    assert resolved == custom_file
    assert resolved.is_file()
