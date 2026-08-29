"""Web navigation contract regression tests.

These tests guard against a recurring class of production UI defects: links that
render correctly but point to routes that do not exist, or accidental development
URLs leaking into enterprise templates.
"""
from __future__ import annotations

import glob
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates" / "enterprise"


def _declared_routes() -> set[str]:
    routes: set[str] = set()
    for path in ROOT.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in re.finditer(r"@(?:app|router)\.(?:get|post|put|delete|patch)\(\s*['\"]([^'\"]+)", text):
            routes.add(match.group(1))
    return routes


def test_enterprise_internal_href_targets_are_declared_routes_or_anchors():
    routes = _declared_routes()
    missing: list[str] = []
    for path in TEMPLATES.rglob("*.html"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"href=[\"']([^\"']+)[\"']", text):
            href = match.group(1)
            if not href.startswith("/") or href.startswith("//") or href.startswith("/static/"):
                continue
            route = href.split("#", 1)[0].split("?", 1)[0]
            if not route or route in routes:
                continue
            missing.append(f"{path.relative_to(ROOT)} -> {href}")
    assert not missing, "Broken internal navigation targets:\n" + "\n".join(sorted(set(missing)))


def test_enterprise_templates_contain_no_localhost_action_links():
    offenders: list[str] = []
    for path in TEMPLATES.rglob("*.html"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "localhost:8000" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, "Development localhost URLs leaked into enterprise templates: " + ", ".join(offenders)


def test_enterprise_templates_contain_no_inline_event_handlers():
    offenders: list[str] = []
    pattern = re.compile(r"\s(onclick|onchange|onsubmit|oninput|onkeyup|onkeydown|onmouseover|onmouseout)\s*=", re.I)
    for path in TEMPLATES.rglob("*.html"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, "Inline event handlers remain: " + ", ".join(offenders)
