"""WIP52 global navigation regression boundaries."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_no_ui_javascript_navigation_to_localhost():
    offenders=[]
    for folder in ("templates","static"):
        root=ROOT/folder
        if not root.exists(): continue
        for p in root.rglob("*"):
            if p.suffix.lower() not in {".html",".js",".ts"}: continue
            for i,line in enumerate(p.read_text(encoding="utf-8",errors="ignore").splitlines(),1):
                if re.search(r"""(?:location\.(?:href|assign|replace)|window\.open)\s*\([^)]*(?:localhost|127\.0\.0\.1)""",line,re.I):
                    offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert not offenders, offenders


def test_canonical_url_builder_exists():
    p=ROOT/"core/notifications/url_resolver.py"
    text=p.read_text(encoding="utf-8")
    assert "def get_public_base_url" in text
    assert "def build_action_url" in text
