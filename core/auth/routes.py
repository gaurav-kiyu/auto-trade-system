"""AD-KIYU Auth Routes - FastAPI router for login, logout, password management,
user management, and session management.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from fastapi import APIRouter, Depends, HTTPException, Request, Response
    from fastapi.responses import RedirectResponse
except ImportError:
    class APIRouter:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
        def get(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def post(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def put(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def delete(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
    def Depends(dependency: Any = None) -> Any: return dependency  # type: ignore
    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int = 500, detail: str = "") -> None:
            self.status_code = status_code
            self.detail = detail
            super().__init__(f"[{status_code}] {detail}")
    class Request:  # type: ignore
        pass
    class Response:  # type: ignore
        pass


from core.auth.csrf import CSRF_COOKIE_NAME
from core.ports.rate_limiting.rate_limit_port import LimitResult, RateLimitConfig
from core.services.rate_limiting_service import RateLimitingService

# Singleton rate limiter for register endpoint (5 attempts per IP per 15 minutes)
_register_rate_limiter = RateLimitingService(
    RateLimitConfig(limit=5, window=900, algorithm="fixed_window"),
)
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
from core.auth.permissions import is_super_admin_identity
from core.auth.registration_notifications import notify_new_registration
from core.auth.user_signal_permissions import ALL_CATEGORIES, UserPermissionManager
from core.notifications.url_resolver import build_action_url

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

    # ── Register ──────────────────────────────────────────────────────────────

    @router.post("/register")
    async def register(
        request: Request,
    ) -> dict:
        """Register a new user (self-registration, defaults to viewer role).

        Rate limited to 5 registrations per IP per 15 minutes.

        JSON body:
            username: Unique username.
            password: Password (min 8 chars).
            display_name: Optional display name.

        Returns:
            Dict with success status and user info.

        """
        # Apply rate limiting (5 registrations per IP per 15 minutes)
        client_ip = get_client_ip(request)
        result = _register_rate_limiter.is_allowed(f"register:{client_ip}")
        if result == LimitResult.DENIED:
            _log.warning("[AUTH] Register rate limited for IP: %s", client_ip)
            raise HTTPException(
                status_code=429,
                detail="Too many registration attempts. Please try again later.",
            )

        body = await request.json()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        display_name = str(body.get("display_name", ""))
        email = str(body.get("email", "")).strip()
        telegram_chat_id = str(body.get("telegram_chat_id", "")).strip()
        role = "viewer"  # Self-registration always creates viewers

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")

        if len(password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

        result = auth_handler.create_user(
            username=username,
            password=password,
            role=role,
            display_name=display_name,
            created_by="self-register",
            email=email,
            telegram_chat_id=telegram_chat_id,
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Registration failed"))

        # Save email & telegram_chat_id into UserPermissionManager
        try:
            perm_mgr = UserPermissionManager.get_instance()
            update_data: dict[str, Any] = {}
            # Self-registration is intentionally not authorized for signal delivery.
            # The account may log in to complete the profile flow, but restricted
            # signal access remains blocked until an administrator explicitly
            # grants it through User Authorization & Controls.
            update_data["is_active"] = False
            update_data["signals_enabled"] = False
            if email:
                update_data["email"] = email
                update_data["email_enabled"] = True
            if telegram_chat_id:
                update_data["telegram_chat_id"] = telegram_chat_id
                update_data["telegram_enabled"] = True
            perm_mgr.update_user_permissions(username, update_data, admin_username="self-register")
        except Exception as e:
            _log.warning("[AUTH] Failed to save user signal permissions on register: %s", e)

        notification_result = notify_new_registration(
            username=username,
            display_name=display_name,
            email=email,
            role=role,
            created_by="self-register",
        )
        return {
            "success": True,
            "message": "Account created successfully with viewer role and is pending administrator authorization.",
            "notification": notification_result,
        }

    # ── Login ─────────────────────────────────────────────────────────────────

    @router.get("/login")
    async def login_get() -> Response:
        """Redirect GET /api/auth/login directly to the HTML login page."""
        return RedirectResponse(url="/login", status_code=307)

    @router.post("/login")
    async def login(
        request: Request,
        response: Response,
    ) -> dict:
        """Authenticate and create a session."""
        try:
            body = await request.json()
            username = str(body.get("username", "")).strip()
            password = str(body.get("password", "")).strip()
        except Exception:
            try:
                form = await request.form()
                username = str(form.get("username", "")).strip()
                password = str(form.get("password", "")).strip()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid request body")

        ip = get_client_ip(request)
        ua = request.headers.get("user-agent", "")

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")

        user = auth_handler.authenticate(username, password, ip)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = auth_handler.create_session(user, ip, ua)
        csrf_token = generate_csrf_token()

        mfa_required = auth_handler.is_mfa_enabled(username)

        # Check if browser form post vs AJAX JSON
        content_type = request.headers.get("content-type", "")
        accept_header = request.headers.get("accept", "")
        is_html_form = "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type or "text/html" in accept_header

        if is_html_form and not mfa_required:
            target_url = "/change-password" if user.must_change_password else "/"
            redirect_resp = RedirectResponse(url=target_url, status_code=303)
            _set_session_cookie(redirect_resp, token.token, auth_handler._token_ttl, request=request)
            _set_csrf_cookie(redirect_resp, csrf_token, request=request)
            return redirect_resp  # type: ignore[return-value]

        _set_session_cookie(response, token.token, auth_handler._token_ttl, request=request)
        _set_csrf_cookie(response, csrf_token, request=request)

        return {
            "success": True,
            "user": user.to_dict(),
            "must_change_password": user.must_change_password,
            "mfa_required": mfa_required,
        }

    # ── Logout ────────────────────────────────────────────────────────────────

    @router.get("/logout")
    @router.post("/logout")
    async def logout(
        request: Request,
        response: Response,
    ) -> Any:
        """Logout, revoke session, and redirect browser requests to /login."""
        token_str = request.cookies.get(SESSION_COOKIE_NAME, "")
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token_str = auth_header[7:]

        if token_str:
            auth_handler.revoke_session(token_str)

        accept_header = request.headers.get("accept", "")
        if request.method == "GET" or "text/html" in accept_header:
            redirect_resp = RedirectResponse(url="/login", status_code=303)
            _clear_session_cookie(redirect_resp)
            _clear_csrf_cookie(redirect_resp)
            return redirect_resp

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

    # ── User profile ──────────────────────────────────────────────────────────

    @router.get("/profile")
    async def get_my_profile(
        current_user: AuthUser = Depends(auth_deps.require_auth),
    ) -> dict:
        """Get the current user's profile and signal delivery preferences."""
        metadata = current_user.metadata or {}
        perms = UserPermissionManager.get_instance().get_user_permissions(current_user.username)
        return {
            "success": True,
            "user": {
                "user_id": current_user.user_id,
                "username": current_user.username,
                "display_name": current_user.display_name or metadata.get("display_name", current_user.username),
                "role": current_user.role,
                "email": getattr(current_user, "email", None) or metadata.get("email", ""),
                "telegram_chat_id": getattr(current_user, "telegram_chat_id", None) or metadata.get("telegram_chat_id", ""),
                "created_ts": current_user.created_ts,
                "last_login_ts": current_user.last_login_ts,
                "must_change_password": current_user.must_change_password,
                "mfa_enabled": getattr(current_user, "mfa_enabled", False),
                "permissions": perms.to_dict() if perms else {},
            },
        }

    @router.post("/profile")
    async def update_my_profile(
        request: Request,
        current_user: AuthUser = Depends(auth_deps.require_auth),
    ) -> dict:
        """Update the current user's display name, email, and telegram chat id."""
        body = await request.json()
        display_name = str(body.get("display_name", "")).strip() or current_user.display_name
        email = str(body.get("email", "")).strip()
        telegram_chat_id = str(body.get("telegram_chat_id", "")).strip()

        # Update Auth metadata & display_name
        auth_handler.update_user_metadata(
            current_user.username,
            {"email": email, "telegram_chat_id": telegram_chat_id, "display_name": display_name},
            display_name=display_name,
        )

        # Update Signal Permissions store
        perm_updates = {"display_name": display_name}
        if email is not None:
            perm_updates["email"] = email
        if telegram_chat_id is not None:
            perm_updates["telegram_chat_id"] = telegram_chat_id
        UserPermissionManager.get_instance().update_user_permissions(current_user.username, perm_updates, admin_username=current_user.username)

        return {
            "success": True,
            "message": "Profile updated successfully",
            "user": {
                "username": current_user.username,
                "display_name": display_name,
                "email": email,
                "telegram_chat_id": telegram_chat_id,
                "role": current_user.role,
            },
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

    # Granular administrative gates. Super Admin satisfies every permission.
    manage_users = auth_deps.require_permission("manage_users")
    manage_permissions = auth_deps.require_permission("manage_permissions")
    view_signal_analytics = auth_deps.require_any_permission("manage_users", "view_logs")

    @router.get("/users")
    async def list_users(
        admin: AuthUser = Depends(manage_users),
    ) -> list:
        """List all users. Admin only."""
        return auth_handler.list_users()

    @router.post("/users")
    async def create_user(
        request: Request,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Create a new user. Admin only."""
        body = await request.json()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        role = str(body.get("role", "viewer")).strip().lower()
        display_name = str(body.get("display_name", ""))
        email = str(body.get("email", "")).strip()
        telegram_chat_id = str(body.get("telegram_chat_id", "")).strip()

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")

        valid_roles = {"super_admin", "admin", "operator", "viewer", "observer", "developer"}
        if role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Unsupported role: {role}")
        if not is_super_admin_identity(admin.username, admin.role) and role != "viewer":
            raise HTTPException(status_code=403, detail="Only Super Admin can create accounts with elevated roles")

        result = auth_handler.create_user(
            username=username,
            password=password,
            role=role,
            display_name=display_name,
            created_by=admin.username,
            email=email,
            telegram_chat_id=telegram_chat_id,
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "User creation failed"))

        try:
            perm_mgr = UserPermissionManager.get_instance()
            create_data: dict[str, Any] = {
                "display_name": display_name or username,
                "role": role,
                "is_active": True,
                "signals_enabled": False,
            }
            if email:
                create_data["email"] = email
                create_data["email_enabled"] = True
            if telegram_chat_id:
                create_data["telegram_chat_id"] = telegram_chat_id
                create_data["telegram_enabled"] = True
            perm_mgr.update_user_permissions(username, create_data, admin_username=admin.username)
        except Exception as e:
            _log.warning("[AUTH] Failed to save user signal permissions on admin create user: %s", e)

        notification_result = notify_new_registration(
            username=username,
            display_name=display_name,
            email=email,
            role=role,
            created_by=admin.username,
        )
        result["notification"] = notification_result
        return result

    @router.put("/users/{username}/role")
    async def update_user_role(
        username: str,
        request: Request,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """Update a user's role. Admin only."""
        body = await request.json()
        new_role = str(body.get("role", "")).lower()
        target = auth_handler.get_user(username)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")

        # Only the root role may grant/revoke Super Admin. This prevents an
        # ordinary Admin from escalating another account to the root role.
        if new_role == "super_admin" and not is_super_admin_identity(admin.username, admin.role):
            raise HTTPException(status_code=403, detail="Only Super Admin can assign Super Admin role")
        if str(target.role).lower() == "super_admin" and new_role != "super_admin" and not is_super_admin_identity(admin.username, admin.role):
            raise HTTPException(status_code=403, detail="Only Super Admin can modify a Super Admin")

        # Never remove the final active Super Admin.
        if str(target.role).lower() == "super_admin" and new_role != "super_admin":
            roots = [u for u in auth_handler.list_users() if str(u.get("role", "")).lower() == "super_admin" and not u.get("disabled")]
            if len(roots) <= 1:
                raise HTTPException(status_code=400, detail="The last active Super Admin cannot be demoted")

        result = auth_handler.update_user_role(username, new_role, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Role update failed"))
        try:
            UserPermissionManager.get_instance().update_user_permissions(username, {"role": new_role}, admin_username=admin.username)
        except Exception as sync_ex:
            _log.warning("[AUTH] Failed to synchronize role metadata for %s: %s", username, sync_ex)

        return result

    @router.post("/users/{username}/reset-password")
    async def reset_user_password(
        username: str,
        request: Request,
        admin: AuthUser = Depends(manage_users),
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
        admin: AuthUser = Depends(manage_users),
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
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Enable a disabled user. Admin only."""
        result = auth_handler.enable_user(username, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Enable failed"))
        return result

    @router.delete("/users/{username}")
    async def delete_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Delete a user with safety guards for the current/last administrator."""
        target = username.strip().lower()
        if target == admin.username.strip().lower():
            raise HTTPException(status_code=400, detail="You cannot delete your own active administrator account")

        # Never allow the control plane to remove the final administrator.
        admins = [u for u in auth_handler.list_users() if str(u.get("role", "")).lower() in {"admin", "super_admin"} and not u.get("disabled")]
        target_user = auth_handler.get_user(target)
        if target_user and str(target_user.role).lower() in {"admin", "super_admin"} and len(admins) <= 1:
            raise HTTPException(status_code=400, detail="The last active administrator cannot be deleted")

        result = auth_handler.delete_user(target, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
        UserPermissionManager.get_instance().delete_user_permissions(target)
        return result

    # ── Super Admin User Signal Permissions & Quotas ──────────────────────────

    @router.get("/user-permissions")
    async def list_all_user_permissions(
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """List all users with full signal permissions, quotas, and categories."""
        mgr = UserPermissionManager.get_instance()
        auth_users = auth_handler.list_users()
        active_unames = {u["username"] for u in auth_users}
        mgr.prune_stale_users(active_unames)

        for u in auth_users:
            uname = u["username"]
            perm = mgr.get_user_permissions(uname)
            u_email = u.get("email") or (u.get("metadata") or {}).get("email", "")
            u_tg = u.get("telegram_chat_id") or (u.get("metadata") or {}).get("telegram_chat_id", "")
            u_name = u.get("display_name") or (u.get("metadata") or {}).get("display_name", "")
            u_role = u.get("role", "viewer")

            if not perm:
                mgr.update_user_permissions(
                    uname,
                    {
                        "display_name": u_name or uname,
                        "role": u_role,
                        "is_active": not u.get("disabled", False),
                        "signals_enabled": True if u_role in {"admin", "super_admin"} else False,
                        "email": u_email,
                        "email_enabled": True if uname == "admin" or bool(u_email) else False,
                        "telegram_chat_id": u_tg,
                        "telegram_enabled": bool(u_tg),
                    },
                    admin_username="system-sync",
                )

        all_perms = mgr.list_all_permissions()
        return {
            "success": True,
            "categories": ALL_CATEGORIES,
            "permissions": all_perms,
        }

    @router.get("/users/{username}/permissions")
    async def get_user_permissions(
        username: str,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """Get signal permissions and quota usage for a specific user."""
        mgr = UserPermissionManager.get_instance()
        u = auth_handler.get_user(username)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")

        u_meta = u.metadata or {}
        u_email = getattr(u, "email", None) or u_meta.get("email", "")
        u_tg = getattr(u, "telegram_chat_id", None) or u_meta.get("telegram_chat_id", "")
        u_name = u.display_name or u_meta.get("display_name", u.username)

        perm = mgr.get_user_permissions(username)
        if not perm:
            mgr.update_user_permissions(
                username,
                {
                    "display_name": u_name,
                    "role": u.role,
                    "is_active": not u.disabled,
                    "signals_enabled": True if u.role in {"admin", "super_admin"} else False,
                    "email": u_email,
                    "email_enabled": bool(u_email),
                    "telegram_chat_id": u_tg,
                    "telegram_enabled": bool(u_tg),
                },
                admin_username="system-sync",
            )
            perm = mgr.get_user_permissions(username)

        perm_dict = perm.to_dict() if perm else {}
        return {"success": True, "categories": ALL_CATEGORIES, "permissions": perm_dict}

    @router.post("/users/{username}/permissions")
    async def update_user_permissions(
        username: str,
        request: Request,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """Super Admin update of user signal permissions, category subscriptions, quotas, and channels."""
        body = await request.json()
        target_user = auth_handler.get_user(username)
        if target_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        target_role = str(target_user.role or "viewer").lower()
        admin_role = admin.role.lower()
        requested_role = str(body.get("role", target_role) or target_role).lower()
        valid_roles = {"super_admin", "admin", "operator", "viewer", "observer", "developer"}
        if requested_role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Unsupported role: {requested_role}")
        if requested_role != target_role and not is_super_admin_identity(admin.username, admin.role):
            raise HTTPException(status_code=403, detail="Only Super Admin can change user roles")
        if target_role == "super_admin" and not is_super_admin_identity(admin.username, admin.role):
            raise HTTPException(status_code=403, detail="Only Super Admin can modify Super Admin permissions")

        # Only Super Admin can grant capabilities the requesting administrator
        # does not possess. This makes the permission UI an actual security
        # boundary rather than a cosmetic menu control.
        requested_allowed = {str(v).lower() for v in (body.get("allowed_permissions") or [])}
        if not is_super_admin_identity(admin.username, admin.role):
            from core.auth.permissions import get_role_permissions
            own = {p.value for p in get_role_permissions(admin_role)}
            if not requested_allowed.issubset(own):
                raise HTTPException(status_code=403, detail="Admin cannot grant permissions beyond their own role")
            if target_role == "super_admin":
                raise HTTPException(status_code=403, detail="Only Super Admin can modify Super Admin permissions")

        if requested_role != target_role:
            role_result = auth_handler.update_user_role(username, requested_role, admin.username)
            if not role_result.get("success"):
                raise HTTPException(status_code=400, detail=role_result.get("error", "Role update failed"))
            target_role = requested_role

        mgr = UserPermissionManager.get_instance()
        ok, msg, updated = mgr.update_user_permissions(username, {**body, "role": target_role}, admin_username=admin.username)
        if ok:
            auth_handler.update_user_metadata(
                username,
                {
                    "email": body.get("email", ""),
                    "telegram_chat_id": body.get("telegram_chat_id", ""),
                },
                display_name=body.get("display_name"),
            )
            # Synchronize admin user changes across json/config.json and runtime config
            if username == "admin":
                try:
                    from core.config_manager import get_config_manager
                    cfg_mgr = get_config_manager()
                    cfg_updates = {}
                    if "email" in body:
                        cfg_updates["EMAIL_TO"] = str(body["email"])
                        if "email_enabled" in body:
                            cfg_updates["EMAIL_ENABLED"] = bool(body["email_enabled"])
                    if "telegram_chat_id" in body:
                        cfg_updates["CHAT_ID"] = str(body["telegram_chat_id"])
                    if cfg_updates:
                        cfg_mgr.update(cfg_updates)
                        _log.info("[ADMIN_SYNC] Synchronized admin user permissions to system config: %s", list(cfg_updates.keys()))
                except Exception as sync_ex:
                    _log.warning("[ADMIN_SYNC] Could not sync admin user to system config: %s", sync_ex)

        auth_handler._audit_log(
            "user_permissions_updated", admin.username, "",
            {"target_user": username, "changed_keys": list(body.keys()), "ok": ok},
            success=ok,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"success": True, "message": msg, "permissions": updated}

    @router.post("/users/{username}/toggle-signals")
    async def toggle_user_signals(
        username: str,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """One-click toggle of master signal delivery for a user."""
        mgr = UserPermissionManager.get_instance()
        ok, msg, enabled = mgr.toggle_user_signals(username, admin_username=admin.username)
        auth_handler._audit_log(
            "user_signals_toggled", admin.username, "",
            {"target_user": username, "signals_enabled": enabled, "ok": ok},
            success=ok,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"success": True, "message": msg, "signals_enabled": enabled}

    # ── Signal Intelligence, Category Accuracy & User Delivery History ────────

    @router.get("/signals/analytics")
    async def get_admin_signal_analytics(
        timeframe: str = "all",
        category: str = "all",
        tier: str = "all",
        status: str = "all",
        admin: AuthUser = Depends(view_signal_analytics),
    ) -> dict:
        """Signal Intelligence / Accuracy / Category Breakdown for authorized viewers."""
        from core.signals.signal_tracker import SignalTracker
        tracker = SignalTracker.get_instance()
        return tracker.get_admin_signal_analytics(timeframe=timeframe, category=category, tier=tier, status=status)

    @router.get("/signals/my-history")
    async def get_my_signal_history(
        year: str = "all",
        month: str = "all",
        week: str = "all",
        day: str = "all",
        category: str = "all",
        current_user: AuthUser = Depends(auth_deps.require_auth),
    ) -> dict:
        """Personalized received signal feed for the authenticated user with time filters."""
        from core.signals.signal_tracker import SignalTracker
        tracker = SignalTracker.get_instance()
        return tracker.get_user_received_signals(
            username=current_user.username,
            year=year,
            month=month,
            week=week,
            day=day,
            category=category,
        )

    @router.post("/signals/{signal_id}/mark-order-placed")
    async def mark_signal_order_placed(
        signal_id: str,
        request: Request,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Admin marks/unmarks "I actually placed an order off this signal"
        for historical record-keeping (templates/enterprise/admin_signals.html's
        Order Placed? column) - independent of the automatic price-based
        outcome grading in SignalTracker.update_active_signal_outcomes()."""
        body = await request.json()
        placed = bool(body.get("placed", True))
        from core.signals.signal_tracker import SignalTracker
        tracker = SignalTracker.get_instance()
        ok = tracker.mark_order_placed(signal_id, placed, admin.username)
        auth_handler._audit_log(
            "signal_order_placed_marked", admin.username, "",
            {"signal_id": signal_id, "placed": placed},
            success=ok,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Signal not found")
        return {"success": True, "signal_id": signal_id, "placed": placed}

    # ── Session management (admin) ────────────────────────────────────────────

    @router.get("/users/{username}/sessions")
    async def get_user_sessions(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> list:
        """Get sessions for a user. Admin only."""
        user = auth_handler.get_user(username)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return auth_handler.get_user_sessions(user.user_id)

    @router.post("/users/{username}/revoke-sessions")
    async def revoke_user_sessions(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Revoke all sessions for a user. Admin only."""
        count = auth_handler.revoke_all_user_sessions(username)
        auth_handler._audit_log(
            "user_sessions_revoked", admin.username, "",
            {"target_user": username, "sessions_revoked": count},
        )
        return {"success": True, "sessions_revoked": count}

    # ── Audit log (admin) ─────────────────────────────────────────────────────

    @router.get("/audit")
    async def get_audit_log(
        limit: int = 100,
        event_type: str | None = None,
        admin: AuthUser = Depends(manage_users),
    ) -> list[dict[str, Any]]:
        """Get auth audit log. Admin only."""
        from datetime import datetime, timedelta, timezone
        raw_logs = auth_handler.get_audit_log(limit=limit, event_type=event_type)
        ist = timezone(timedelta(hours=5, minutes=30))
        results = []
        for entry in raw_logs:
            item = dict(entry)
            ts = item.get("timestamp")
            if isinstance(ts, (int, float)):
                try:
                    dt = datetime.fromtimestamp(ts, tz=ist)
                    item["timestamp_str"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                    item["timestamp"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    item["timestamp_str"] = str(ts)
                    item["timestamp"] = str(ts)
            else:
                item["timestamp_str"] = str(ts or "-")
            results.append(item)
        return results

    # ── Auth stats ────────────────────────────────────────────────────────────

    @router.get("/stats")
    async def auth_stats(
        admin: AuthUser = Depends(manage_users),
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
            from core.auth.sso import SSOAuthenticator
            app_config = getattr(request.app.state, "config", {}) or {}
            sso_redirect_uri = build_action_url(
                "/api/auth/sso/callback",
                cfg=app_config,
            )
            app_config["sso_redirect_uri"] = sso_redirect_uri
            sso = SSOAuthenticator.from_config(auth_handler, app_config)

        # Keep the OAuth callback on the canonical public origin configured for
        # this deployment. Do not derive it from request.base_url because that
        # can be the internal reverse-proxy/upstream host (or localhost), which
        # would make the provider redirect the user to an unusable URL.
        app_config = getattr(request.app.state, "config", {}) or {}
        sso._config.redirect_uri = build_action_url(
            "/api/auth/sso/callback",
            cfg=app_config,
        )

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
            from core.auth.sso import SSOAuthenticator
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


    # ── Forgot & Reset Password Endpoints ─────────────────────────────────────

    @router.post("/forgot-password")
    async def forgot_password(request: Request) -> dict:
        """Request a password reset token for a given username."""
        body = await request.json()
        username = str(body.get("username", "")).strip()
        if not username:
            raise HTTPException(status_code=400, detail="Username is required")
        token = auth_handler.create_password_reset_token(username)
        if not token:
            # Generic error to prevent username enumeration or specific detail
            raise HTTPException(status_code=400, detail="Unable to request password reset. Please check username.")
        return {
            "success": True,
            "message": "Password reset token generated successfully",
            "token": token,
            "reset_url": f"/reset-password?token={token}",
            "expires_in": 3600
        }

    @router.post("/verify-reset-token")
    async def verify_reset_token(request: Request) -> dict:
        """Verify token validity."""
        body = await request.json()
        token = str(body.get("token", "")).strip()
        if not token:
            raise HTTPException(status_code=400, detail="Token is required")
        username = auth_handler.verify_password_reset_token(token, mark_used=False)
        if not username:
            raise HTTPException(status_code=400, detail="Invalid or expired token")
        return {
            "success": True,
            "valid": True,
            "username": username
        }

    @router.post("/reset-password")
    async def reset_password(request: Request) -> dict:
        """Reset password with token."""
        body = await request.json()
        token = str(body.get("token", "")).strip()
        new_password = str(body.get("new_password", ""))
        if not token or not new_password:
            raise HTTPException(status_code=400, detail="Token and new password are required")
        res = auth_handler.reset_password_with_token(token, new_password)
        if not res["success"]:
            raise HTTPException(status_code=400, detail=res.get("error", "Password reset failed"))
        return res

    @router.post("/emergency-reset-password")
    async def emergency_reset_password(request: Request) -> dict:
        """Emergency self-service password reset using master recovery key."""
        body = await request.json()
        username = str(body.get("username", "")).strip()
        recovery_key = str(body.get("recovery_key", "")).strip()
        new_password = str(body.get("new_password", ""))
        if not username or not recovery_key or not new_password:
            raise HTTPException(status_code=400, detail="Username, recovery key, and new password are required")
        res = auth_handler.emergency_master_reset_password(username, recovery_key, new_password)
        if not res["success"]:
            raise HTTPException(status_code=400, detail=res.get("error", "Emergency reset failed"))
        return res

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
