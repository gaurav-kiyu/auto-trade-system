"""WIP45 SSO repair regression tests."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_public_url_resolver():
    text = (ROOT / "core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "def build_action_url" in text
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text


def test_sso_routes_preserve_callback_builder():
    text = (ROOT / "core/auth/routes.py").read_text(encoding="utf-8")
    assert "build_action_url" in text
    assert '"/api/auth/sso/callback"' in text


def test_no_direct_application_callback_base_url_concat():
    offenders = []
    for name in ("core/auth/sso.py", "core/auth/routes.py"):
        p = ROOT / name
        text = p.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(
                r"request\.base_url.*\+\s*['\"]/(?:api|auth|sso)",
                line,
                flags=re.I,
            ):
                offenders.append(f"{name}:{i}")
    assert not offenders, offenders
