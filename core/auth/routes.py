"""
AD-KIYU Auth Routes - FastAPI router for login, logout, password management,
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
from core.auth.mfa import (
    generate_mfa_secret,
    generate_recovery_codes,
    get_mfa_provisioning_uri,
    get_mfa_session_state,
    hash_recovery_code,
    verify_mfa_token,
)

_log = logging.getLogger(__name__)


def create_auth_router(
    auth_handler: AuthHandler,
    auth_deps: AuthDependencies,
    cookie_secure: bool = False,
    cookie_domain: str = "",
    sso_config: dict[str, Any] | None = None,
) -> APIRouter:
    """Create a FastAPI router with all auth endpoints.

    Args:
        auth_handler: The AuthHandler instance.
        auth_deps: The AuthDependencies instance.
        cookie_secure: Whether to set Secure flag on cookies.
        cookie_domain: Optional cookie domain.
        sso_config: Optional SSO config dict with sso_* keys.
    """
    router = APIRouter(prefix="/api/auth", tags=["Authentication"])
    _cookie_secure = cookie_secure
    _cookie_domain = cookie_domain

    # Create singleton SSO authenticator if config is provided
    _sso_authenticator = None
    if sso_config and sso_config.get("sso_enabled", False):
        from core.auth.sso import SSOAuthenticator
        _sso_authenticator = SSOAuthenticator.from_config(auth_handler, sso_config)

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

        mfa_required = auth_handler.is_mfa_enabled(username)

        return {
            "success": True,
            "user": user.to_dict(),
            "must_change_password": user.must_change_password,
            "mfa_required": mfa_required,
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

    # ── MFA Routes ────────────────────────────────────────────────────────────

    @router.post("/mfa/setup")
    async def mfa_setup(
        current_user: AuthUser = Depends(auth_deps.require_auth),
    ) -> dict:
        """Generate a new MFA secret and provisioning URI for the current user.

        This does NOT enable MFA yet. The user must verify a token first
        via POST /api/auth/mfa/verify.

        Returns:
            Dict with ``secret``, ``provisioning_uri``, and ``recovery_codes``.
            The recovery codes are shown only once — the user must save them.
        """
        secret = generate_mfa_secret()
        provisioning_uri = get_mfa_provisioning_uri(
            username=current_user.username,
            secret=secret,
            issuer="OPB Enterprise",
        )
        recovery_codes = generate_recovery_codes()

        # Save secret (but don't enable MFA yet)
        auth_handler.set_mfa_secret(current_user.username, secret)

        # Return hashed recovery codes for storage
        hashed_codes = [hash_recovery_code(c) for c in recovery_codes]
        auth_handler.update_mfa_recovery_codes(current_user.username, hashed_codes)

        return {
            "success": True,
            "secret": secret,
            "provisioning_uri": provisioning_uri,
            "recovery_codes": recovery_codes,
            "note": "Save these recovery codes securely. They will not be shown again.",
        }

    @router.post("/mfa/verify")
    async def mfa_verify(
        request: Request,
        current_user: AuthUser = Depends(auth_deps.require_auth),
        current_token: AuthToken = Depends(_get_token_from_state),
    ) -> dict:
        """Verify a TOTP token to enable MFA.

        JSON body:
            token: The 6-digit TOTP code from the authenticator app.

        On success, MFA is enabled for the user.
        """
        body = await request.json()
        token = str(body.get("token", "")).strip()

        if not token:
            raise HTTPException(status_code=400, detail="Token required")

        secret = auth_handler.get_mfa_secret(current_user.username)
        if not secret:
            raise HTTPException(status_code=400, detail="MFA not set up yet. Call POST /api/auth/mfa/setup first.")

        if auth_handler.is_mfa_enabled(current_user.username):
            raise HTTPException(status_code=400, detail="MFA is already enabled")

        if not verify_mfa_token(secret, token):
            raise HTTPException(status_code=400, detail="Invalid token")

        # Enable MFA (recovery codes were already saved during setup)
        codes = auth_handler.get_mfa_recovery_codes(current_user.username)
        auth_handler.enable_mfa(current_user.username, codes)

        return {"success": True, "message": "MFA enabled successfully"}

    @router.post("/mfa/disable")
    async def mfa_disable(
        request: Request,
        current_user: AuthUser = Depends(auth_deps.require_auth),
    ) -> dict:
        """Disable MFA for the current user. Requires password confirmation.

        JSON body:
            password: Current password for verification.
        """
        body = await request.json()
        password = str(body.get("password", ""))
        ip = get_client_ip(request)

        if not password:
            raise HTTPException(status_code=400, detail="Password required to disable MFA")

        # Verify password via public authenticate() method
        verified_user = auth_handler.authenticate(current_user.username, password, ip)
        if verified_user is None:
            raise HTTPException(status_code=403, detail="Invalid password")

        auth_handler.disable_mfa(current_user.username)

        return {"success": True, "message": "MFA disabled"}

    @router.get("/mfa/status")
    async def mfa_status(
        current_user: AuthUser = Depends(auth_deps.require_auth),
        current_token: AuthToken = Depends(_get_token_from_state),
    ) -> dict:
        """Get MFA status for the current user.

        Returns:
            Dict with ``enabled``, ``setup_complete`` (secret exists),
            and ``session_verified`` (MFA completed in this session).
        """
        enabled = auth_handler.is_mfa_enabled(current_user.username)
        secret = auth_handler.get_mfa_secret(current_user.username)
        session_verified = get_mfa_session_state().is_verified(current_token.token)

        return {
            "enabled": enabled,
            "setup_complete": bool(secret),
            "session_verified": session_verified,
            "username": current_user.username,
        }

    @router.post("/mfa/verify-session")
    async def mfa_verify_session(
        request: Request,
        current_user: AuthUser = Depends(auth_deps.require_auth),
        current_token: AuthToken = Depends(_get_token_from_state),
    ) -> dict:
        """Verify MFA for the current session (used during login when MFA is enabled).

        JSON body:
            token: The 6-digit TOTP code, OR
            recovery_code: A recovery code (8 alphanumeric characters)

        On success, the session is marked as MFA-verified.
        """
        body = await request.json()
        token = str(body.get("token", "")).strip()
        recovery_code = str(body.get("recovery_code", "")).strip()

        if not token and not recovery_code:
            raise HTTPException(status_code=400, detail="Token or recovery code required")

        if not auth_handler.is_mfa_enabled(current_user.username):
            raise HTTPException(status_code=400, detail="MFA is not enabled")

        # Try TOTP token first
        if token:
            secret = auth_handler.get_mfa_secret(current_user.username)
            if secret and verify_mfa_token(secret, token):
                get_mfa_session_state().mark_verified(current_token.token)
                return {"success": True, "method": "totp"}

        # Try recovery code
        if recovery_code:
            if auth_handler.use_recovery_code(current_user.username, recovery_code):
                get_mfa_session_state().mark_verified(current_token.token)
                return {"success": True, "method": "recovery_code"}

        raise HTTPException(status_code=400, detail="Invalid token or recovery code")

    @router.get("/mfa/recovery-codes")
    async def mfa_recovery_codes(
        request: Request,
        current_user: AuthUser = Depends(auth_deps.require_auth),
    ) -> dict:
        """Get the count of remaining recovery codes for the current user.

        For security, the actual codes are not returned — only the count.
        """
        codes = auth_handler.get_mfa_recovery_codes(current_user.username)
        return {
            "remaining": len(codes),
            "total_initial": 8,
            "note": "Recovery codes are stored hashed and cannot be retrieved.",
        }

    # ── SSO / OAuth2 Routes ───────────────────────────────────────────────────

    @router.get("/sso/login")
    async def sso_login(
        request: Request,
        provider: str = "google",
    ) -> dict:
        """Initiate SSO login with the specified provider.

        Query params:
            provider: OAuth2 provider (google, microsoft, github).

        Returns:
            Dict with ``authorization_url`` to redirect the user to.
        """
        # Use singleton SSO authenticator (closure) or create from req state
        sso = _sso_authenticator
        if sso is None:
            app_config = getattr(request.app.state, "config", {}) or {}
            app_config["sso_redirect_uri"] = str(request.base_url) + "api/auth/sso/callback"
            sso = SSOAuthenticator.from_config(auth_handler, app_config)

        # Override redirect_uri to match the actual request
        sso._config.redirect_uri = str(request.base_url) + "api/auth/sso/callback"

        url = sso.get_authorization_url()
        if url is None:
            ready, issues = sso.is_ready()
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "SSO not available",
                    "issues": issues,
                    "hint": "Install authlib: pip install authlib httpx",
                },
            )
        return {"success": True, "authorization_url": url}

    @router.get("/sso/callback")
    async def sso_callback(
        request: Request,
        code: str = "",
        state: str = "",
    ) -> dict:
        """Handle SSO OAuth2 callback.

        Query params:
            code: Authorization code from provider.
            state: OAuth2 state parameter.

        Returns:
            Dict with session token and user info on success.
        """
        if not code or not state:
            raise HTTPException(status_code=400, detail="Missing code or state parameter")

        # Use the same SSO authenticator instance (preserves OAuth2 state)
        sso = _sso_authenticator
        if sso is None:
            app_config = getattr(request.app.state, "config", {}) or {}
            sso = SSOAuthenticator.from_config(auth_handler, app_config)

        sso_user = await sso.handle_callback(code, state)
        if sso_user is None:
            raise HTTPException(status_code=401, detail="SSO authentication failed")

        # Get or create local user
        local_user = sso.get_or_create_user(sso_user)
        if local_user is None:
            raise HTTPException(status_code=500, detail="Failed to create local user from SSO")

        # Create session
        ip = get_client_ip(request)
        ua = request.headers.get("user-agent", "")
        token = auth_handler.create_session(local_user, ip, ua)

        return {
            "success": True,
            "user": local_user.to_dict(),
            "session": token.to_dict(),
            "sso_provider": sso_user.provider,
        }

    @router.get("/sso/providers")
    async def sso_providers() -> dict:
        """List available SSO/OAuth2 providers."""
        from core.auth.sso import OAUTH_PROVIDERS
        return {
            "success": True,
            "providers": list(OAUTH_PROVIDERS.keys()),
            "details": {
                name: {"scope": cfg["scope"]}
                for name, cfg in OAUTH_PROVIDERS.items()
            },
        }

    return router


# ── Helper dependency ──────────────────────────────────────────────────────────

async def _get_token_from_state(request: Request) -> Any:
    """Extract AuthToken from request state."""
    token = getattr(request.state, "token", None)
    if token is None:
        raise HTTPException(status_code=401, detail="No active session")
    return token


__all__ = [
    "create_auth_router",
]
