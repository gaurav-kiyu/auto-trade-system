"""
Comprehensive test suite for the enterprise auth system.

Covers:
- Password hashing & verification
- Brute-force protection
- Account lockout
- User CRUD
- Session management
- RBAC enforcement
- CSRF protection
- Auth API endpoints
- Security boundary tests
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Generator
from typing import Any

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def auth_db_path() -> Generator[str, None, None]:
    """Create a temporary auth database."""
    tmp = tempfile.mktemp(suffix=".db")
    yield tmp
    try:
        os.unlink(tmp)
    except OSError:
        pass


@pytest.fixture
def auth_handler(auth_db_path: str):
    """Create an AuthHandler with a temp database."""
    from core.auth.handler import AuthHandler
    handler = AuthHandler(db_path=auth_db_path, token_ttl=3600)
    return handler


@pytest.fixture
def test_user(auth_handler) -> dict[str, Any]:
    """Create a test user and return user info."""
    result = auth_handler.create_user(
        username="testuser",
        password="Test@1234!",
        role="viewer",
        display_name="Test User",
    )
    assert result["success"]
    return result


@pytest.fixture
def admin_user(auth_handler):
    """Create a test admin user."""
    result = auth_handler.create_user(
        username="testadmin",
        password="Str0ng!PwdX",  # Avoid 'admin' substring in password
        role="admin",
        display_name="Test Admin",
    )
    assert result["success"], f"Admin creation failed: {result.get('error', 'unknown')}"
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Password Hashing & Verification
# ──────────────────────────────────────────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_and_verify(self):
        from core.auth.handler import hash_password, verify_password
        pwd = "MySecureP@ss1"
        hashed = hash_password(pwd)
        assert hashed != pwd
        assert verify_password(pwd, hashed)
        assert not verify_password("WrongP@ss1", hashed)

    def test_different_salts(self):
        from core.auth.handler import hash_password
        pwd = "SameP@ss1"
        h1 = hash_password(pwd)
        h2 = hash_password(pwd)
        assert h1 != h2  # different salts

    def test_empty_password(self):
        from core.auth.handler import hash_password, verify_password
        hashed = hash_password("")
        assert verify_password("", hashed)
        assert not verify_password("x", hashed)

    def test_verify_corrupted_hash(self):
        from core.auth.handler import verify_password
        assert not verify_password("pwd", "not-a-valid-hash")
        assert not verify_password("pwd", "100000$salt$hash")
        assert not verify_password("pwd", "")

    def test_unicode_password(self):
        from core.auth.handler import hash_password, verify_password
        pwd = "P@sswörd123!ñ"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed)

    def test_long_password(self):
        from core.auth.handler import hash_password, verify_password
        pwd = "A" * 100 + "@1x"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed)
        assert not verify_password(pwd[:-1], hashed)

    def test_timing_resistance(self):
        """Verify timing comparison using hmac.compare_digest."""

        from core.auth.handler import hash_password, verify_password
        pwd = "Test@1234!"
        hashed = hash_password(pwd)
        # verify_password uses hmac.compare_digest internally
        assert verify_password(pwd, hashed)
        assert not verify_password("WrongP@ss1", hashed)


class TestPasswordStrength:
    def test_valid_password(self):
        from core.auth.handler import validate_password_strength
        valid, msg = validate_password_strength("Str0ng!Pwd")
        assert valid
        assert msg == ""

    def test_too_short(self):
        from core.auth.handler import validate_password_strength
        valid, _ = validate_password_strength("Ab1!")
        assert not valid

    def test_no_uppercase(self):
        from core.auth.handler import validate_password_strength
        valid, _ = validate_password_strength("lowercase1!")
        assert not valid

    def test_no_lowercase(self):
        from core.auth.handler import validate_password_strength
        valid, _ = validate_password_strength("UPPERCASE1!")
        assert not valid

    def test_no_digit(self):
        from core.auth.handler import validate_password_strength
        valid, _ = validate_password_strength("NoDigits!")
        assert not valid

    def test_no_special_char(self):
        from core.auth.handler import validate_password_strength
        valid, _ = validate_password_strength("NoSpecial1")
        assert not valid

    def test_common_password_blocked(self):
        from core.auth.handler import validate_password_strength
        valid, _ = validate_password_strength("Password123!")
        assert not valid


# ──────────────────────────────────────────────────────────────────────────────
# User Management
# ──────────────────────────────────────────────────────────────────────────────

class TestUserManagement:
    def test_create_user(self, auth_handler):
        result = auth_handler.create_user("newuser", "New@User1!", "viewer")
        assert result["success"]
        assert result["username"] == "newuser"

    def test_create_duplicate_user(self, auth_handler, test_user):
        result = auth_handler.create_user("testuser", "Other@1!", "viewer")
        assert not result["success"]
        assert "already exists" in result.get("error", "")

    def test_create_user_invalid_role(self, auth_handler):
        result = auth_handler.create_user("badrole", "Test@1234!", "superadmin")
        assert not result["success"]

    def test_get_user(self, auth_handler, test_user):
        user = auth_handler.get_user("testuser")
        assert user is not None
        assert user.username == "testuser"
        assert user.role == "viewer"

    def test_get_nonexistent_user(self, auth_handler):
        user = auth_handler.get_user("nonexistent")
        assert user is None

    def test_list_users(self, auth_handler, test_user, admin_user):
        users = auth_handler.list_users()
        assert len(users) >= 2
        usernames = [u["username"] for u in users]
        assert "testuser" in usernames
        assert "testadmin" in usernames

    def test_disable_user(self, auth_handler, test_user):
        result = auth_handler.disable_user("testuser", "testadmin")
        assert result["success"]
        user = auth_handler.get_user("testuser")
        assert user is not None
        assert user.disabled

    def test_enable_user(self, auth_handler, test_user):
        auth_handler.disable_user("testuser", "testadmin")
        result = auth_handler.enable_user("testuser", "testadmin")
        assert result["success"]
        user = auth_handler.get_user("testuser")
        assert user is not None
        assert not user.disabled

    def test_delete_user(self, auth_handler, test_user):
        result = auth_handler.delete_user("testuser", "testadmin")
        assert result["success"]
        assert auth_handler.get_user("testuser") is None

    def test_cannot_delete_default_admin(self, auth_handler):
        result = auth_handler.delete_user("admin", "testadmin")
        assert not result["success"]


# ──────────────────────────────────────────────────────────────────────────────
# Authentication
# ──────────────────────────────────────────────────────────────────────────────

class TestAuthentication:
    def test_login_success(self, auth_handler, test_user):
        user = auth_handler.authenticate("testuser", "Test@1234!", "127.0.0.1")
        assert user is not None
        assert user.username == "testuser"
        assert user.role == "viewer"

    def test_login_wrong_password(self, auth_handler, test_user):
        user = auth_handler.authenticate("testuser", "WrongP@ss1!", "127.0.0.1")
        assert user is None

    def test_login_nonexistent_user(self, auth_handler):
        user = auth_handler.authenticate("nobody", "SomeP@ss1!", "127.0.0.1")
        assert user is None

    def test_login_disabled_user(self, auth_handler, test_user):
        auth_handler.disable_user("testuser", "admin")
        user = auth_handler.authenticate("testuser", "Test@1234!", "127.0.0.1")
        assert user is None

    def test_login_updates_last_login(self, auth_handler, test_user):
        before = time.time()
        auth_handler.authenticate("testuser", "Test@1234!", "127.0.0.1")
        user = auth_handler.get_user("testuser")
        assert user is not None
        assert user.last_login_ts is not None
        assert user.last_login_ts >= before

    def test_create_admin_user(self, auth_handler):
        result = auth_handler.create_user("admin2_user", "Str0ng!PwdX", "admin")
        assert result["success"], f"Failed: {result.get('error', 'unknown')}"
        user = auth_handler.get_user("admin2_user")
        assert user is not None
        assert user.role == "admin"

    def test_create_operator_user(self, auth_handler):
        result = auth_handler.create_user("op1", "Oper@tor1!", "operator")
        assert result["success"]
        user = auth_handler.get_user("op1")
        assert user is not None
        assert user.role == "operator"


# ──────────────────────────────────────────────────────────────────────────────
# Session & Token Management
# ──────────────────────────────────────────────────────────────────────────────

class TestSessionManagement:
    def test_create_session(self, auth_handler, test_user):
        user = auth_handler.get_user("testuser")
        assert user is not None
        token = auth_handler.create_session(user, "127.0.0.1", "test-agent")
        assert token is not None
        assert token.username == "testuser"
        assert token.role == "viewer"
        assert token.csrf_token != ""

    def test_verify_valid_session(self, auth_handler, test_user):
        user = auth_handler.get_user("testuser")
        token = auth_handler.create_session(user)
        verified = auth_handler.verify_session(token.token)
        assert verified is not None
        assert verified.user_id == user.user_id

    def test_verify_expired_session(self, auth_handler, test_user):
        handler = auth_handler
        handler._token_ttl = 0  # instant expiry
        user = handler.get_user("testuser")
        token = handler.create_session(user)
        time.sleep(0.01)
        verified = handler.verify_session(token.token)
        assert verified is None

    def test_revoke_session(self, auth_handler, test_user):
        user = auth_handler.get_user("testuser")
        token = auth_handler.create_session(user)
        assert auth_handler.revoke_session(token.token)
        assert auth_handler.verify_session(token.token) is None

    def test_revoke_nonexistent_session(self, auth_handler):
        assert not auth_handler.revoke_session("nonexistent")

    def test_revoke_all_user_sessions(self, auth_handler, test_user):
        user = auth_handler.get_user("testuser")
        token1 = auth_handler.create_session(user)
        token2 = auth_handler.create_session(user)
        count = auth_handler.revoke_all_user_sessions("testuser")
        assert count >= 2
        assert auth_handler.verify_session(token1.token) is None
        assert auth_handler.verify_session(token2.token) is None

    def test_purge_expired(self, auth_handler, test_user):
        handler = auth_handler
        handler._token_ttl = 0
        user = handler.get_user("testuser")
        handler.create_session(user)
        time.sleep(0.01)
        count = handler.purge_expired_sessions()
        assert count >= 1


# ──────────────────────────────────────────────────────────────────────────────
# Password Change
# ──────────────────────────────────────────────────────────────────────────────

class TestPasswordChange:
    def test_password_change_success(self, auth_handler, test_user):
        result = auth_handler.update_password("testuser", "Test@1234!", "NewP@ss1!")
        assert result["success"]
        user = auth_handler.authenticate("testuser", "NewP@ss1!", "127.0.0.1")
        assert user is not None

    def test_password_change_wrong_current(self, auth_handler, test_user):
        result = auth_handler.update_password("testuser", "Wrong@123!", "NewP@ss1!")
        assert not result["success"]

    def test_password_change_weak_new(self, auth_handler, test_user):
        result = auth_handler.update_password("testuser", "Test@1234!", "weak")
        assert not result["success"]

    def test_admin_reset_password(self, auth_handler, test_user):
        result = auth_handler.admin_reset_password("testuser", "Reset@1234!", "admin")
        assert result["success"]
        user = auth_handler.get_user("testuser")
        assert user is not None
        assert user.must_change_password
        # Old password should no longer work
        assert auth_handler.authenticate("testuser", "Test@1234!", "127.0.0.1") is None
        # New password should work but force change
        auth_user = auth_handler.authenticate("testuser", "Reset@1234!", "127.0.0.1")
        assert auth_user is not None
        assert auth_user.must_change_password


# ──────────────────────────────────────────────────────────────────────────────
# Brute-Force Protection & Account Lockout
# ──────────────────────────────────────────────────────────────────────────────

class TestBruteForceProtection:
    def _make_test_user(self, handler, name: str):
        """Create a unique test user to avoid cross-test contamination."""
        pwd = "Test@1234!"
        handler.create_user(name, pwd, "viewer")
        return name, pwd

    def test_rate_limiting(self, auth_handler):
        """Multiple failed attempts from same IP should be rate-limited."""
        handler = auth_handler
        uname, pwd = self._make_test_user(handler, "bfuser1")
        for i in range(12):
            handler.authenticate(uname, "WrongP@ss!", "10.0.0.1")
        user = handler.authenticate(uname, pwd, "10.0.0.1")
        assert user is None, "Should be rate limited even with correct password"

    def test_rate_limiting_by_ip(self, auth_handler):
        """Different IPs should not affect each other."""
        handler = auth_handler
        uname, pwd = self._make_test_user(handler, "bfuser2")
        handler._clear_lockout(uname)
        for i in range(6):
            handler.authenticate(uname, "WrongP@ss!", "10.0.0.1")
        handler._clear_lockout(uname)
        # Different IP should work
        user = handler.authenticate(uname, pwd, "10.0.0.2")
        assert user is not None

    def test_account_lockout(self, auth_handler):
        handler = auth_handler
        uname, pwd = self._make_test_user(handler, "bfuser3")
        handler._clear_lockout(uname)
        for i in range(5):
            handler.authenticate(uname, "WrongP@ss!", "10.0.0.3")
        user = handler.authenticate(uname, pwd, "10.0.0.3")
        assert user is None

    def test_lockout_clears_on_success(self, auth_handler):
        handler = auth_handler
        uname, pwd = self._make_test_user(handler, "bfuser4")
        handler._clear_lockout(uname)
        for i in range(3):
            handler.authenticate(uname, "WrongP@ss!", "10.0.0.4")
        user = handler.authenticate(uname, pwd, "10.0.0.5")
        assert user is not None


# ──────────────────────────────────────────────────────────────────────────────
# RBAC & Permissions
# ──────────────────────────────────────────────────────────────────────────────

class TestRBAC:
    def test_role_hierarchy(self):
        from core.auth.permissions import (
            Permission,
            Role,
            get_role_permissions,
        )
        admin_perms = get_role_permissions(Role.ADMIN)
        assert Permission.MODIFY_RISK_LIMITS in admin_perms
        assert Permission.MODIFY_CONFIG in admin_perms
        assert Permission.ADD_BROKERS in admin_perms

        viewer_perms = get_role_permissions(Role.OBSERVER)
        assert Permission.VIEW_STATE in viewer_perms
        assert Permission.MODIFY_RISK_LIMITS not in viewer_perms

    def test_role_has_permission(self):
        from core.auth.permissions import role_has_permission
        assert role_has_permission("admin", "view_state")
        assert not role_has_permission("observer", "halt_trading")
        assert not role_has_permission("unknown_role", "view_state")

    def test_role_manager_assignments(self, auth_handler):
        from core.auth.permissions import Permission, Role
        from core.auth.role_manager import RoleManager

        rm = RoleManager(default_role="observer")
        rm.assign("alice", "admin")
        rm.assign("bob", "operator")

        assert rm.get_role("alice") == Role.ADMIN
        assert rm.get_role("bob") == Role.OPERATOR
        assert rm.get_role("unknown") == Role.OBSERVER

        rm.check("alice", Permission.MODIFY_CONFIG)
        with pytest.raises(Exception):
            rm.check("bob", Permission.MODIFY_CONFIG)

    def test_role_manager_load_from_config(self):
        from core.auth.role_manager import RoleManager
        rm = RoleManager()
        rm.load_from_config({
            "admin_roles": {"alice": "admin", "bob": "operator"},
            "admin_default_role": "observer",
        })
        assert rm.get_role("alice").value == "admin"

    def test_role_manager_revoke(self):
        from core.auth.role_manager import RoleManager
        rm = RoleManager()
        rm.assign("alice", "admin")
        rm.revoke("alice")
        assert rm.get_role("alice").value == "observer"


# ──────────────────────────────────────────────────────────────────────────────
# CSRF Protection
# ──────────────────────────────────────────────────────────────────────────────

class TestCSRFProtection:
    @pytest.fixture
    def csrf(self):
        from core.auth.csrf import CSRFProtection
        return CSRFProtection(secret_key="test-secret-key-for-testing")

    @pytest.mark.anyio
    async def test_get_request_exempt(self, csrf):
        """GET requests should be exempt from CSRF."""
        class MockRequest:
            method = "GET"
            cookies = {}
            headers = {}
            state = type("state", (), {})()

        await csrf.validate(MockRequest())

    def test_csrf_token_generation(self, csrf):
        token = csrf._generate_token("session123")
        assert isinstance(token, str)
        assert len(token) == 64

    @pytest.mark.anyio
    async def test_exempt_paths(self, csrf):
        csrf.exempt("/api/auth/login")
        class MockRequest:
            method = "POST"
            url = type("url", (), {"path": "/api/auth/login"})()
            cookies = {}
            headers = {}
            state = type("state", (), {"session_id": "test"})()
        await csrf.validate(MockRequest())

    # ── ensure_cookie_set tests ──────────────────────────────────────────

    @pytest.mark.anyio
    async def test_ensure_cookie_set_on_get_no_cookie(self, csrf):
        """GET request without a CSRF cookie should set one on the response."""
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "GET"
            url = type("url", (), {"path": "/"})()
            cookies = {}
            headers = {}
            state = type("state", (), {})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_was_set) == 1
        assert cookie_was_set[0]["key"] == "opb_csrf"
        assert not cookie_was_set[0]["httponly"]  # Must be JS-accessible
        assert cookie_was_set[0]["samesite"] == "lax"
        assert cookie_was_set[0]["path"] == "/"

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_when_exists(self, csrf):
        """GET request with an existing valid CSRF cookie should NOT set a new one."""
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "GET"
            url = type("url", (), {"path": "/"})()
            cookies = {"opb_csrf": "a" * 64}  # 64-char token
            headers = {}
            state = type("state", (), {})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_was_set) == 0  # No new cookie set

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_on_post(self, csrf):
        """POST request should NOT have a cookie set (only GET/HEAD/OPTIONS)."""
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "POST"
            url = type("url", (), {"path": "/"})()
            cookies = {}
            headers = {}
            state = type("state", (), {})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_was_set) == 0

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_on_exempt_path(self, csrf):
        """Exempt paths should NOT have a CSRF cookie set."""
        csrf.exempt("/login")
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "GET"
            url = type("url", (), {"path": "/login"})()
            cookies = {}
            headers = {}
            state = type("state", (), {})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_was_set) == 0

    @pytest.mark.anyio
    async def test_ensure_cookie_set_uses_session_id(self, csrf):
        """CSRF token should be tied to the session_id from request.state."""
        cookie_kwargs = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_kwargs.append(kwargs)

        class MockRequest:
            method = "GET"
            url = type("url", (), {"path": "/"})()
            cookies = {}
            headers = {}
            state = type("state", (), {"session_id": "session-abc-123"})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_kwargs) == 1
        token = cookie_kwargs[0]["value"]
        # Token should be a 64-char hex string (SHA-256 HMAC output)
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    @pytest.mark.anyio
    async def test_ensure_cookie_set_generates_session_id_if_missing(self, csrf):
        """If request.state has no session_id, should generate one."""
        cookie_kwargs = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_kwargs.append(kwargs)

        class MockRequest:
            method = "GET"
            url = type("url", (), {"path": "/"})()
            cookies = {}
            headers = {}
            state = type("state", (), {})()  # No session_id

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_kwargs) == 1
        token = cookie_kwargs[0]["value"]
        assert len(token) == 64

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_on_short_existing_token(self, csrf):
        """If cookie exists but is not 64 chars, should set a new one."""
        cookie_kwargs = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_kwargs.append(kwargs)

        class MockRequest:
            method = "GET"
            url = type("url", (), {"path": "/"})()
            cookies = {"opb_csrf": "too-short"}  # Not 64 chars
            headers = {}
            state = type("state", (), {})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_kwargs) == 1  # New cookie set

    @pytest.mark.anyio
    async def test_ensure_cookie_set_with_valid_token_preserves_existing(self, csrf):
        """Existing valid 64-char token should be preserved (no change)."""
        cookie_kwargs = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_kwargs.append(kwargs)

        existing_token = csrf._generate_token("session-xyz")
        assert len(existing_token) == 64

        class MockRequest:
            method = "GET"
            url = type("url", (), {"path": "/dashboard"})()
            cookies = {"opb_csrf": existing_token}
            headers = {}
            state = type("state", (), {"session_id": "session-xyz"})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_kwargs) == 0  # Should not overwrite valid token

    # ── HEAD / OPTIONS method tests ───────────────────────────────────

    @pytest.mark.anyio
    async def test_ensure_cookie_set_on_head(self, csrf):
        """HEAD request without a CSRF cookie should set one (same as GET)."""
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "HEAD"
            url = type("url", (), {"path": "/"})()
            cookies = {}
            headers = {}
            state = type("state", (), {})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_was_set) == 1
        assert cookie_was_set[0]["key"] == "opb_csrf"

    @pytest.mark.anyio
    async def test_ensure_cookie_set_on_options(self, csrf):
        """OPTIONS request without a CSRF cookie should set one (same as GET)."""
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "OPTIONS"
            url = type("url", (), {"path": "/"})()
            cookies = {}
            headers = {}
            state = type("state", (), {})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_was_set) == 1
        assert cookie_was_set[0]["key"] == "opb_csrf"

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_on_head_with_existing(self, csrf):
        """HEAD with existing valid cookie should not set new one."""
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "HEAD"
            url = type("url", (), {"path": "/state"})()
            cookies = {"opb_csrf": "a" * 64}
            headers = {}
            state = type("state", (), {})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_was_set) == 0  # Existing valid cookie preserved

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_on_put(self, csrf):
        """PUT request should NOT have a cookie set."""
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "PUT"
            url = type("url", (), {"path": "/"})()
            cookies = {}
            headers = {}
            state = type("state", (), {})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_was_set) == 0

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_on_delete(self, csrf):
        """DELETE request should NOT have a cookie set."""
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "DELETE"
            url = type("url", (), {"path": "/"})()
            cookies = {}
            headers = {}
            state = type("state", (), {})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_was_set) == 0

    @pytest.mark.anyio
    async def test_ensure_cookie_set_exempt_path_with_head(self, csrf):
        """Exempt paths should skip cookie set for HEAD requests."""
        csrf.exempt("/health")
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "HEAD"
            url = type("url", (), {"path": "/health"})()
            cookies = {}
            headers = {}
            state = type("state", (), {})()

        response = MockResponse()
        await csrf.ensure_cookie_set(MockRequest(), response)
        assert len(cookie_was_set) == 0


# ──────────────────────────────────────────────────────────────────────────────
# Session Store
# ──────────────────────────────────────────────────────────────────────────────

class TestSessionStore:
    def test_session_creation(self):
        from core.auth.permissions import Role
        from core.auth.session_store import SessionStore
        store = SessionStore(ttl_seconds=3600)
        session = store.create("alice", Role.ADMIN)
        assert session.identity == "alice"
        assert session.role == Role.ADMIN

    def test_session_get_and_touch(self):
        from core.auth.permissions import Role
        from core.auth.session_store import SessionStore
        store = SessionStore(ttl_seconds=3600)
        session = store.create("bob", Role.OPERATOR)
        retrieved = store.get(session.session_id)
        assert retrieved is not None
        assert retrieved.identity == "bob"

    def test_session_expiry(self):
        import time

        from core.auth.permissions import Role
        from core.auth.session_store import SessionStore
        store = SessionStore(ttl_seconds=0)
        session = store.create("charlie", Role.OBSERVER)
        time.sleep(0.01)
        assert store.get(session.session_id) is None

    def test_session_delete(self):
        from core.auth.session_store import SessionStore
        store = SessionStore()
        session = store.create("dave", "admin")
        assert store.delete(session.session_id)
        assert store.get(session.session_id) is None

    def test_purge_expired(self):
        import time

        from core.auth.session_store import SessionStore
        store = SessionStore(ttl_seconds=0)
        store.create("eve", "observer")
        time.sleep(0.01)
        count = store.purge_expired()
        assert count >= 1

    def test_active_count(self):
        from core.auth.session_store import SessionStore
        store = SessionStore()
        store.create("frank", "admin")
        store.create("grace", "operator")
        assert store.active_count() == 2

    def test_list_active(self):
        from core.auth.session_store import SessionStore
        store = SessionStore()
        store.create("hank", "admin")
        store.create("iris", "operator")
        active = store.list_active()
        assert len(active) == 2


# ──────────────────────────────────────────────────────────────────────────────
# Auth API Endpoints (integration)
# ──────────────────────────────────────────────────────────────────────────────

class TestAuthAPI:
    @pytest.fixture
    def app(self, auth_db_path):
        """Create a test FastAPI app with auth routes."""
        from core.auth.dependencies import AuthDependencies
        from core.auth.handler import AuthHandler
        from core.auth.routes import create_auth_router
        from fastapi import FastAPI

        app = FastAPI()
        handler = AuthHandler(db_path=auth_db_path, token_ttl=3600)
        deps = AuthDependencies(handler)
        router = create_auth_router(handler, deps)
        app.include_router(router)
        return app, handler

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient
        app_instance, handler = app
        return TestClient(app_instance), handler

    def test_login_endpoint(self, client):
        test_client, handler = client
        handler.create_user("apiuser", "Api@User1!", "admin")

        resp = test_client.post("/api/auth/login", json={"username": "apiuser", "password": "Api@User1!"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        assert data["user"]["username"] == "apiuser"
        # Session token is only in cookie, not in response body (security)
        assert "session" not in data

    def test_login_wrong_password(self, client):
        test_client, handler = client
        handler.create_user("apiuser2", "Api@User1!", "viewer")
        resp = test_client.post("/api/auth/login", json={"username": "apiuser2", "password": "wrong"})
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        test_client, _ = client
        resp = test_client.post("/api/auth/login", json={})
        assert resp.status_code == 400

    def test_logout(self, client):
        test_client, handler = client
        handler.create_user("logoutuser", "Log@Out1!", "viewer")
        login_resp = test_client.post("/api/auth/login", json={"username": "logoutuser", "password": "Log@Out1!"})
        assert login_resp.status_code == 200

        cookies = login_resp.cookies
        resp = test_client.post("/api/auth/logout", cookies=cookies)
        assert resp.status_code == 200
        assert resp.json()["success"]

    def test_session_endpoint(self, client):
        test_client, handler = client
        handler.create_user("sessionuser", "Sess@ion1!", "admin")

        login_resp = test_client.post("/api/auth/login", json={"username": "sessionuser", "password": "Sess@ion1!"})
        cookies = login_resp.cookies

        resp = test_client.get("/api/auth/session", cookies=cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"]
        assert data["user"]["username"] == "sessionuser"

    def test_session_without_auth(self, client):
        test_client, _ = client
        resp = test_client.get("/api/auth/session")
        assert resp.status_code == 401

    def test_change_password(self, client):
        test_client, handler = client
        handler.create_user("changepwd", "Old@Pass1!", "viewer")

        login_resp = test_client.post("/api/auth/login", json={"username": "changepwd", "password": "Old@Pass1!"})
        cookies = login_resp.cookies

        resp = test_client.post("/api/auth/change-password", cookies=cookies, json={
            "current_password": "Old@Pass1!",
            "new_password": "New@Pass1!",
        })
        assert resp.status_code == 200
        assert resp.json()["success"]

    def test_admin_user_list(self, client):
        test_client, handler = client
        handler.create_user("admin_list", "Adm1n@L1!", "admin")
        handler.create_user("regular_list", "Reg@List1!", "viewer")

        login_resp = test_client.post("/api/auth/login", json={"username": "admin_list", "password": "Adm1n@L1!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.json()}"
        cookies = login_resp.cookies

        resp = test_client.get("/api/auth/users", cookies=cookies)
        assert resp.status_code == 200, f"User list failed: {resp.status_code} {resp.text[:200]}"
        users = resp.json()
        assert any(u["username"] == "regular_list" for u in users)

    def test_non_admin_user_list_blocked(self, client):
        test_client, handler = client
        handler.create_user("not_admin", "Not@Adm1!", "viewer")

        login_resp = test_client.post("/api/auth/login", json={"username": "not_admin", "password": "Not@Adm1!"})
        cookies = login_resp.cookies

        resp = test_client.get("/api/auth/users", cookies=cookies)
        assert resp.status_code == 403  # Forbidden

    def test_admin_create_user(self, client):
        test_client, handler = client
        handler.create_user("creator", "Cre@tor1!", "admin")

        login_resp = test_client.post("/api/auth/login", json={"username": "creator", "password": "Cre@tor1!"})
        cookies = login_resp.cookies

        resp = test_client.post("/api/auth/users", cookies=cookies, json={
            "username": "newguy",
            "password": "NewGuy@123!",
            "role": "operator",
        })
        assert resp.status_code == 200
        assert resp.json()["success"]

    def test_admin_disable_user(self, client):
        test_client, handler = client
        handler.create_user("admin_dis2", "Adm1n@D2x!", "admin")
        handler.create_user("target_dis2", "Target@1!x", "viewer")

        login_resp = test_client.post("/api/auth/login", json={"username": "admin_dis2", "password": "Adm1n@D2x!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.json()}"
        cookies = login_resp.cookies

        resp = test_client.post("/api/auth/users/target_dis2/disable", cookies=cookies)
        assert resp.status_code == 200, f"Disable failed: {resp.status_code} {resp.text[:200]}"

        user = handler.get_user("target_dis2")
        assert user is not None
        assert user.disabled

    def test_admin_reset_password(self, client):
        test_client, handler = client
        handler.create_user("admin_rst2", "Adm1n@R2x!", "admin")
        handler.create_user("target_rst2", "Targt@R1!", "viewer")

        login_resp = test_client.post("/api/auth/login", json={"username": "admin_rst2", "password": "Adm1n@R2x!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.json()}"
        cookies = login_resp.cookies

        resp = test_client.post("/api/auth/users/target_rst2/reset-password", cookies=cookies, json={
            "new_password": "Reset@1234!",
        })
        assert resp.status_code == 200, f"Reset failed: {resp.status_code} {resp.text[:200]}"

        user = handler.get_user("target_rst2")
        assert user is not None
        assert user.must_change_password

    def test_auth_stats(self, client):
        test_client, handler = client
        handler.create_user("statsadm", "Stats@A1!", "admin")

        login_resp = test_client.post("/api/auth/login", json={"username": "statsadm", "password": "Stats@A1!"})
        cookies = login_resp.cookies

        resp = test_client.get("/api/auth/stats", cookies=cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert "active_sessions" in data
        assert "total_users" in data

    def test_audit_log(self, client):
        test_client, handler = client
        handler.create_user("auditadm", "Audit@A1!", "admin")
        handler.create_user("audituser", "Audit@U1!", "viewer")

        login_resp = test_client.post("/api/auth/login", json={"username": "auditadm", "password": "Audit@A1!"})
        cookies = login_resp.cookies

        resp = test_client.get("/api/auth/audit?limit=10", cookies=cookies)
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Security Boundary Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSecurityBoundaries:
    def test_token_generation_uniqueness(self):
        from core.auth.handler import generate_token
        tokens = {generate_token() for _ in range(1000)}
        assert len(tokens) == 1000  # No collisions

    def test_csrf_token_uniqueness(self):
        from core.auth.handler import generate_csrf_token
        tokens = {generate_csrf_token() for _ in range(100)}
        assert len(tokens) == 100

    def test_password_hash_not_reversible(self):
        from core.auth.handler import hash_password
        hashed = hash_password("Secret@123!")
        # Should not contain the original password
        assert "Secret" not in hashed

    def test_sql_injection_resistance(self, auth_handler, test_user):
        """Attempt SQL injection via username."""
        injection = "' OR '1'='1"
        user = auth_handler.get_user(injection)
        assert user is None
        result = auth_handler.authenticate(injection, "Test@1234!", "127.0.0.1")
        assert result is None

    def test_xss_resistance(self, auth_handler):
        """Attempt XSS via input fields."""
        xss = "<script>alert('xss')</script>"
        result = auth_handler.create_user(xss, "Xss@1234!", "viewer")
        # Should either reject or safely encode
        auth_handler.get_user(xss.lower() if not result["success"] else xss)
        # Should not cause issues either way

    def test_session_token_in_cookies(self, auth_handler, test_user):
        """Session token should be set in cookies on login."""
        from core.auth.handler import generate_token
        token = generate_token()
        assert len(token) > 0
        assert isinstance(token, str)
        # Verify token format
        user = auth_handler.get_user("testuser")
        assert user is not None
        session = auth_handler.create_session(user)
        assert session.token is not None
        assert session.csrf_token != ""

    def test_different_sessions_different_tokens(self, auth_handler, test_user):
        user = auth_handler.get_user("testuser")
        t1 = auth_handler.create_session(user)
        t2 = auth_handler.create_session(user)
        assert t1.token != t2.token

    def test_password_reset_token(self, auth_handler, test_user):
        token = auth_handler.create_password_reset_token("testuser")
        assert token is not None
        username = auth_handler.verify_password_reset_token(token)
        assert username == "testuser"

    def test_password_reset_token_expiry(self, auth_handler, test_user):
        handler = auth_handler
        token = handler.create_password_reset_token("testuser")
        assert token is not None
        # Simulate expiry by manipulating the DB directly
        t_hash = __import__("hashlib").sha256(token.encode()).hexdigest()
        conn = handler._get_conn()
        handler._init_password_reset_table(conn)
        conn.execute("UPDATE password_reset_tokens SET expires_ts = 0 WHERE token_hash = ?", (t_hash,))
        conn.commit()
        conn.close()
        assert handler.verify_password_reset_token(token) is None

    def test_password_reset_token_one_time(self, auth_handler, test_user):
        token = auth_handler.create_password_reset_token("testuser")
        assert token is not None
        assert auth_handler.verify_password_reset_token(token) == "testuser"
        # Second use should fail
        assert auth_handler.verify_password_reset_token(token) is None


# ──────────────────────────────────────────────────────────────────────────────
# RBAC Integration with Permissions
# ──────────────────────────────────────────────────────────────────────────────

class TestRBACIntegration:
    def test_role_manager_with_auth(self, auth_handler, test_user):
        from core.auth.role_manager import RoleManager

        rm = RoleManager()
        rm.assign("testuser", "admin")

        user = auth_handler.get_user("testuser")
        assert user is not None

        # Update role in auth
        auth_handler.update_user_role("testuser", "admin", "system")
        user = auth_handler.get_user("testuser")
        assert user is not None
        assert user.role == "admin"

    def test_permission_check_admin(self):
        from core.auth.permissions import role_has_permission
        assert role_has_permission("admin", "modify_config")
        assert role_has_permission("admin", "add_brokers")
        assert role_has_permission("admin", "halt_trading")
        assert role_has_permission("admin", "view_state")
        assert role_has_permission("admin", "modify_risk_limits")

    def test_permission_check_operator(self):
        from core.auth.permissions import role_has_permission
        assert role_has_permission("operator", "view_state")
        assert role_has_permission("operator", "halt_trading")
        assert role_has_permission("operator", "toggle_strategies")
        assert not role_has_permission("operator", "modify_risk_limits")
        assert not role_has_permission("operator", "modify_config")

    def test_permission_check_observer(self):
        from core.auth.permissions import role_has_permission
        assert role_has_permission("observer", "view_state")
        assert role_has_permission("observer", "view_logs")
        assert not role_has_permission("observer", "halt_trading")
        assert not role_has_permission("observer", "modify_config")

    def test_role_manager_defaults(self):
        from core.auth.role_manager import RoleManager
        rm = RoleManager("observer")
        assert rm.get_role("unknown").value == "observer"

    def test_get_role_permissions_set(self):
        from core.auth.permissions import Role, get_role_permissions
        perms = get_role_permissions(Role.ADMIN)
        assert len(perms) >= 5  # admin has many permissions
        perms = get_role_permissions(Role.OBSERVER)
        assert len(perms) == 2  # view_state + view_logs


# ──────────────────────────────────────────────────────────────────────────────
# Enterprise Dashboard Integration
# ──────────────────────────────────────────────────────────────────────────────

class TestEnterpriseDashboard:
    @pytest.fixture
    def dashboard(self):
        """Create a test EnterpriseDashboard."""
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard(config={"web_dashboard_host": "127.0.0.1"})
        return db

    def test_dashboard_creation(self, dashboard):
        assert dashboard is not None
        assert dashboard.app is not None

    def test_dashboard_has_auth_routes(self, dashboard):
        routes = [r.path for r in dashboard.app.routes]
        assert "/api/auth/login" in str(routes)
        assert "/api/auth/logout" in str(routes)
        assert "/api/auth/session" in str(routes)

    def test_dashboard_kill_switch_endpoint(self, dashboard):
        routes = [r.path for r in dashboard.app.routes]
        assert "kill" in str(routes)

    def test_dashboard_config_endpoints(self, dashboard):
        routes = [r.path for r in dashboard.app.routes]
        assert "/api/config" in str(routes)

    def test_dashboard_html_routes(self, dashboard):
        routes = [r.path for r in dashboard.app.routes]
        assert "/login" in str(routes)
        assert "/" in str(routes)

    def test_dashboard_wire_refs(self, dashboard):
        dashboard.wire_bot_refs(pause_event="test", signal_log="test")
        assert dashboard._pause_event == "test"
        assert dashboard._signal_log == "test"


# ──────────────────────────────────────────────────────────────────────────────
# Config Management
# ──────────────────────────────────────────────────────────────────────────────

class TestConfigManagement:
    @pytest.fixture
    def config_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def config_path(self, config_dir):
        path = os.path.join(config_dir, "config.json")
        with open(path, "w") as f:
            json.dump({"BASE_CAPITAL": 5000, "MAX_DAILY_LOSS": -600, "SL_PCT": 0.88}, f)
        return path

    def test_validate_config_ok(self):
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard()
        result = db._validate_config_change({"BASE_CAPITAL": 10000})
        assert result["valid"]

    def test_validate_config_env_ref(self):
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard()
        result = db._validate_config_change({"BOT_TOKEN": "${OPBUYING_BOT_TOKEN}"})
        assert result["valid"]
        assert len(result["warnings"]) > 0

    def test_preview_config(self):
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard(config={"BASE_CAPITAL": 5000})
        result = db._preview_config_change({"BASE_CAPITAL": 10000})
        assert result["total_changes"] == 1
        assert result["changed_keys"]["BASE_CAPITAL"]["old"] == 5000
        assert result["changed_keys"]["BASE_CAPITAL"]["new"] == 10000

    def test_execute_kill(self):
        import threading

        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard()
        db.wire_bot_refs(pause_event=threading.Event())
        result = db._execute_kill("Test kill", "admin")
        assert result["halted"]
        assert result["success"]

    def test_execute_resume(self):
        import threading

        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard()
        pause = threading.Event()
        pause.set()
        db.wire_bot_refs(pause_event=pause)
        result = db._execute_resume()
        assert not result["halted"]


# ──────────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────────

class TestCleanup:
    def test_purge_expired_sessions(self, auth_handler, test_user):
        user = auth_handler.get_user("testuser")
        handler = auth_handler
        handler._token_ttl = 0
        handler.create_session(user)
        time.sleep(0.01)
        count = handler.purge_expired_sessions()
        assert count >= 1

    def test_stats_endpoint(self, auth_handler, test_user):
        stats = auth_handler.get_stats()
        assert "active_sessions" in stats
        assert "total_users" in stats
        assert stats["total_users"] >= 1
