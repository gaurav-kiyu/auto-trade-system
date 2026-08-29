"""WIP50 production UI origin regression tests."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_no_explicit_localhost_browser_urls_in_ui():
    offenders=[]
    for folder in ("templates","static"):
        root=ROOT/folder
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.suffix.lower() not in {".html",".js",".ts",".css"}:
                continue
            text=p.read_text(encoding="utf-8",errors="ignore")
            for i,line in enumerate(text.splitlines(),1):
                if re.search(
                    r"""https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?""",
                    line,re.I
                ):
                    offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert not offenders, offenders


def test_public_url_resolver_exists():
    p=ROOT/"core/notifications/url_resolver.py"
    text=p.read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "def build_action_url" in text


def test_admin_override_exists():
    text=(ROOT/"core/notifications/url_resolver.py").read_text(encoding="utf-8")
    assert "PUBLIC_BASE_URL_ADMIN_OVERRIDE" in text
