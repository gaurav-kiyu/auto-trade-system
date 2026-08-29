"""AD-KIYU RBAC - Role-Based Access Control for admin control plane.

Permission matrix:
| Action            | ADMIN | OPERATOR | OBSERVER | DEVELOPER |
|-------------------|-------|----------|----------|-----------|
| View state        | ✓     | ✓        | ✓        | ✓         |
| Halt trading      | ✓     | ✓        |          |           |
| Modify risk limits| ✓     |          |          |           |
| Toggle strategies | ✓     | ✓        |          | ✓         |
| Deploy models     | ✓     |          |          | ✓         |
| Modify code       | ✓     |          |          | ✓         |
| View logs         | ✓     | ✓        | ✓        | ✓         |
| Add brokers       | ✓     |          |          |           |
| Modify config     | ✓     |          |          | ✓         |
"""

from __future__ import annotations

import enum


class Role(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    OBSERVER = "observer"
    DEVELOPER = "developer"


class Permission(str, enum.Enum):
    VIEW_STATE = "view_state"
    HALT_TRADING = "halt_trading"
    MODIFY_RISK_LIMITS = "modify_risk_limits"
    TOGGLE_STRATEGIES = "toggle_strategies"
    DEPLOY_MODELS = "deploy_models"
    MODIFY_CODE = "modify_code"
    VIEW_LOGS = "view_logs"
    ADD_BROKERS = "add_brokers"
    MODIFY_CONFIG = "modify_config"
    MANAGE_USERS = "manage_users"
    MANAGE_PERMISSIONS = "manage_permissions"


_PERMISSION_MATRIX: dict[Role, set[Permission]] = {
    # Super Admin is the root control-plane role. It inherits every defined RBAC permission.
    Role.SUPER_ADMIN: set(Permission),
    Role.ADMIN: {
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
    },
    Role.OPERATOR: {
        Permission.VIEW_STATE,
        Permission.HALT_TRADING,
        Permission.TOGGLE_STRATEGIES,
        Permission.VIEW_LOGS,
    },
    Role.VIEWER: {
        Permission.VIEW_STATE,
        Permission.VIEW_LOGS,
    },
    Role.OBSERVER: {
        Permission.VIEW_STATE,
        Permission.VIEW_LOGS,
    },
    Role.DEVELOPER: {
        Permission.VIEW_STATE,
        Permission.TOGGLE_STRATEGIES,
        Permission.DEPLOY_MODELS,
        Permission.MODIFY_CODE,
        Permission.VIEW_LOGS,
        Permission.MODIFY_CONFIG,
    },
}


def role_has_permission(role: Role | str, permission: Permission | str) -> bool:
    """Check whether a role has a given permission."""
    if isinstance(role, str):
        try:
            role = Role(role.lower())
        except ValueError:
            return False
    if isinstance(permission, str):
        try:
            permission = Permission(permission.lower())
        except ValueError:
            return False
    return permission in _PERMISSION_MATRIX.get(role, set())


def get_role_permissions(role: Role | str) -> set[Permission]:
    """Get all permissions for a role."""
    if isinstance(role, str):
        try:
            role = Role(role.lower())
        except ValueError:
            return set()
    return _PERMISSION_MATRIX.get(role, set()).copy()


def is_super_admin_identity(username: str, role: Role | str) -> bool:
    """Return whether an authenticated identity is the immutable root administrator.

    ``admin`` is retained as the legacy root account alias for backward compatibility
    with the existing production deployment; new root accounts use ``super_admin``.
    """
    return str(username or '').strip().lower() == 'admin' or str(role or '').lower() == Role.SUPER_ADMIN.value


class PermissionDenied(Exception):
    """Raised when a role lacks permission for a requested action."""


__all__ = [
    "Permission",
    "PermissionDenied",
    "Role",
    "get_role_permissions",
    "role_has_permission",
    "is_super_admin_identity",
]
