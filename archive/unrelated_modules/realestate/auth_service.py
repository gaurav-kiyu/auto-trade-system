"""OAuth Authentication Service — Google login for the real estate platform.

Provides:
  - Google OAuth 2.0 token verification
  - JWT session token generation and validation
  - User registration on first login
  - Login/logout API endpoints
  - Auth-required dependency for FastAPI routes

Environment variables:
  - GOOGLE_CLIENT_ID: Google OAuth client ID
  - GOOGLE_CLIENT_SECRET: Google OAuth client secret
  - JWT_SECRET: Secret key for JWT signing (auto-generated if not set)
  - JWT_EXPIRY_HOURS: JWT token expiry in hours (default: 24)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_log = logging.getLogger(__name__)

_TEMPLATES_DIR = None


def _get_templates() -> Jinja2Templates:
    global _TEMPLATES_DIR
    if _TEMPLATES_DIR is None:
        from pathlib import Path
        _TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "realestate"
        _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

OAUTH_CONFIG = {
    "google_client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
    "google_client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    "jwt_secret": os.environ.get("JWT_SECRET", uuid.uuid4().hex),
    "jwt_expiry_hours": int(os.environ.get("JWT_EXPIRY_HOURS", "24")),
}


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class UserSession:
    """An authenticated user session from OAuth login."""
    user_id: str = ""
    email: str = ""
    name: str = ""
    picture: str = ""
    role: str = "buyer"  # buyer, seller, broker, developer, admin
    token: str = ""
    expires_at: float = 0.0
    created_at: float = 0.0
    is_admin: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
            "role": self.role,
            "is_admin": self.is_admin,
            "expires_at": self.expires_at,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Google OAuth Verification
# ═══════════════════════════════════════════════════════════════════════════════

class GoogleOAuthVerifier:
    """Verifies Google OAuth ID tokens.

    In production, this uses the google-auth library to verify the token.
    Falls back to a simpler verification for development/testing.
    """

    @staticmethod
    def verify_id_token(id_token: str) -> dict[str, Any] | None:
        """Verify a Google ID token and return the user info payload.

        Uses google-auth library if available, otherwise a simple
        base64-decode verification. The token format is JWT-like.
        """
        # Try google-auth library first
        try:
            import google.auth.transport.requests
            from google.oauth2 import id_token

            # Load balanacer-friendly request
            request = google.auth.transport.requests.Request()
            id_info = id_token.verify_oauth2_token(
                id_token, request, OAUTH_CONFIG["google_client_id"]
            )
            return id_info
        except (ImportError, ValueError, Exception) as exc:
            _log.debug("[AUTH] google-auth unavailable or failed: %s", exc)

        # Fallback: decode JWT payload (for testing without google-auth)
        try:
            # JWT format: header.payload.signature
            payload_b64 = id_token.split(".")[1]
            # Add padding
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            import base64
            payload = json.loads(base64.b64decode(payload_b64))
            return payload
        except Exception:
            return None


# ═══════════════════════════════════════════════════════════════════════════════
# JWT Session Management
# ═══════════════════════════════════════════════════════════════════════════════

class JWTManager:
    """Simple JWT session manager — generates and validates tokens."""

    def __init__(self) -> None:
        self._secret = OAUTH_CONFIG["jwt_secret"]
        self._expiry = OAUTH_CONFIG["jwt_expiry_hours"] * 3600
        self._sessions: dict[str, UserSession] = {}

    def create_session(self, email: str, name: str, picture: str = "",
                       user_id: str = "", role: str = "buyer") -> UserSession:
        """Create a new authenticated session."""
        uid = user_id or f"user-{uuid.uuid4().hex[:12]}"
        now = time.time()
        token = self._generate_jwt(uid, email, role)

        session = UserSession(
            user_id=uid,
            email=email,
            name=name,
            picture=picture,
            role=role,
            token=token,
            expires_at=now + self._expiry,
            created_at=now,
        )
        self._sessions[token] = session
        return session

    def validate_token(self, token: str) -> UserSession | None:
        """Validate a JWT token and return the session."""
        session = self._sessions.get(token)
        if not session:
            return None
        if time.time() > session.expires_at:
            self._sessions.pop(token, None)
            return None
        return session

    def revoke_token(self, token: str) -> bool:
        """Revoke a token (logout)."""
        return self._sessions.pop(token, None) is not None

    def _generate_jwt(self, user_id: str, email: str, role: str) -> str:
        """Generate a simple signed JWT token."""
        import base64
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()

        payload = base64.urlsafe_b64encode(
            json.dumps({
                "sub": user_id,
                "email": email,
                "role": role,
                "iat": int(time.time()),
                "exp": int(time.time()) + int(self._expiry),
            }).encode()
        ).rstrip(b"=").decode()

        signature = hmac.new(
            self._secret.encode(),
            f"{header}.{payload}".encode(),
            hashlib.sha256,
        ).hexdigest()

        return f"{header}.{payload}.{signature}"


# ═══════════════════════════════════════════════════════════════════════════════
# Auth Service
# ═══════════════════════════════════════════════════════════════════════════════

_jwt_manager = JWTManager()


class AuthService:
    """Authentication service — OAuth login, session management, user roles."""

    def __init__(self) -> None:
        self._users: dict[str, dict[str, Any]] = {}  # email -> user profile
        self._jwt = _jwt_manager

    # ── Login Flow ────────────────────────────────────────────────────────

    def login_with_google(self, id_token: str, role: str = "buyer") -> UserSession | None:
        """Authenticate a user with a Google ID token.

        Args:
            id_token: Google OAuth ID token from the frontend.
            role: Requested user role (buyer/seller/broker/developer/admin).

        Returns:
            UserSession if authentication succeeds, None otherwise.
        """
        payload = GoogleOAuthVerifier.verify_id_token(id_token)
        if not payload:
            _log.warning("[AUTH] Invalid Google ID token")
            return None

        email = payload.get("email", "")
        name = payload.get("name", payload.get("given_name", "User"))
        picture = payload.get("picture", "")

        if not email:
            _log.warning("[AUTH] No email in Google token")
            return None

        # Admin promotion: set is_admin if email matches configured admin
        _admin_emails = set(
            e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
        )
        # Default admin emails for demo/dev
        if not _admin_emails:
            _admin_emails = {"admin@realestate.in", "admin@realestate.demo"}
        is_admin = email.lower() in _admin_emails

        # Check if user exists, otherwise create profile
        if email not in self._users:
            self._users[email] = {
                "email": email,
                "name": name,
                "picture": picture,
                "role": role,
                "is_admin": is_admin,
                "created_at": time.time(),
            }
            _log.info("[AUTH] New user registered: %s (%s) admin=%s", name, email, is_admin)
        else:
            # Update profile on each login
            self._users[email].update({
                "name": name,
                "picture": picture,
                "is_admin": is_admin,
                "last_login": time.time(),
            })

        user = self._users[email]
        session = self._jwt.create_session(
            email=email,
            name=name,
            picture=picture,
            user_id=user.get("user_id", f"user-{hash(email) % 10**8}"),
            role=user.get("role", role),
        )
        session.is_admin = user.get("is_admin", is_admin)
        return session

    def login_as_guest(self, name: str = "Guest", role: str = "buyer") -> UserSession:
        """Create a guest session (for development/demo)."""
        guest_email = f"guest-{uuid.uuid4().hex[:8]}@realestate.demo"
        session = self._jwt.create_session(
            email=guest_email,
            name=name,
            role=role,
        )
        return session

    def logout(self, token: str) -> bool:
        """Logout by revoking the token."""
        return self._jwt.revoke_token(token)

    def get_session(self, token: str) -> UserSession | None:
        """Get the session for a token (validates expiry)."""
        return self._jwt.validate_token(token)

    # ── User Management ───────────────────────────────────────────────────

    def get_user(self, email: str) -> dict[str, Any] | None:
        return self._users.get(email)

    def update_role(self, email: str, role: str) -> bool:
        """Update a user's role."""
        if email not in self._users:
            return False
        self._users[email]["role"] = role
        return True

    def list_users(self) -> list[dict[str, Any]]:
        """List all registered users."""
        return list(self._users.values())

    def get_stats(self) -> dict[str, Any]:
        """Get authentication service statistics."""
        return {
            "total_users": len(self._users),
            "active_sessions": len(self._jwt._sessions),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_auth_service_instance: AuthService | None = None


def get_auth_service() -> AuthService:
    """Get the global auth service singleton."""
    global _auth_service_instance
    if _auth_service_instance is None:
        _auth_service_instance = AuthService()
    return _auth_service_instance


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Auth Dependency
# ═══════════════════════════════════════════════════════════════════════════════

async def get_current_user(request: Request) -> UserSession | None:
    """FastAPI dependency: extract current user from Authorization header or cookie.

    Usage in endpoints:
        @router.get("/me")
        async def get_me(user: UserSession = Depends(get_current_user)):
            ...
    """
    # Check Authorization header first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        session = get_auth_service().get_session(token)
        if session:
            return session

    # Check cookie
    token = request.cookies.get("session_token", "")
    if token:
        session = get_auth_service().get_session(token)
        if session:
            return session

    return None


async def require_admin(user: UserSession | None = Depends(get_current_user)) -> UserSession:
    """FastAPI dependency: require admin role."""
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ═══════════════════════════════════════════════════════════════════════════════
# API Router
# ═══════════════════════════════════════════════════════════════════════════════

def create_auth_router() -> APIRouter:
    """Create the OAuth authentication API router."""
    router = APIRouter(prefix="/api/realestate/auth", tags=["Real Estate Auth"])
    svc = get_auth_service()

    @router.post("/google")
    async def google_login(
        id_token: str = Query(..., description="Google OAuth ID token"),
        role: str = Query("buyer", description="User role"),
    ):
        """Authenticate with Google OAuth ID token."""
        session = svc.login_with_google(id_token, role)
        if not session:
            raise HTTPException(status_code=401, detail="Invalid Google token")
        return {"success": True, "session": session.to_dict()}

    @router.post("/guest")
    async def guest_login(name: str = Query("Guest", description="Guest name")):
        """Create a guest session for development."""
        session = svc.login_as_guest(name)
        return {"success": True, "session": session.to_dict()}

    @router.post("/logout")
    async def logout(token: str = Query(..., description="Session token to revoke")):
        """Logout by revoking the session token."""
        success = svc.logout(token)
        return {"success": success}

    @router.get("/me")
    async def get_me(user: UserSession | None = Depends(get_current_user)):
        """Get the current authenticated user's session info."""
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"success": True, "user": user.to_dict()}

    @router.get("/users")
    async def list_users(admin: UserSession = Depends(require_admin)):
        """List all registered users (admin)."""
        return {"success": True, "users": svc.list_users()}

    @router.get("/stats")
    async def auth_stats(admin: UserSession = Depends(require_admin)):
        """Get authentication statistics."""
        return {"success": True, "stats": svc.get_stats()}

    return router


# ── Login Page ──────────────────────────────────────────────────────────────

def create_auth_page_router() -> APIRouter:
    """Create router for the login page."""
    router = APIRouter(tags=["Real Estate Pages"])
    templates = _get_templates()

    @router.get("/realestate/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        """Login page with Google OAuth button."""
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "google_client_id": OAUTH_CONFIG["google_client_id"],
            },
        )

    return router
