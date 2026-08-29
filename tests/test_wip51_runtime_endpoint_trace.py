"""WIP51 runtime endpoint regression guard."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_ui_has_no_explicit_loopback_origin():
    offenders=[]
    for folder in ("templates","static"):
        root=ROOT/folder
        if not root.exists(): continue
        for p in root.rglob("*"):
            if p.suffix.lower() not in {".html",".js",".ts",".css"}: continue
            for i,line in enumerate(p.read_text(encoding="utf-8",errors="ignore").splitlines(),1):
                if re.search(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?",line,re.I):
                    offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert not offenders, offenders
