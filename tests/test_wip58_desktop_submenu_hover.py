"""WIP58 regression test for desktop submenu pointer continuity."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_dropdown_has_pointer_bridge_and_delayed_hide():
    text = (ROOT / "templates/enterprise/_nav.html").read_text(encoding="utf-8")
    assert ".opb-ws-dropdown::before" in text
    assert "height: 14px" in text
    assert "visibility 0s linear 0.30s" in text
    assert ".opb-ws-group:hover .opb-ws-dropdown" in text
    assert "pointer-events: auto" in text


def test_user_controls_is_canonical_admin_submenu_only():
    text = (ROOT / "templates/enterprise/_nav.html").read_text(encoding="utf-8")
    assert text.count('href="/admin/users"') == 2  # desktop + mobile representations
    assert "User Authorization & Controls" in text
    assert "User Authorization & Access" in text
