"""Regression guards for canonical web interaction wiring."""
from pathlib import Path
import re

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
