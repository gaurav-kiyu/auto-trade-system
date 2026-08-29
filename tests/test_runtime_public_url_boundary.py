"""Guardrails for the centralized public URL boundary."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = [ROOT / "core", ROOT / "index_app", ROOT / "infrastructure"]

PRODUCTION_HOST = "gaurav-cockpit.servegame.com"


def _runtime_text_files():
    for root in RUNTIME_DIRS:
        if not root.exists():
            continue
        yield from (p for p in root.rglob("*.py") if p.is_file())


def test_no_direct_production_host_in_runtime_python():
    offenders = []
    for p in _runtime_text_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        if PRODUCTION_HOST in text and "url_resolver.py" not in str(p):
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, f"Direct production host found in runtime code: {offenders}"


def test_public_url_resolver_is_the_canonical_boundary():
    p = ROOT / "core/notifications/url_resolver.py"
    text = p.read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text
