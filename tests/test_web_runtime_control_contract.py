"""Static contract checks for enterprise interactive controls.

These checks are intentionally conservative: they catch broken event wiring and
dead element references without pretending to replace authenticated browser E2E.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates" / "enterprise"


def _html_ids(text: str) -> set[str]:
    return set(re.findall(r'\bid=["\']([^"\']+)["\']', text, re.I))


def test_event_listener_targets_exist_when_not_optional():
    missing = []
    for path in TEMPLATES.glob("*.html"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        ids = _html_ids(text)
        for m in re.finditer(
            r"getElementById\(['\"]([^'\"]+)['\"]\)(\??\.)addEventListener",
            text,
        ):
            target = m.group(1)
            optional = bool(m.group(2))
            if not optional and target not in ids:
                missing.append(f"{path.name}: {target}")
    assert not missing, "Missing non-optional event targets: " + ", ".join(missing)


def test_no_known_dead_cspfix_listener_targets():
    intelligence = (TEMPLATES / "intelligence.html").read_text(
        encoding="utf-8", errors="ignore"
    )
    assert "getElementById('cspfix-1')" not in intelligence
    assert 'getElementById("cspfix-1")' not in intelligence
