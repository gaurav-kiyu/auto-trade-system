"""
Web Closure Contract Tests (WIP14).

Static guardrails for the production Web UI. These tests intentionally avoid
network/browser assumptions and catch common regressions before deployment.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates" / "enterprise"


def _templates():
    return list(TEMPLATES.glob("*.html"))


def _routes():
    routes = set()
    for f in ROOT.rglob("*.py"):
        text = f.read_text(errors="ignore")
        routes.update(
            m.group(1)
            for m in re.finditer(
                r'@\w+\.(?:get|post|put|patch|delete)\(\s*[\'"]([^\'"]+)',
                text,
            )
        )
    return routes


def _route_matches(path, routes):
    path = path.split("?", 1)[0].split("#", 1)[0]
    if path in routes:
        return True
    for route in routes:
        pattern = re.sub(r"\{[^}]+\}", r"[^/]+", route)
        if re.fullmatch(pattern, path):
            return True
    return False


def test_enterprise_templates_have_no_inline_event_handlers():
    bad = []
    for f in _templates():
        text = f.read_text(errors="ignore")
        # Restrict the check to HTML attributes, not JavaScript strings/selectors.
        if re.search(
            r"<(?:button|a|form|input|select|textarea|div|span)\b[^>]*\b(?:onclick|ondblclick|onchange|onsubmit|oninput|onkeyup|onkeydown|onload)\s*=",
            text,
            re.I | re.S,
        ):
            bad.append(f.name)
    assert not bad, f"Inline event handlers found: {bad}"


def test_enterprise_templates_have_no_localhost_urls():
    bad = []
    for f in _templates():
        if "localhost:8000" in f.read_text(errors="ignore"):
            bad.append(f.name)
    assert not bad, f"Hard-coded localhost URL found: {bad}"


def test_internal_enterprise_links_resolve_to_application_routes():
    routes = _routes()
    bad = []
    for f in _templates():
        text = f.read_text(errors="ignore")
        for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', text):
            href = m.group(1)
            if not href.startswith("/") or href.startswith("//") or href.startswith("/static/"):
                continue
            if not _route_matches(href, routes):
                bad.append((f.name, href))
    assert not bad, f"Unresolved internal links: {bad}"


def test_enterprise_templates_have_no_placeholder_hash_links():
    bad = []
    for f in _templates():
        if re.search(r'href\s*=\s*["\']#["\']', f.read_text(errors="ignore")):
            bad.append(f.name)
    assert not bad, f"Placeholder href='#' links found: {bad}"
