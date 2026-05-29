"""
AD-KIYU Auth Routes — FastAPI router for login, logout, password management,
user management, and session management.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from core.auth.csrf import CSRF_COOKIE_NAME
from core.auth.dependencies import AuthDependencies, get_client_ip
from core.auth.handler import (
    SESSION_COOKIE_NAME,
    AuthHandler,
    AuthToken,
    AuthUser,
    generate_csrf_token,
)

_log = logging.getLogger(__name__)


def create_auth_router(
    auth_handler: AuthHandler,
    auth_deps: AuthDependencies,
    cookie_secure: bool = False,
    cookie_domain: str = "",
) -> APIRouter:
    """Create a FastAPI router with all auth endpoints."""
    router = APIRouter(prefix="/api/auth", tags=["Authentication"])
    _cookie_secure = cookie_secure
    _cookie_domain = cookie_domain

    def _set_session_cookie(response: Response, token_str: str, max_age: int, request: Request | None = None) -> None:
        secure = _cookie_secure
        if request is not None:
            secure = request.url.scheme == "https"
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token_str,
            max_age=max_age,
            httponly=True,
            samesite="lax",
            secure=secure,
            domain=_cookie_domain or None,
            path="/",
        )

    def _set_csrf_cookie(response: Response, csrf_token: str, request: Request | None = None) -> None:
        secure = _cookie_secure
        if request is not None:
            secure = request.url.scheme == "https"
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=csrf_token,
            max_age=86400,
            httponly=False,
            samesite="lax",
            secure=secure,
            domain=_cookie_domain or None,
            path="/",
        )

    def _clear_session_cookie(response: Response) -> None:
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            path="/",
            domain=_cookie_domain or None,
        )

    def _clear_csrf_cookie(response: Response) -> None:
        response.delete_cookie(
            key=CSRF_COOKIE_NAME,
            path="/",
            domain=_cookie_domain or None,
        )

    # ── Login ─────────────────────────────────────────────────────────────────

    @router.post("/login")
    async def login(
        request: Request,
        response: Response,
    ) -> dict:
        """Authenticate and create a session."""
        body = await request.json()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", "")).strip()
        ip = get_client_ip(request)
        ua = request.headers.get("user-agent", "")

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")

        user = auth_handler.authenticate(username, password, ip)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = auth_handler.create_session(user, ip, ua)
        csrf_token = generate_csrf_token()

        _set_session_cookie(response, token.token, auth_handler._token_ttl, request=request)
        _set_csrf_cookie(response, csrf_token, request=request)

        return {
            "success": True,
            "user": user.to_dict(),
            "must_change_password": user.must_change_password,
        }

    # ── Logout ────────────────────────────────────────────────────────────────

    @router.post("/logout")
    async def logout(
        request: Request,
        response: Response,
    ) -> dict:
        """Logout and revoke session."""
        token_str = request.cookies.get(SESSION_COOKIE_NAME, "")
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token_str = auth_header[7:]

        if token_str:
            auth_handler.revoke_session(token_str)

        _clear_session_cookie(response)
        _clear_csrf_cookie(response)

        return {"success": True}

    # ── Session info ──────────────────────────────────────────────────────────

    @router.get("/session")
    async def get_session(
        current_user: AuthUser = Depends(auth_deps.require_auth),
        current_token: AuthToken = Depends(_get_token_from_state),
    ) -> dict:
        """Get current session information."""
        return {
            "authenticated": True,
            "user": current_user.to_dict(),
            "session": current_token.to_dict(),
        }

    # ── Change password ───────────────────────────────────────────────────────

    @router.post("/change-password")
    async def change_password(
        request: Request,
        current_user: AuthUser = Depends(auth_deps.require_auth),
    ) -> dict:
        """Change password for the current user."""
        body = await request.json()
        current = str(body.get("current_password", ""))
        new = str(body.get("new_password", ""))

        if not current or not new:
            raise HTTPException(status_code=400, detail="Current and new password required")

        result = auth_handler.update_password(current_user.username, current, new)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Password change failed"))

        return {"success": True}

    # ── User management (admin only) ──────────────────────────────────────────

    admin_only = auth_deps.require_role("admin")

    @router.get("/users")
    async def list_users(
        admin: AuthUser = Depends(admin_only),
    ) -> list:
        """List all users. Admin only."""
        return auth_handler.list_users()

    @router.post("/users")
    async def create_user(
        request: Request,
        admin: AuthUser = Depends(admin_only),
    ) -> dict:
        """Create a new user. Admin only."""
        body = await request.json()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        role = str(body.get("role", "viewer")).lower()
        display_name = str(body.get("display_name", ""))

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")

        result = auth_handler.create_user(username, password, role, display_name, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "User creation failed"))

        return result

    @router.put("/users/{username}/role")
    async def update_user_role(
        username: str,
        request: Request,
        admin: AuthUser = Depends(admin_only),
    ) -> dict:
        """Update a user's role. Admin only."""
        body = await request.json()
        new_role = str(body.get("role", "")).lower()

        result = auth_handler.update_user_role(username, new_role, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Role update failed"))

        return result

    @router.post("/users/{username}/reset-password")
    async def reset_user_password(
        username: str,
        request: Request,
        admin: AuthUser = Depends(admin_only),
    ) -> dict:
        """Admin-forced password reset. Admin only."""
        body = await request.json()
        new_password = str(body.get("new_password", ""))

        result = auth_handler.admin_reset_password(username, new_password, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Password reset failed"))

        auth_handler.revoke_all_user_sessions(username)
        return result

    @router.post("/users/{username}/disable")
    async def disable_user(
        username: str,
        admin: AuthUser = Depends(admin_only),
    ) -> dict:
        """Disable a user account. Admin only."""
        result = auth_handler.disable_user(username, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Disable failed"))
        auth_handler.revoke_all_user_sessions(username)
        return result

    @router.post("/users/{username}/enable")
    async def enable_user(
        username: str,
        admin: AuthUser = Depends(admin_only),
    ) -> dict:
        """Enable a disabled user. Admin only."""
        result = auth_handler.enable_user(username, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Enable failed"))
        return result

    @router.delete("/users/{username}")
    async def delete_user(
        username: str,
        admin: AuthUser = Depends(admin_only),
    ) -> dict:
        """Delete a user. Admin only."""
        result = auth_handler.delete_user(username, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
        return result

    # ── Session management (admin) ────────────────────────────────────────────

    @router.get("/users/{username}/sessions")
    async def get_user_sessions(
        username: str,
        admin: AuthUser = Depends(admin_only),
    ) -> list:
        """Get sessions for a user. Admin only."""
        user = auth_handler.get_user(username)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return auth_handler.get_user_sessions(user.user_id)

    @router.post("/users/{username}/revoke-sessions")
    async def revoke_user_sessions(
        username: str,
        admin: AuthUser = Depends(admin_only),
    ) -> dict:
        """Revoke all sessions for a user. Admin only."""
        count = auth_handler.revoke_all_user_sessions(username)
        return {"success": True, "sessions_revoked": count}

    # ── Audit log (admin) ─────────────────────────────────────────────────────

    @router.get("/audit")
    async def get_audit_log(
        limit: int = 100,
        event_type: str | None = None,
        admin: AuthUser = Depends(admin_only),
    ) -> list:
        """Get auth audit log. Admin only."""
        return auth_handler.get_audit_log(limit=limit, event_type=event_type)

    # ── Auth stats ────────────────────────────────────────────────────────────

    @router.get("/stats")
    async def auth_stats(
        admin: AuthUser = Depends(admin_only),
    ) -> dict:
        """Get auth system statistics."""
        return auth_handler.get_stats()

    return router


# ── Helper dependency ──────────────────────────────────────────────────────────

async def _get_token_from_state(request: Request) -> Any:
    """Extract AuthToken from request state."""
    token = getattr(request.state, "token", None)
    if token is None:
        raise HTTPException(status_code=401, detail="No active session")
    return token
