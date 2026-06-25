"""
AD-KIYU Auth Dependencies - FastAPI dependency injection for auth + RBAC.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, Request

from core.auth.handler import AuthHandler, AuthUser
from core.auth.mfa import get_mfa_session_state
from core.auth.permissions import role_has_permission
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
            if user.role.lower() not in allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"Requires one of roles: {', '.join(roles)}",
                )
            return user

        return _check_role

    def require_permission(self, permission: str) -> Any:
        """Return a dependency that requires a specific permission."""
        async def _check_perm(user: AuthUser = Depends(self.require_auth)) -> AuthUser:
            if not role_has_permission(user.role, permission):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {permission}",
                )
            return user

        return _check_perm

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
