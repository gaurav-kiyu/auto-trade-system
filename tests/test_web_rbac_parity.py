"""Web RBAC parity guards for the enterprise dashboard.

These tests are intentionally source-level regression guards: the Web UI must not
silently fall back to broad admin-role checks after a granular permission is
introduced.  They complement endpoint-level auth tests.
"""
from __future__ import annotations

import ast
from pathlib import Path


def test_admin_route_module_has_no_broad_admin_dependency() -> None:
    source = Path("core/enterprise_dashboard/routes/admin.py").read_text(encoding="utf-8")
    assert "Depends(admin_only)" not in source
    assert "Depends(operator_or_admin)" not in source


def test_all_web_permission_dependencies_use_declared_permissions() -> None:
    from core.auth.permissions import Permission

    allowed = {p.value for p in Permission}
    paths = [
        Path("core/enterprise_dashboard/routes/admin.py"),
        Path("core/enterprise_dashboard/routes/pages.py"),
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "require_permission"):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            permission = node.args[0].value
            assert permission in allowed, f"Unknown permission {permission!r} in {path}"


def test_admin_role_still_has_all_operational_admin_permissions() -> None:
    from core.auth.permissions import Permission, Role, role_has_permission

    required = {
        Permission.VIEW_STATE,
        Permission.HALT_TRADING,
        Permission.MODIFY_RISK_LIMITS,
        Permission.TOGGLE_STRATEGIES,
        Permission.DEPLOY_MODELS,
        Permission.MODIFY_CODE,
        Permission.VIEW_LOGS,
        Permission.ADD_BROKERS,
        Permission.MODIFY_CONFIG,
        Permission.MANAGE_USERS,
    }
    assert all(role_has_permission(Role.ADMIN, p) for p in required)
    assert not role_has_permission(Role.ADMIN, Permission.MANAGE_PERMISSIONS)
