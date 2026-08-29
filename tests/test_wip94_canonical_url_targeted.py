from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]

def test_sso_canonical_url_helpers():
    matches=[]
    for p in ROOT.rglob("*sso*.py"):
        if p.is_file():
            t=p.read_text(encoding="utf-8",errors="ignore")
            if "def get_public_base_url" in t and "def build_action_url" in t:
                matches.append(p)
    assert matches

def test_admin_config_has_no_localhost():
    p=ROOT/"templates/enterprise/admin_config.html"
    assert p.exists()
    offenders=[]
    for i,line in enumerate(p.read_text(encoding="utf-8",errors="ignore").splitlines(),1):
        if re.search(r'''https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?(?:[/\s'"`]|$)''', line, re.I):
            offenders.append(i)
    assert not offenders, offenders
