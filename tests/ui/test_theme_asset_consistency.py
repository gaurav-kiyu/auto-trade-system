"""Regression guards for the canonical theme presentation contract."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]

# The theme engine may support these existing IDs internally.
ENGINE_THEME_IDS = (
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

# Only these five themes are selectable from the user-facing navigation.
SELECTABLE_THEME_IDS = (
    "dark-cyber",
    "dracula-purple",
    "ivory-gold",
    "midnight-slate",
    "emerald-matrix",
)


def _theme_ids(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"'([a-z0-9-]+)':\s*\{\s*name:", text))


def _selector_theme_ids(text: str, selector_id: str) -> list[str]:
    match = re.search(
        rf'<select[^>]*id="{re.escape(selector_id)}"[^>]*>.*?</select>',
        text,
        flags=re.DOTALL,
    )
    assert match is not None, f"{selector_id} selector not found"

    return re.findall(r'value="([^"]+)"', match.group(0))


def test_canonical_theme_engine_has_all_supported_themes() -> None:
    expected = set(ENGINE_THEME_IDS)
    assert _theme_ids(ROOT / "static/theme_engine.js") == expected


def test_legacy_theme_asset_does_not_drift_from_canonical_engine() -> None:
    expected = set(ENGINE_THEME_IDS)
    assert _theme_ids(ROOT / "core/static/theme_engine.js") == expected


def test_desktop_and_mobile_selectors_expose_exact_five_themes() -> None:
    text = (ROOT / "templates/enterprise/_nav.html").read_text(
        encoding="utf-8"
    )

    expected = list(SELECTABLE_THEME_IDS)

    assert _selector_theme_ids(text, "desktopThemeSelect") == expected
    assert _selector_theme_ids(text, "drawerThemeSelect") == expected


def test_theme_engine_assets_are_byte_identical() -> None:
    assert (
        ROOT / "static/theme_engine.js"
    ).read_bytes() == (
        ROOT / "core/static/theme_engine.js"
    ).read_bytes()
