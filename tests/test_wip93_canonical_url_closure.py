from pathlib import Path
import re
import importlib.util

ROOT=Path(__file__).resolve().parents[1]

def test_sso_exposes_canonical_url_boundary():
    matches=[]
    for p in ROOT.rglob("*sso*.py"):
        if "get_public_base_url" in p.read_text(encoding="utf-8",errors="ignore") or "build_action_url" in p.read_text(encoding="utf-8",errors="ignore"):
            matches.append(p)
    assert matches

def test_admin_template_has_no_hardcoded_localhost():
    p=ROOT/"templates/enterprise/admin_config.html"
    text=p.read_text(encoding="utf-8",errors="ignore")
    assert not re.search(r'''https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?(?:[/\s'"`]|$)''', text, re.I)

def test_wip90_requirements_remain():
    t=(ROOT/"WEB_CLOSURE_WIP90_FINAL_STATIC_CLOSURE_MATRIX.md").read_text(encoding="utf-8")
    assert "Deployment URL, Admin URL override and Base/Public URL" in t
    assert "Every durable state change must produce exactly one authoritative server-side audit event." in t
