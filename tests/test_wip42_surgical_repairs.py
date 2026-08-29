"""WIP42 regression tests for surgical public URL repairs."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_url_builder():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "def build_action_url" in text
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text


def test_sso_remains_canonical():
    text = (ROOT / "core/auth/routes.py").read_text(encoding="utf-8")
    assert "build_action_url" in text
    assert '"/api/auth/sso/callback"' in text


def test_no_direct_request_base_url_concatenation():
    offenders = []
    for root_name in ("core", "index_app", "infrastructure"):
        root = ROOT / root_name
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(text.splitlines(), 1):
                if re.search(r"request\.base_url\.rstrip\([^)]*\)\s*\+", line):
                    offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert not offenders, offenders


def test_setup_url_layers():
    text = (ROOT / "templates/enterprise/admin_config.html").read_text(encoding="utf-8")
    for field in ("deploymentPublicUrl", "adminPublicUrlOverride", "effectivePublicUrl"):
        assert f'id="{field}"' in text
