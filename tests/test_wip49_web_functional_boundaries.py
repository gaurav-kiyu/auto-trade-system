"""WIP49 Web functional boundary regression tests."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_no_localhost_in_ui_templates_or_static():
    offenders = []
    for folder in ("templates", "static"):
        root = ROOT / folder
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.suffix.lower() not in {".html", ".js", ".ts", ".css"}:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(text.splitlines(), 1):
                if re.search(r'''https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?(?:[/\s'"`]|$)''', line, re.I):
                    offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert not offenders, offenders


def test_canonical_public_url_builder_exists():
    p = ROOT / "core/notifications/url_resolver.py"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "def build_action_url" in text


def test_admin_setup_url_fields_exist():
    p = ROOT / "templates/enterprise/admin_config.html"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    for field in ("deploymentPublicUrl", "adminPublicUrlOverride", "effectivePublicUrl"):
        assert f'id="{field}"' in text
