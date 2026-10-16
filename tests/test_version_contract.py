"""Authoritative Regression Suite for OPB Application Version Contract.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Scope: Single consistent version source of truth validation.
"""

from pathlib import Path
from unittest.mock import patch

from core.version import get_app_version, get_app_version_tag

_ROOT = Path(__file__).resolve().parent.parent


def test_01_version_file_loading():
    """Verify get_app_version reads canonical version from VERSION file."""
    version_file = _ROOT / "VERSION"
    assert version_file.is_file(), "Root VERSION file must exist"
    expected = version_file.read_text(encoding="utf-8").strip()
    assert expected == "2.61.3", "Canonical version must be 2.61.3"
    assert get_app_version() == "2.61.3"
    assert get_app_version_tag() == "v2.61.3"


def test_02_version_fallback_behavior():
    """Verify get_app_version falls back gracefully if VERSION file is missing or unreadable."""
    with patch("core.version._VERSION_FILE", _ROOT / "NON_EXISTENT_VERSION_FILE"):
        # When file does not exist, it should return fallback version
        fallback = get_app_version()
        assert fallback == "2.61.3"
        assert get_app_version_tag() == "v2.61.3"


def test_03_package_and_manifest_version_consistency():
    """Verify pyproject.toml, Dockerfile, docker-compose.yml all synchronize with VERSION."""
    canonical_ver = get_app_version()

    # pyproject.toml
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{canonical_ver}"' in pyproject

    # Dockerfile
    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f'LABEL version="{canonical_ver}"' in dockerfile

    # docker-compose.yml
    compose = (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert f'image: opb-bot:{canonical_ver}' in compose


def test_04_api_version_reporting():
    """Verify API state endpoint reports canonical version and tag."""
    from core.enterprise_dashboard.main import EnterpriseDashboard

    d = EnterpriseDashboard(config={"BASE_CAPITAL": 3000})
    st = d._read_state()
    assert st["version"] == get_app_version()
    assert st["release_tag"] == get_app_version_tag()


def test_05_ui_page_context_version_reporting():
    """Verify UI page template context injects canonical version and tag."""
    from core.enterprise_dashboard.routes.pages import _page_context

    ctx = _page_context(None, nonce="test-nonce", current_page="login")
    assert ctx["app_version"] == get_app_version()
    assert ctx["version"] == get_app_version()
    assert ctx["version_tag"] == get_app_version_tag()


def test_06_presentation_generator_version_reporting():
    """Verify presentation generator reports canonical version without hardcoding."""
    from core.presentation_generator import (
        PresentationConfig,
        PresentationGenerator,
    )

    gen = PresentationGenerator(PresentationConfig(enabled=False))
    assert gen._fetch_version() == get_app_version()
