from pathlib import Path
import ast
import re


ROOT = Path(__file__).resolve().parents[1]
NAV = ROOT / "templates" / "enterprise" / "_nav.html"
PAGES = ROOT / "core" / "enterprise_dashboard" / "routes" / "pages.py"
PERMISSIONS = ROOT / "core" / "auth" / "permissions.py"


def _text(path):
    return path.read_text(encoding="utf-8")


def _nav_hrefs():
    return set(re.findall(r'href=["' + "'" + r']([^"' + "'" + r']+)["' + "'" + r']', _text(NAV)))


def _nav_permission_flags():
    text = _text(NAV)
    return set(re.findall(r'\b(can_[A-Za-z0-9_]+)\b', text))


def _page_context_function():
    tree = ast.parse(_text(PAGES))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_page_context":
            return node
    raise AssertionError("_page_context not found")


def _function_source(node):
    lines = _text(PAGES).splitlines()
    return "\n".join(lines[node.lineno - 1: node.end_lineno])


def test_all_navigation_permission_flags_remain_available():
    nav_flags = _nav_permission_flags()
    assert nav_flags, "no can_* navigation flags found"

    source = _function_source(_page_context_function())
    missing_nav_flags = sorted(flag for flag in nav_flags if flag not in source)
    assert not missing_nav_flags, (
        f"navigation permission gates missing from _page_context: {missing_nav_flags}"
    )


def test_superadmin_context_uses_canonical_identity_and_matrix():
    source = _function_source(_page_context_function())
    assert "is_super_admin_identity(username, role)" in source
    assert 'get_role_permissions("super_admin")' in source
    assert "if is_super_admin_identity(username, role):" in source


def test_superadmin_matrix_is_root_and_navigation_flags_have_canonical_backing():
    permissions_text = _text(PERMISSIONS)
    page_source = _function_source(_page_context_function())
    nav_text = _text(NAV)

    # Canonical RBAC contract: Super Admin receives every defined Permission.
    assert "Role.SUPER_ADMIN: set(Permission)" in permissions_text

    # Verify every permission flag actually used by the navigation has a
    # corresponding _page_context assignment. Do not infer enum names from
    # template variable names (e.g. can_manage_brokers may be backed by
    # Permission.ADD_BROKERS in the canonical implementation).
    nav_flags = _nav_permission_flags()
    assignments = set(re.findall(r'"(can_[A-Za-z0-9_]+)"\s*:', page_source))
    missing_assignments = sorted(nav_flags - assignments)
    assert not missing_assignments, (
        f"navigation permission flags lack _page_context assignments: {missing_assignments}"
    )

    # Explicitly verify the special broker navigation flag is present and used.
    assert "can_manage_brokers" in nav_flags
    assert "can_manage_brokers" in page_source
    assert "can_manage_brokers" in nav_text


def test_all_existing_navigation_routes_are_preserved():
    expected = {
        "/admin/users",
        "/admin/config",
        "/admin/signals",
        "/admin/portfolio-analyzer",
        "/governance",
        "/security",
        "/observability",
        "/system-health",
        "/data-quality",
        "/capacity",
        "/event-store",
        "/ab-tester",
        "/pricing-plans",
        "/whats-new",
        "/intelligence/presentation",
        "/admin/kill-switch",
    }
    hrefs = _nav_hrefs()
    missing = sorted(expected - hrefs)
    assert not missing, f"implemented Admin/Governance routes missing from navigation: {missing}"


def test_admin_users_has_desktop_and_mobile_representations():
    text = _text(NAV)
    assert text.count("/admin/users") >= 2