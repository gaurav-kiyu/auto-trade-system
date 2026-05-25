"""
AD-KIYU Control Plane RBAC — wraps core.auth for admin control plane endpoints.

Provides a ControlRBAC facade that integrates RoleManager with the control plane's
HTTP layer, ensuring every control action is authorized before execution.
"""
from __future__ import annotations

import logging
from typing import Any

from core.auth.permissions import Permission, PermissionDenied, Role
from core.auth.role_manager import RoleManager

_log = logging.getLogger(__name__)


# ── Action-to-Permission mapping for control plane endpoints ───────────

_CONTROL_PERMISSIONS: dict[str, Permission] = {
    "view_state": Permission.VIEW_STATE,
    "halt_trading": Permission.HALT_TRADING,
    "modify_risk_limits": Permission.MODIFY_RISK_LIMITS,
    "toggle_strategies": Permission.TOGGLE_STRATEGIES,
    "deploy_models": Permission.DEPLOY_MODELS,
    "view_logs": Permission.VIEW_LOGS,
    "add_brokers": Permission.ADD_BROKERS,
    "modify_config": Permission.MODIFY_CONFIG,
}

# Endpoint → required permission mapping
_ENDPOINT_PERMISSIONS: dict[str, str] = {
    "control_state": "view_state",
    "control_audit": "view_state",
    "control_strategy_enable": "toggle_strategies",
    "control_strategy_disable": "toggle_strategies",
    "control_asset_enable": "toggle_strategies",
    "control_asset_disable": "toggle_strategies",
    "control_kill": "halt_trading",
    "control_capital": "modify_config",
    "control_risk_limit": "modify_risk_limits",
    "control_ai_model": "deploy_models",
    "control_feature_flag": "modify_config",
}


class ControlRBAC:
    """
    RBAC facade for the admin control plane.

    Integrates core.auth.role_manager.RoleManager with control plane endpoints
    to provide permission-checked access to all control actions.

    Each control action is mapped to a permission, and each identity has a role
    that grants a set of permissions.
    """

    def __init__(self, role_manager: RoleManager | None = None):
        self._role_manager = role_manager or RoleManager()

    @property
    def role_manager(self) -> RoleManager:
        return self._role_manager

    def check_endpoint(self, identity: str, endpoint_name: str) -> tuple[bool, str]:
        """
        Check whether an identity has permission to access a control endpoint.

        Args:
            identity: The operator identity (e.g. "alice")
            endpoint_name: The control endpoint name (e.g. "control_kill")

        Returns:
            (allowed: bool, reason: str)
        """
        permission_name = _ENDPOINT_PERMISSIONS.get(endpoint_name)
        if permission_name is None:
            # Unknown endpoint — deny by default
            return False, f"Unknown endpoint: {endpoint_name}"

        permission = _CONTROL_PERMISSIONS.get(permission_name)
        if permission is None:
            return False, f"Unknown permission: {permission_name}"

        try:
            self._role_manager.check(identity, permission)
            return True, ""
        except PermissionDenied as e:
            return False, str(e)

    def check_permission(self, identity: str, permission: Permission | str) -> tuple[bool, str]:
        """
        Check whether an identity has a specific permission.

        Args:
            identity: The operator identity
            permission: The required permission

        Returns:
            (allowed: bool, reason: str)
        """
        try:
            self._role_manager.check(identity, permission)
            return True, ""
        except PermissionDenied as e:
            return False, str(e)

    def require_endpoint(self, identity: str, endpoint_name: str) -> None:
        """
        Require permission for an endpoint. Raises PermissionDenied on failure.
        """
        allowed, reason = self.check_endpoint(identity, endpoint_name)
        if not allowed:
            raise PermissionDenied(reason)

    def require_permission(self, identity: str, permission: Permission | str) -> None:
        """
        Require a specific permission. Raises PermissionDenied on failure.
        """
        self._role_manager.check(identity, permission)

    def get_identity_role(self, identity: str) -> Role:
        """Get the role assigned to an identity."""
        return self._role_manager.get_role(identity)

    def list_assignments(self) -> dict[str, str]:
        """List all explicit role assignments."""
        return self._role_manager.list_assignments()

    def get_permissions_for_role(self, role: Role | str) -> list[str]:
        """Get all permission names for a role."""
        from core.auth.permissions import get_role_permissions
        perms = get_role_permissions(role)
        return sorted(p.value for p in perms)

    def has_permission(self, identity: str, permission: Permission | str) -> bool:
        """Check if an identity has a specific permission."""
        return self._role_manager.has_permission(identity, permission)

    def load_from_config(self, cfg: dict[str, Any]) -> None:
        """Load RBAC configuration from config dict."""
        self._role_manager.load_from_config(cfg)
