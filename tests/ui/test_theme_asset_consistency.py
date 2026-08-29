"""Regression guards for the canonical 9-theme presentation contract."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
THEME_IDS = (
    "dark-cyber",
    "nordic-frost",
    "ivory-gold",
    "tokyo-night",
    "catppuccin-mocha",
    "obsidian-gold",
    "midnight-slate",
    "emerald-matrix",
    "dracula-purple",
)


def _theme_ids(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"'([a-z0-9-]+)':\s*\{\s*name:", text))


def test_canonical_theme_engine_has_all_nine_themes() -> None:
    expected = set(THEME_IDS)
    assert _theme_ids(ROOT / "static/theme_engine.js") == expected


def test_legacy_theme_asset_does_not_drift_from_canonical_engine() -> None:
    expected = set(THEME_IDS)
    assert _theme_ids(ROOT / "core/static/theme_engine.js") == expected


def test_mobile_drawer_exposes_all_nine_themes() -> None:
    text = (ROOT / "templates/enterprise/_nav.html").read_text(encoding="utf-8")
    for theme_id in THEME_IDS:
        assert f'value="{theme_id}"' in text


def test_theme_engine_assets_are_byte_identical() -> None:
    assert (ROOT / "static/theme_engine.js").read_bytes() == (ROOT / "core/static/theme_engine.js").read_bytes()
