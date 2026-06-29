"""Tests for core/auth/dependencies.py - FastAPI auth dependency injection.

Covers:
- AuthDependencies init with auth_handler and role_manager
- require_auth: valid session, expired session, no session, disabled user
- require_auth_optional: returns None when no valid session
- require_role: allows/denies based on user role
- require_permission: allows/denies based on permission
- optional_auth_with_fallback: returns anonymous user with fallback role
- get_client_ip: extracts IP from headers, forwarded-for, client
"""

from __future__ import annotations

import pytest
from core.auth.dependencies import AuthDependencies, get_client_ip
from core.auth.handler import AuthHandler, AuthUser

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def auth(tmp_path) -> AuthHandler:
    """AuthHandler with isolated temp DB."""
    db_path = str(tmp_path / "test_auth.db")
    return AuthHandler(db_path=db_path)


@pytest.fixture
def deps(auth: AuthHandler) -> AuthDependencies:
    """AuthDependencies with real auth handler."""
    return AuthDependencies(auth_handler=auth)


@pytest.fixture
def test_user(auth: AuthHandler) -> AuthUser:
    """Create a test user and return it."""
    result = auth.create_user("testuser", "TestPass123!", "operator")
    assert result["success"]
    user = auth.get_user("testuser")
    assert user is not None
    return user


@pytest.fixture
def admin_user(auth: AuthHandler, test_user: AuthUser) -> AuthUser:
    """Promote the test user to admin role."""
    auth.update_user_role("testuser", "admin", "admin")
    user = auth.get_user("testuser")
    assert user is not None
    assert user.role == "admin"
    return user


# ── Mock Request ──────────────────────────────────────────────────────────────


class MockRequest:
    """Minimal mock for FastAPI Request."""

    def __init__(self, cookies=None, headers=None, client_host=None):
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.state = type("State", (), {})()
        self.client = type("Client", (), {"host": client_host})() if client_host else None


class MockRequestNoClient:
    """Request without client attribute."""

    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.state = type("State", (), {})()
        self.client = None


# ═══════════════════════════════════════════════════════════════════════════════
#  AuthDependencies Initialization
# ═══════════════════════════════════════════════════════════════════════════════


class TestInit:
    """Sync tests only - no asyncio marker needed."""
    def test_init_with_handler(self, auth: AuthHandler):
        deps = AuthDependencies(auth_handler=auth)
        assert deps._auth is auth
        assert deps._role_manager is not None

    def test_init_with_custom_role_manager(self, auth: AuthHandler):
        from core.auth.role_manager import RoleManager
        rm = RoleManager()
        deps = AuthDependencies(auth_handler=auth, role_manager=rm)
        assert deps._role_manager is rm


# ═══════════════════════════════════════════════════════════════════════════════
#  require_auth
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestRequireAuth:
    async def test_valid_session(self, deps: AuthDependencies, test_user: AuthUser):
        """Valid session should return the AuthUser."""
        token = deps._auth.create_session(test_user, "127.0.0.1")
        request = MockRequest(cookies={"opb_session": token.token})
        user = await deps.require_auth(request)
        assert user.username == "testuser"
        assert user.role == "operator"

    async def test_auth_header_fallback(self, deps: AuthDependencies, test_user: AuthUser):
        """Authorization header should work as fallback."""
        token = deps._auth.create_session(test_user)
        request = MockRequest(headers={"Authorization": f"Bearer {token.token}"})
        user = await deps.require_auth(request)
        assert user is not None
        assert user.username == "testuser"

    async def test_no_session_raises_401(self, deps: AuthDependencies):
        """No session should raise HTTPException 401."""
        from fastapi import HTTPException
        request = MockRequest()
        with pytest.raises(HTTPException) as excinfo:
            await deps.require_auth(request)
        assert excinfo.value.status_code == 401

    async def test_expired_session_raises_401(self, deps: AuthDependencies, test_user: AuthUser):
        """Expired session should raise 401."""
        token = deps._auth.create_session(test_user)
        # Manually expire the token
        token.expires_ts = 0
        request = MockRequest(cookies={"opb_session": token.token})
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            await deps.require_auth(request)
        assert excinfo.value.status_code == 401

    async def test_disabled_user_raises_403(self, deps: AuthDependencies, test_user: AuthUser):
        """Disabled user should raise 403."""
        token = deps._auth.create_session(test_user)
        deps._auth.disable_user("testuser", "admin")
        request = MockRequest(cookies={"opb_session": token.token})
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            await deps.require_auth(request)
        assert excinfo.value.status_code == 403

    async def test_stores_user_in_request_state(self, deps: AuthDependencies, test_user: AuthUser):
        """The authenticated user should be stored in request state."""
        token = deps._auth.create_session(test_user)
        request = MockRequest(cookies={"opb_session": token.token})
        await deps.require_auth(request)
        assert request.state.user is not None
        assert request.state.user.username == "testuser"

    async def test_stores_token_in_request_state(self, deps: AuthDependencies, test_user: AuthUser):
        """The auth token should be stored in request state."""
        token = deps._auth.create_session(test_user)
        request = MockRequest(cookies={"opb_session": token.token})
        await deps.require_auth(request)
        assert request.state.token is not None
        assert request.state.session_id == token.token

    async def test_blank_session_cookie_raises_401(self, deps: AuthDependencies):
        """Empty session cookie should not bypass auth."""
        request = MockRequest(cookies={"opb_session": ""})
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            await deps.require_auth(request)
        assert excinfo.value.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
#  require_auth_optional
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestRequireAuthOptional:
    async def test_valid_session_returns_user(self, deps: AuthDependencies, test_user: AuthUser):
        token = deps._auth.create_session(test_user)
        request = MockRequest(cookies={"opb_session": token.token})
        user = await deps.require_auth_optional(request)
        assert user is not None
        assert user.username == "testuser"

    async def test_no_session_returns_none(self, deps: AuthDependencies):
        request = MockRequest()
        user = await deps.require_auth_optional(request)
        assert user is None

    async def test_invalid_session_returns_none(self, deps: AuthDependencies):
        request = MockRequest(cookies={"opb_session": "invalid"})
        user = await deps.require_auth_optional(request)
        assert user is None


# ═══════════════════════════════════════════════════════════════════════════════
#  require_role
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestRequireRole:
    async def test_allowed_role(self, deps: AuthDependencies, admin_user: AuthUser):
        token = deps._auth.create_session(admin_user)
        request = MockRequest(cookies={"opb_session": token.token})
        # Get the authenticated user first, then pass to the role check
        authed_user = await deps.require_auth(request)
        dep = deps.require_role("admin")
        # FastAPI would inject authed_user via Depends; we call the inner _check_role directly
        result = await dep(authed_user)
        assert result.role == "admin"

    async def test_denied_role_raises_403(self, deps: AuthDependencies, test_user: AuthUser):
        token = deps._auth.create_session(test_user)
        request = MockRequest(cookies={"opb_session": token.token})
        authed_user = await deps.require_auth(request)
        dep = deps.require_role("admin")  # testuser is operator, not admin
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            await dep(authed_user)
        assert excinfo.value.status_code == 403

    async def test_any_of_multiple_roles(self, deps: AuthDependencies, test_user: AuthUser):
        """require_role should allow any of the specified roles."""
        token = deps._auth.create_session(test_user)
        request = MockRequest(cookies={"opb_session": token.token})
        authed_user = await deps.require_auth(request)
        dep = deps.require_role("admin", "operator")
        result = await dep(authed_user)
        assert result is not None

    async def test_case_insensitive(self, deps: AuthDependencies, test_user: AuthUser):
        token = deps._auth.create_session(test_user)
        request = MockRequest(cookies={"opb_session": token.token})
        authed_user = await deps.require_auth(request)
        dep = deps.require_role("OPERATOR")
        result = await dep(authed_user)
        assert result is not None


# ═══════════════════════════════════════════════════════════════════════════════
#  require_permission
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestRequirePermission:
    async def test_allowed_permission(self, deps: AuthDependencies, admin_user: AuthUser):
        token = deps._auth.create_session(admin_user)
        request = MockRequest(cookies={"opb_session": token.token})
        authed_user = await deps.require_auth(request)
        dep = deps.require_permission("halt_trading")
        result = await dep(authed_user)
        assert result is not None

    async def test_denied_permission_raises_403(self, deps: AuthDependencies, test_user: AuthUser):
        """Viewer/operator does not have modify_risk_limits permission."""
        token = deps._auth.create_session(test_user)
        request = MockRequest(cookies={"opb_session": token.token})
        authed_user = await deps.require_auth(request)
        dep = deps.require_permission("modify_risk_limits")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            await dep(authed_user)
        assert excinfo.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
#  optional_auth_with_fallback
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestOptionalAuthWithFallback:
    async def test_authenticated_returns_real_user(self, deps: AuthDependencies, test_user: AuthUser):
        token = deps._auth.create_session(test_user)
        request = MockRequest(cookies={"opb_session": token.token})
        dep = deps.optional_auth_with_fallback(fallback_role="viewer")
        user = await dep(request)
        assert user.username == "testuser"
        assert user.role == "operator"

    async def test_no_auth_returns_anonymous(self, deps: AuthDependencies):
        request = MockRequest()
        dep = deps.optional_auth_with_fallback(fallback_role="viewer")
        user = await dep(request)
        assert user.username == "anonymous"
        assert user.role == "viewer"

    async def test_custom_fallback_role(self, deps: AuthDependencies):
        request = MockRequest()
        dep = deps.optional_auth_with_fallback(fallback_role="observer")
        user = await dep(request)
        assert user.role == "observer"


# ═══════════════════════════════════════════════════════════════════════════════
#  get_client_ip
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetClientIp:
    def test_x_forwarded_for(self):
        request = MockRequest(headers={"x-forwarded-for": "10.0.0.1, 10.0.0.2"})
        ip = get_client_ip(request)
        assert ip == "10.0.0.1"

    def test_client_host_fallback(self):
        request = MockRequest(client_host="192.168.1.1")
        ip = get_client_ip(request)
        assert ip == "192.168.1.1"

    def test_no_client(self):
        request = MockRequestNoClient()
        ip = get_client_ip(request)
        assert ip == ""

    def test_forwarded_preferred_over_client(self):
        """x-forwarded-for should take precedence over client host."""
        request = MockRequest(
            headers={"x-forwarded-for": "10.0.0.1"},
            client_host="192.168.1.1",
        )
        ip = get_client_ip(request)
        assert ip == "10.0.0.1"
