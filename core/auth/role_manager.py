"""
AD-KIYU RBAC — Role Manager.

Manages role assignments per operator identity and provides
role-checking for the admin control plane endpoints.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from core.auth.permissions import Permission, PermissionDenied, Role, role_has_permission

_log = logging.getLogger(__name__)


class RoleManager:
    """Thread-safe role assignment store.

    Maps operator identity → Role.
    Default role for unknown identities is OBSERVER.
    """

    def __init__(self, default_role: Role | str = Role.OBSERVER):
        self._lock = threading.Lock()
        self._roles: dict[str, Role] = {}
        if isinstance(default_role, str):
            default_role = Role(default_role.lower())
        self._default_role = default_role

    def assign(self, identity: str, role: Role | str) -> None:
        """Assign a role to an operator identity."""
        if isinstance(role, str):
            role = Role(role.lower())
        with self._lock:
            self._roles[identity] = role
        _log.info(f"[RBAC] Assigned {role.value} to {identity!r}")

    def revoke(self, identity: str) -> None:
        """Revoke explicit role assignment (falls back to default)."""
        with self._lock:
            self._roles.pop(identity, None)
        _log.info(f"[RBAC] Revoked role for {identity!r}")

    def get_role(self, identity: str) -> Role:
        """Get the role for an identity."""
        with self._lock:
            return self._roles.get(identity, self._default_role)

    def check(self, identity: str, permission: Permission | str) -> None:
        """Check permission for identity. Raises PermissionDenied on failure."""
        role = self.get_role(identity)
        if not role_has_permission(role, permission):
            raise PermissionDenied(
                f"Role {role.value} for {identity!r} lacks permission {permission}"
            )

    def has_permission(self, identity: str, permission: Permission | str) -> bool:
        """Return True if identity's role has the permission."""
        try:
            self.check(identity, permission)
            return True
        except PermissionDenied:
            return False

    def list_assignments(self) -> dict[str, str]:
        """Return all explicit role assignments (identity → role name)."""
        with self._lock:
            return {k: v.value for k, v in sorted(self._roles.items())}

    def load_from_config(self, cfg: dict[str, Any]) -> None:
        """Load role assignments from config dict.

        Expected format::
            {
                "admin_roles": {"alice": "admin", "bob": "operator"},
                "admin_default_role": "observer",
            }
        """
        roles_cfg = cfg.get("admin_roles") or {}
        for identity, role_name in roles_cfg.items():
            try:
                role = Role(role_name.lower())
                self.assign(str(identity), role)
            except ValueError:
                _log.warning(f"[RBAC] Unknown role {role_name!r} for {identity!r} — skipped")
        default = cfg.get("admin_default_role", "observer")
        try:
            self._default_role = Role(default.lower())
        except ValueError:
            _log.warning(f"[RBAC] Unknown default_role {default!r} — keeping {self._default_role.value}")
