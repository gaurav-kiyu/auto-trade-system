"""Regression guards for canonical web interaction wiring."""
import re
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]


def _html(path: Path):
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def test_theme_engine_is_loaded_at_most_once_per_template() -> None:
    pattern = re.compile(r"<script[^>]+src=[\"']/static/theme_engine\.js(?:\?[^\"']*)?[\"']")
    for path in (ROOT / "templates").rglob("*.html"):
        count = len(pattern.findall(path.read_text(encoding="utf-8")))
        assert count <= 1, f"duplicate theme_engine.js load: {path} ({count})"


def test_password_inputs_have_one_canonical_eye_control() -> None:
    for path in (ROOT / "templates").rglob("*.html"):
        soup = _html(path)
        for inp in soup.select('input[type="password"]'):
            wrapper = inp.find_parent(class_=lambda c: c and "opb-password-wrapper" in c.split())
            if wrapper is None:
                wrapper = inp.parent
            controls = wrapper.select('.opb-password-toggle, [data-toggle="password"], [data-toggle-password], .password-toggle-btn')
            assert len(controls) == 1, f"expected one eye control in {path}: found {len(controls)}"


def test_theme_engine_fallback_is_byte_identical_to_canonical_asset() -> None:
    assert (ROOT / "static/theme_engine.js").read_bytes() == (ROOT / "core/static/theme_engine.js").read_bytes()


def test_theme_engine_has_no_duplicate_eye_click_listeners() -> None:
    """Verify theme_engine.js delegates eye toggles through handleGlobalEyeToggle without duplicate listeners."""
    content = (ROOT / "static/theme_engine.js").read_text(encoding="utf-8")

    # 1. Exactly one handleGlobalEyeToggle declaration and exactly one invocation
    assert content.count("function handleGlobalEyeToggle(e)") == 1
    assert content.count("handleGlobalEyeToggle(e);") == 1
    # 2. No duplicate document.addEventListener('click') calling togglePasswordField directly
    assert "document.addEventListener('click', function(e) {\n        const btn = e.target.closest('.opb-password-toggle" not in content
    # 3. Canonical exports present
    assert "window.togglePasswordField = togglePasswordField;" in content
    assert "window.togglePasswordVisibility = function" in content


def test_profile_template_has_no_page_level_redundant_toggle_binding() -> None:
    """OPB UI Golden Rule: profile.html must rely on universal theme_engine without page-level click handlers."""
    profile_content = (ROOT / "templates/enterprise/profile.html").read_text(encoding="utf-8")
    assert "button.dataset.opbToggleBound" not in profile_content
    assert "document.querySelectorAll('.opb-password-toggle').forEach" not in profile_content
