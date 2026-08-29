"""AD-KIYU Auth Dependencies - FastAPI dependency injection for auth + RBAC.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from fastapi import Depends, HTTPException, Request
except ImportError:
    def Depends(dependency: Any = None) -> Any: return dependency  # type: ignore
    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int = 500, detail: str = "") -> None:
            self.status_code = status_code
            self.detail = detail
            super().__init__(f"[{status_code}] {detail}")
    class Request:  # type: ignore
        pass


from core.auth.handler import AuthHandler, AuthUser
from core.auth.mfa import get_mfa_session_state
from core.auth.permissions import is_super_admin_identity, role_has_permission
from core.auth.role_manager import RoleManager

_log = logging.getLogger(__name__)


class AuthDependencies:
    """Factory for FastAPI auth dependencies.

    Usage::

        auth = AuthDependencies(auth_handler, role_manager)

        @app.get("/protected")
        async def protected(user: AuthUser = Depends(auth.require_auth)):
            ...

        @app.get("/admin-only")
        async def admin(user: AuthUser = Depends(auth.require_role("admin"))):
            ...
    """

    def __init__(
        self,
        auth_handler: AuthHandler,
        role_manager: RoleManager | None = None,
    ):
        self._auth = auth_handler
        self._role_manager = role_manager or RoleManager()

    # ── Dependency callables ──────────────────────────────────────────────────

    async def require_auth(self, request: Request) -> AuthUser:
        """Require a valid authentication session.

        Checks session cookie first, then Authorization header.
        """
        token_str = ""

        # Check session cookie
        session_token = request.cookies.get("opb_session", "")
        if session_token:
            token_str = session_token

        # Fall back to Authorization header
        if not token_str:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token_str = auth_header[7:]

        if not token_str:
            raise HTTPException(status_code=401, detail="Authentication required")

        token = self._auth.verify_session(token_str)
        if token is None:
            raise HTTPException(status_code=401, detail="Session expired or invalid")

        user = self._auth.get_user_by_id(token.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")

        if user.disabled:
            raise HTTPException(status_code=403, detail="Account disabled")

        # Store in request state for other dependencies
        request.state.user = user
        request.state.token = token
        request.state.session_id = token.token

        return user

    async def require_auth_optional(self, request: Request) -> AuthUser | None:
        """Optionally authenticate - returns None if no valid session."""
        try:
            return await self.require_auth(request)
        except HTTPException:
            return None

    def require_role(self, *roles: str) -> Any:
        """Return a dependency that requires one of the specified roles."""
        allowed = set(r.lower() for r in roles)

        async def _check_role(user: AuthUser = Depends(self.require_auth)) -> AuthUser:
            actual_role = user.role.lower()
            # super_admin is the root administrative role and satisfies admin gates.
            if actual_role == "super_admin" and "admin" in allowed:
                return user
            if actual_role not in allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"Requires one of roles: {', '.join(roles)}",
                )
            return user

        return _check_role

    def require_permission(self, permission: str) -> Any:
        """Return a dependency that requires a specific permission."""
        async def _check_perm(user: AuthUser = Depends(self.require_auth)) -> AuthUser:
            # Super Admin is the immutable root role. Other roles may have
            # per-user allow/deny overrides managed by the control plane.
            if is_super_admin_identity(user.username, user.role):
                return user
            # Role permissions are always the baseline. Per-user overrides are
            # additive/removing only when a permission record actually exists.
            # This is important for newly-created/test users whose signal
            # permission record has not been provisioned yet.
            allowed = role_has_permission(user.role, permission)
            try:
                from core.auth.user_signal_permissions import UserPermissionManager
                mgr = UserPermissionManager.get_instance()
                perm_record = mgr.get_user_permissions(user.username)
                if perm_record is not None:
                    allowed = mgr.user_has_permission(user.username, permission, base_role=user.role)
            except Exception as exc:
                _log.warning("Per-user permission lookup failed for %s: %s", user.username, exc)
            if not allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {permission}",
                )
            return user

        return _check_perm

    def require_any_permission(self, *permissions: str) -> Any:
        """Return a dependency that accepts any one of the supplied permissions.

        This is intentionally evaluated against the same effective per-user RBAC
        model as ``require_permission``.  It is useful for read-only admin pages
        whose data may be viewed by either an audit/log user or a user-management
        administrator, without granting either role the other's capabilities.
        """
        normalized = tuple(str(p).strip().lower() for p in permissions if str(p).strip())

        async def _check_any(user: AuthUser = Depends(self.require_auth)) -> AuthUser:
            if is_super_admin_identity(user.username, user.role):
                return user
            for permission in normalized:
                try:
                    from core.auth.user_signal_permissions import UserPermissionManager
                    mgr = UserPermissionManager.get_instance()
                    if mgr.user_has_permission(user.username, permission, base_role=user.role):
                        return user
                except Exception as exc:
                    _log.warning("Per-user permission lookup failed for %s: %s", user.username, exc)
                    if role_has_permission(user.role, permission):
                        return user
            detail = ", ".join(normalized) or "a required permission"
            raise HTTPException(status_code=403, detail=f"Permission denied: requires one of: {detail}")

        return _check_any

    def optional_auth_with_fallback(self, fallback_role: str = "viewer") -> Any:
        """Auth if possible, else use fallback role."""
        async def _resolve(request: Request) -> AuthUser:
            try:
                return await self.require_auth(request)
            except HTTPException:
                return AuthUser(
                    user_id="anonymous",
                    username="anonymous",
                    role=fallback_role,
                    display_name="Anonymous",
                )
        return _resolve

    # ── MFA dependency ────────────────────────────────────────────────────────

    async def require_mfa_verified(self, request: Request) -> None:
        """Dependency that checks MFA verification status for the current session.

        If the user has MFA enabled and the session is not yet verified,
        raises HTTP 403 with detail "MFA required".

        Usage:
            @app.get("/protected")
            async def protected(user: AuthUser = Depends(auth.require_auth),
                                 _: None = Depends(auth.require_mfa_verified)):
                ...
        """
        user = getattr(request.state, "user", None)
        token = getattr(request.state, "token", None)

        if user is None or token is None:
            return

        # Check if MFA is enabled for this user
        if not self._auth.is_mfa_enabled(user.username):
            return  # No MFA required

        # Check if session has been MFA-verified
        if not get_mfa_session_state().is_verified(token.token):
            raise HTTPException(
                status_code=403,
                detail="MFA required. Call POST /api/auth/mfa/verify-session first.",
            )


# ── Non-dependency helpers ─────────────────────────────────────────────────────

def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""


__all__ = [
    "AuthDependencies",
    "get_client_ip",
]
