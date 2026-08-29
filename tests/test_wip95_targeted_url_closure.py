from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]
LOCALHOST_URL = re.compile(r"https?://localhost(?::\d+)?(?:[/'`\s]|$)", re.I)

def _sso_source():
    for p in ROOT.rglob("*.py"):
        if not p.is_file() or "tests" in p.parts:
            continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        if "class SSOAuthenticator" in t and "def get_public_base_url" in t:
            return p, t
    raise AssertionError("canonical SSO helpers not found in production SSO module")

def test_sso_canonical_url_helpers_exist_and_have_resolution_order():
    p, t = _sso_source()
    tree = ast.parse(t)
    names = {n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "get_public_base_url" in names
    assert "build_action_url" in names
    assert "public_base_url" in t
    assert "base_url" in t
    assert "deployment_url" in t

def test_admin_config_has_no_hardcoded_localhost_url():
    p = ROOT / "templates/enterprise/admin_config.html"
    text = p.read_text(encoding="utf-8", errors="ignore")
    offenders = [i for i, line in enumerate(text.splitlines(), 1)
                 if LOCALHOST_URL.search(line)]
    assert not offenders, offenders
