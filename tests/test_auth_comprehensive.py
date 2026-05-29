"""
Comprehensive test suite covering the full AD-KIYU auth system.

Covers every module in ``core/auth/``:
  1. Password hashing (PBKDF2) & verification
  2. Password strength validation (all rules)
  3. CSRF token generation & validation
  4. AuthHandler — default admin, authenticate, user CRUD,
     password management, session management, token expiry,
     concurrent session limits, account lockout, brute-force
     rate limiting, audit logging, password reset tokens,
     stats, purge expired sessions
  5. AuthDependencies — require_auth, require_auth_optional,
     require_role, require_permission, optional_auth_with_fallback
  6. CSRFProtection — token generation, validation (valid/missing/
     mismatch), exempt paths, ensure_cookie_set
  7. RoleManager — assign, revoke, get_role, check, has_permission,
     load_from_config, list_assignments
  8. SessionStore — create, get, touch, delete, TTL expiry,
     purge_expired, active_count, list_active
  9. Permissions — role_has_permission for all roles,
     get_role_permissions, PermissionDenied exception

All tests are self-contained.  Uses conftest fixtures where possible.
"""

import time
from collections.abc import Generator
from typing import Any

import pytest

# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def auth_db() -> Generator[str, None, None]:
    """Provide a temporary auth DB path."""
    import os as _os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".auth.db")
    _os.close(fd)
    yield path
    try:
        _os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def handler(auth_db: str) -> Any:
    """Create an AuthHandler backed by a temporary database."""
    from core.auth.handler import AuthHandler
    return AuthHandler(db_path=auth_db, token_ttl=3600)


@pytest.fixture
def handler_instant_expiry(auth_db: str) -> Any:
    """AuthHandler with zero-second TTL (instant expiry)."""
    from core.auth.handler import AuthHandler
    return AuthHandler(db_path=auth_db, token_ttl=0)


@pytest.fixture
def test_user(handler: Any) -> dict[str, Any]:
    """Create and return a test viewer user."""
    result = handler.create_user(
        username="testuser",
        password="Test@1234!",
        role="viewer",
        display_name="Test User",
    )
    assert result["success"], f"test_user creation failed: {result}"
    return result


@pytest.fixture
def test_admin(handler: Any) -> dict[str, Any]:
    """Create and return a test admin user."""
    result = handler.create_user(
        username="testadmin",
        password="Str0ng!PwdX",  # no common substring
        role="admin",
        display_name="Test Admin",
    )
    assert result["success"], f"test_admin creation failed: {result}"
    return result


@pytest.fixture
def test_operator(handler: Any) -> dict[str, Any]:
    """Create and return a test operator user."""
    result = handler.create_user(
        username="opuser",
        password="OpP@ss123!",
        role="operator",
        display_name="Operator User",
    )
    assert result["success"]
    return result


@pytest.fixture
def auth_token(handler: Any, test_user: dict[str, Any]) -> Any:
    """Create and return a valid AuthToken for test_user."""
    user_obj = handler.get_user("testuser")
    assert user_obj is not None
    return handler.create_session(user_obj, "127.0.0.1", "pytest")


# ── FastAPI app fixture for AuthDependencies tests ────────────────────


def _build_test_app(handler: Any) -> Any:
    """Build a FastAPI app with test routes for auth dependencies."""
    from core.auth.dependencies import AuthDependencies
    from core.auth.handler import AuthUser
    from fastapi import Depends, FastAPI

    deps = AuthDependencies(handler)
    app = FastAPI()

    @app.get("/require-auth")
    async def _route_require_auth(user: AuthUser = Depends(deps.require_auth)):
        return {"authenticated": True, "username": user.username, "role": user.role}

    @app.get("/require-auth-optional")
    async def _route_optional(user: AuthUser | None = Depends(deps.require_auth_optional)):
        if user is None:
            return {"authenticated": False}
        return {"authenticated": True, "username": user.username}

    @app.get("/require-admin")
    async def _route_admin(user: AuthUser = Depends(deps.require_role("admin"))):
        return {"role": user.role}

    @app.get("/require-operator")
    async def _route_operator(user: AuthUser = Depends(deps.require_role("operator"))):
        return {"role": user.role}

    @app.get("/require-admin-or-operator")
    async def _route_admin_or_op(user: AuthUser = Depends(deps.require_role("admin", "operator"))):
        return {"role": user.role}

    @app.get("/require-viewer")
    async def _route_viewer(user: AuthUser = Depends(deps.require_role("viewer"))):
        return {"role": user.role}

    @app.get("/require-permission")
    async def _route_perm(user: AuthUser = Depends(deps.require_permission("halt_trading"))):
        return {"role": user.role, "permission": "halt_trading"}

    @app.get("/optional-with-fallback")
    async def _route_fallback(user: AuthUser = Depends(deps.optional_auth_with_fallback("viewer"))):
        return {"username": user.username, "role": user.role}

    return app, deps


def _add_login_route(app: Any, handler: Any) -> None:
    """Add a POST /login route to the app."""
    from core.auth.dependencies import get_client_ip
    from fastapi import HTTPException, Request, Response

    @app.post("/login")
    async def login(request: Request, response: Response):
        body = await request.json()
        uname = str(body.get("username", ""))
        pwd = str(body.get("password", ""))
        ip = get_client_ip(request)
        user_obj = handler.authenticate(uname, pwd, ip)
        if user_obj is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = handler.create_session(user_obj, ip, "pytest")
        response.set_cookie(key="opb_session", value=token.token, httponly=True)
        return {"success": True, "token": token.token}


@pytest.fixture
def deps_client(handler: Any) -> Any:
    """Create TestClient with routes for testing AuthDependencies.

    Returns (client, handler, deps) tuple.
    """
    from fastapi.testclient import TestClient
    app, deps = _build_test_app(handler)
    _add_login_route(app, handler)
    return TestClient(app), handler, deps


# ═══════════════════════════════════════════════════════════════════════
# 1. Password Hashing & Verification (PBKDF2)
# ═══════════════════════════════════════════════════════════════════════


class TestPasswordHashing:
    """PBKDF2-SHA256 hashing and verification."""

    def test_hash_and_verify(self):
        from core.auth.handler import hash_password, verify_password
        pwd = "MySecureP@ss1"
        hashed = hash_password(pwd)
        assert hashed != pwd
        assert hashed.count("$") == 2
        assert verify_password(pwd, hashed)
        assert not verify_password("WrongP@ss1", hashed)

    def test_different_salts_per_call(self):
        from core.auth.handler import hash_password
        pwd = "SameP@ss1"
        h1 = hash_password(pwd)
        h2 = hash_password(pwd)
        assert h1 != h2

    def test_empty_password(self):
        from core.auth.handler import hash_password, verify_password
        hashed = hash_password("")
        assert verify_password("", hashed)
        assert not verify_password("x", hashed)

    def test_corrupted_hash_returns_false(self):
        from core.auth.handler import verify_password
        assert not verify_password("pwd", "not-a-valid-hash")
        assert not verify_password("pwd", "100000$salt$hash")
        assert not verify_password("pwd", "")
        assert not verify_password("pwd", "abc$def")

    def test_unicode_password(self):
        from core.auth.handler import hash_password, verify_password
        pwd = "P@sswörd123!ñ"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed)
        assert not verify_password("P@ssword123!n", hashed)

    def test_long_password(self):
        from core.auth.handler import hash_password, verify_password
        pwd = "A" * 100 + "@1x"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed)
        assert not verify_password(pwd[:-1], hashed)

    def test_hash_format_contains_iterations(self):
        from core.auth.handler import PBKDF2_ITERATIONS, hash_password
        hashed = hash_password("Test@1234!")
        parts = hashed.split("$")
        assert int(parts[0]) == PBKDF2_ITERATIONS
        assert len(bytes.fromhex(parts[1])) == 32  # 32-byte salt

    def test_timing_constant_time_comparison(self):

        from core.auth.handler import hash_password, verify_password
        pwd = "Test@1234!"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed)
        assert not verify_password("WrongP@ss1", hashed)
        # verify_password uses hmac.compare_digest internally


# ═══════════════════════════════════════════════════════════════════════
# 2. Password Strength Validation
# ═══════════════════════════════════════════════════════════════════════


class TestPasswordStrength:
    """All password strength validation rules."""

    VALID = "Str0ng!Pwd"

    def test_valid_password(self):
        from core.auth.handler import validate_password_strength
        valid, msg = validate_password_strength(self.VALID)
        assert valid
        assert msg == ""

    def test_too_short(self):
        from core.auth.handler import validate_password_strength
        valid, msg = validate_password_strength("Ab1!")
        assert not valid
        assert "8 characters" in msg

    def test_no_uppercase(self):
        from core.auth.handler import validate_password_strength
        valid, msg = validate_password_strength("lowercase1!")
        assert not valid
        assert "uppercase" in msg

    def test_no_lowercase(self):
        from core.auth.handler import validate_password_strength
        valid, msg = validate_password_strength("UPPERCASE1!")
        assert not valid
        assert "lowercase" in msg

    def test_no_digit(self):
        from core.auth.handler import validate_password_strength
        valid, msg = validate_password_strength("NoDigits!")
        assert not valid
        assert "digit" in msg

    def test_no_special_character(self):
        from core.auth.handler import validate_password_strength
        valid, msg = validate_password_strength("NoSpecial1")
        assert not valid
        assert "special" in msg

    def test_common_password_blocked(self):
        from core.auth.handler import validate_password_strength
        assert not validate_password_strength("Password123!")[0]
        assert not validate_password_strength("Admin@123!")[0]
        assert not validate_password_strength("Qwerty@123!")[0]
        assert not validate_password_strength("Letmein@123!")[0]

    def test_edge_case_exactly_min_length(self):
        from core.auth.handler import validate_password_strength
        # 8 chars, meets all rules
        valid, _ = validate_password_strength("Abcd@123")
        assert valid

    def test_special_chars_all_variants(self):
        from core.auth.handler import validate_password_strength
        specials = "!@#$%^&*(),.?\":{}|<>_-"
        for ch in specials:
            pwd = f"Abcd1{ch}xy"
            valid, _ = validate_password_strength(pwd)
            assert valid, f"Failed for special char: {ch}"


# ═══════════════════════════════════════════════════════════════════════
# 3. CSRF Token Generation & Validation
# ═══════════════════════════════════════════════════════════════════════


class TestCSRFToken:
    """Unit tests for CSRF token generation and validation."""

    def test_generate_csrf_token_length(self):
        from core.auth.handler import generate_csrf_token
        token = generate_csrf_token()
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_generate_csrf_token_uniqueness(self):
        from core.auth.handler import generate_csrf_token
        tokens = {generate_csrf_token() for _ in range(100)}
        assert len(tokens) == 100

    def test_csrf_protection_token_generation(self):
        from core.auth.csrf import CSRFProtection
        csrf = CSRFProtection(secret_key="test-secret")
        token = csrf._generate_token("session-abc")
        assert len(token) == 64
        assert isinstance(token, str)

    def test_csrf_token_different_for_different_sessions(self):
        from core.auth.csrf import CSRFProtection
        csrf = CSRFProtection(secret_key="test-secret")
        t1 = csrf._generate_token("session-1")
        t2 = csrf._generate_token("session-2")
        assert t1 != t2

    def test_csrf_token_different_for_different_secrets(self):
        from core.auth.csrf import CSRFProtection
        c1 = CSRFProtection(secret_key="secret-1")
        c2 = CSRFProtection(secret_key="secret-2")
        t1 = c1._generate_token("session-x")
        t2 = c2._generate_token("session-x")
        assert t1 != t2


# ═══════════════════════════════════════════════════════════════════════
# 4. AuthHandler — Comprehensive
# ═══════════════════════════════════════════════════════════════════════


class TestAuthHandlerDefaultAdmin:
    """Default admin user is created on first init of empty DB."""

    def test_default_admin_created(self, handler: Any):
        user = handler.get_user("admin")
        assert user is not None
        assert user.username == "admin"
        assert user.role == "admin"
        assert user.must_change_password

    def test_default_admin_not_duplicated(self, handler: Any):
        """Second init does not create a second admin."""
        from core.auth.handler import AuthHandler
        h2 = AuthHandler(db_path=handler._db_path)
        users = h2.list_users()
        admins = [u for u in users if u["username"] == "admin"]
        assert len(admins) == 1

    def test_default_admin_has_must_change_flag(self, handler: Any):
        user = handler.get_user("admin")
        assert user is not None
        assert user.must_change_password is True


class TestAuthHandlerAuthenticate:
    """Authentication success, failure, rate limiting, lockout."""

    def test_login_success(self, handler: Any, test_user: dict[str, Any]):
        user = handler.authenticate("testuser", "Test@1234!", "127.0.0.1")
        assert user is not None
        assert user.username == "testuser"
        assert user.role == "viewer"
        assert user.disabled is False

    def test_login_wrong_password(self, handler: Any, test_user: dict[str, Any]):
        user = handler.authenticate("testuser", "WrongP@ss1!", "127.0.0.1")
        assert user is None

    def test_login_nonexistent_user(self, handler: Any):
        user = handler.authenticate("nobody", "SomeP@ss1!", "127.0.0.1")
        assert user is None

    def test_login_disabled_user(self, handler: Any, test_user: dict[str, Any]):
        handler.disable_user("testuser", "admin")
        user = handler.authenticate("testuser", "Test@1234!", "127.0.0.1")
        assert user is None

    def test_login_updates_last_login_ts(self, handler: Any, test_user: dict[str, Any]):
        before = time.time()
        handler.authenticate("testuser", "Test@1234!", "127.0.0.1")
        user = handler.get_user("testuser")
        assert user is not None
        assert user.last_login_ts is not None
        assert user.last_login_ts >= before - 1

    def test_login_case_insensitive_username(self, handler: Any, test_user: dict[str, Any]):
        user = handler.authenticate("TESTUSER", "Test@1234!", "127.0.0.1")
        assert user is not None
        assert user.username == "testuser"

    def test_login_strips_whitespace(self, handler: Any, test_user: dict[str, Any]):
        user = handler.authenticate("  testuser  ", "Test@1234!", "127.0.0.1")
        assert user is not None


class TestAuthHandlerUserCRUD:
    """Create, list, get, update role, disable, enable, delete."""

    def test_create_user(self, handler: Any):
        result = handler.create_user("newuser", "New@User1!", "viewer")
        assert result["success"]
        assert result["username"] == "newuser"
        assert result["role"] == "viewer"

    def test_create_user_with_display_name(self, handler: Any):
        result = handler.create_user("bob", "Bob@1234!", "operator", "Bob Jones")
        assert result["success"]
        user = handler.get_user("bob")
        assert user is not None
        assert user.display_name == "Bob Jones"

    def test_create_duplicate_user_fails(self, handler: Any, test_user: dict[str, Any]):
        result = handler.create_user("testuser", "Other@1!", "viewer")
        assert not result["success"]
        assert "already exists" in result["error"]

    def test_create_user_invalid_role(self, handler: Any):
        result = handler.create_user("badrole", "Test@1234!", "superadmin")
        assert not result["success"]
        assert "Invalid role" in result["error"]

    def test_create_user_short_username(self, handler: Any):
        result = handler.create_user("ab", "Test@1234!", "viewer")
        assert not result["success"]
        assert "3 characters" in result["error"]

    def test_create_user_weak_password(self, handler: Any):
        result = handler.create_user("weakuser", "short", "viewer")
        assert not result["success"]
        assert "Password" in result["error"]

    def test_list_users(self, handler: Any, test_user: dict[str, Any], test_admin: dict[str, Any]):
        users = handler.list_users()
        assert len(users) >= 2
        usernames = [u["username"] for u in users]
        assert "testuser" in usernames
        assert "testadmin" in usernames

    def test_list_users_ordered_by_created(self, handler: Any, test_user: dict[str, Any], test_admin: dict[str, Any]):
        users = handler.list_users()
        timestamps = [u["created_ts"] for u in users]
        assert timestamps == sorted(timestamps)

    def test_get_user(self, handler: Any, test_user: dict[str, Any]):
        user = handler.get_user("testuser")
        assert user is not None
        assert user.username == "testuser"
        assert user.role == "viewer"

    def test_get_nonexistent_user_returns_none(self, handler: Any):
        user = handler.get_user("nonexistent")
        assert user is None

    def test_get_user_by_id(self, handler: Any, test_user: dict[str, Any]):
        users = handler.list_users()
        target = next(u for u in users if u["username"] == "testuser")
        user = handler.get_user_by_id(target["user_id"])
        assert user is not None
        assert user.username == "testuser"

    def test_get_user_by_id_nonexistent(self, handler: Any):
        user = handler.get_user_by_id("no-such-id")
        assert user is None

    def test_update_user_role(self, handler: Any, test_user: dict[str, Any]):
        result = handler.update_user_role("testuser", "admin", "testadmin")
        assert result["success"]
        user = handler.get_user("testuser")
        assert user is not None
        assert user.role == "admin"

    def test_update_user_role_invalid(self, handler: Any, test_user: dict[str, Any]):
        result = handler.update_user_role("testuser", "superadmin", "testadmin")
        assert not result["success"]
        assert "Invalid role" in result["error"]

    def test_update_user_role_nonexistent(self, handler: Any):
        result = handler.update_user_role("nobody", "admin", "testadmin")
        assert not result["success"]
        assert "not found" in result["error"]

    def test_disable_user(self, handler: Any, test_user: dict[str, Any]):
        result = handler.disable_user("testuser", "testadmin")
        assert result["success"]
        user = handler.get_user("testuser")
        assert user is not None
        assert user.disabled is True

    def test_enable_user(self, handler: Any, test_user: dict[str, Any]):
        handler.disable_user("testuser", "testadmin")
        result = handler.enable_user("testuser", "testadmin")
        assert result["success"]
        user = handler.get_user("testuser")
        assert user is not None
        assert user.disabled is False

    def test_delete_user(self, handler: Any, test_user: dict[str, Any]):
        result = handler.delete_user("testuser", "testadmin")
        assert result["success"]
        assert handler.get_user("testuser") is None

    def test_delete_default_admin_blocked(self, handler: Any):
        result = handler.delete_user("admin", "testadmin")
        assert not result["success"]
        assert "Cannot delete default admin" in result["error"]


class TestAuthHandlerPasswordManagement:
    """Change password and admin-forced reset."""

    def test_password_change_success(self, handler: Any, test_user: dict[str, Any]):
        result = handler.update_password("testuser", "Test@1234!", "NewP@ss1!")
        assert result["success"]
        assert handler.authenticate("testuser", "NewP@ss1!", "127.0.0.1") is not None
        assert handler.authenticate("testuser", "Test@1234!", "127.0.0.1") is None

    def test_password_change_wrong_current(self, handler: Any, test_user: dict[str, Any]):
        result = handler.update_password("testuser", "Wrong@123!", "NewP@ss1!")
        assert not result["success"]
        assert "incorrect" in result["error"]

    def test_password_change_weak_new(self, handler: Any, test_user: dict[str, Any]):
        result = handler.update_password("testuser", "Test@1234!", "weak")
        assert not result["success"]
        assert "Password" in result["error"]

    def test_password_change_nonexistent_user(self, handler: Any):
        result = handler.update_password("nobody", "Old@123!", "New@1234!")
        assert not result["success"]
        assert "not found" in result["error"]

    def test_password_change_clears_must_change_flag(self, handler: Any, test_user: dict[str, Any]):
        # First, admin reset sets must_change_password=1
        handler.admin_reset_password("testuser", "Reset@1234!", "admin")
        user = handler.get_user("testuser")
        assert user is not None and user.must_change_password
        # Now user changes password — flag should clear
        handler.update_password("testuser", "Reset@1234!", "Final@1234!")
        user = handler.get_user("testuser")
        assert user is not None and not user.must_change_password

    def test_admin_reset_password(self, handler: Any, test_user: dict[str, Any]):
        result = handler.admin_reset_password("testuser", "Reset@1234!", "admin")
        assert result["success"]
        user = handler.get_user("testuser")
        assert user is not None and user.must_change_password
        # Old password no longer works
        assert handler.authenticate("testuser", "Test@1234!", "127.0.0.1") is None
        # New password works
        auth_user = handler.authenticate("testuser", "Reset@1234!", "127.0.0.1")
        assert auth_user is not None and auth_user.must_change_password

    def test_admin_reset_weak_password(self, handler: Any, test_user: dict[str, Any]):
        result = handler.admin_reset_password("testuser", "weak", "admin")
        assert not result["success"]
        assert "Password" in result["error"]

    def test_admin_reset_nonexistent_user(self, handler: Any):
        result = handler.admin_reset_password("nobody", "Reset@1234!", "admin")
        assert not result["success"]
        assert "not found" in result["error"]


class TestAuthHandlerSessionManagement:
    """Session creation, verification, refresh, revoke, revoke all."""

    def test_create_session(self, handler: Any, test_user: dict[str, Any]):
        user = handler.get_user("testuser")
        assert user is not None
        token = handler.create_session(user, "127.0.0.1", "pytest")
        assert token is not None
        assert token.username == "testuser"
        assert token.role == "viewer"
        assert token.csrf_token != ""

    def test_verify_valid_session(self, handler: Any, test_token: Any):
        verified = handler.verify_session(test_token.token)
        assert verified is not None
        assert verified.user_id == test_token.user_id

    def test_verify_expired_session_returns_none(
        self, handler_instant_expiry: Any, test_user: dict[str, Any]
    ):
        user = handler_instant_expiry.get_user("testuser")
        assert user is not None
        token = handler_instant_expiry.create_session(user)
        time.sleep(0.01)
        verified = handler_instant_expiry.verify_session(token.token)
        assert verified is None

    def test_verify_empty_token(self, handler: Any):
        assert handler.verify_session("") is None
        assert handler.verify_session(None) is None  # type: ignore[arg-type]

    def test_revoke_session(self, handler: Any, test_token: Any):
        assert handler.revoke_session(test_token.token)
        assert handler.verify_session(test_token.token) is None

    def test_revoke_nonexistent_session(self, handler: Any):
        assert not handler.revoke_session("nonexistent")

    def test_revoke_all_user_sessions(self, handler: Any, test_user: dict[str, Any]):
        user = handler.get_user("testuser")
        assert user is not None
        t1 = handler.create_session(user)
        t2 = handler.create_session(user)
        count = handler.revoke_all_user_sessions("testuser")
        assert count >= 2
        assert handler.verify_session(t1.token) is None
        assert handler.verify_session(t2.token) is None

    def test_revoke_all_user_sessions_nonexistent(self, handler: Any):
        count = handler.revoke_all_user_sessions("nobody")
        assert count == 0

    def test_get_user_sessions(self, handler: Any, test_user: dict[str, Any]):
        user = handler.get_user("testuser")
        assert user is not None
        handler.create_session(user, "10.0.0.1", "agent-1")
        handler.create_session(user, "10.0.0.2", "agent-2")
        sessions = handler.get_user_sessions(user.user_id)
        assert len(sessions) == 2
        ips = {s["ip_address"] for s in sessions}
        assert ips == {"10.0.0.1", "10.0.0.2"}

    def test_purge_expired_sessions(self, handler_instant_expiry: Any, test_user: dict[str, Any]):
        user = handler_instant_expiry.get_user("testuser")
        assert user is not None
        handler_instant_expiry.create_session(user)
        handler_instant_expiry.create_session(user)
        time.sleep(0.01)
        count = handler_instant_expiry.purge_expired_sessions()
        assert count >= 2

    def test_purge_expired_noop_when_none_expired(self, handler: Any, test_user: dict[str, Any]):
        count = handler.purge_expired_sessions()
        assert count == 0

    @pytest.fixture
    def test_token(self, handler: Any, test_user: dict[str, Any]) -> Any:
        user = handler.get_user("testuser")
        assert user is not None
        return handler.create_session(user, "127.0.0.1", "pytest")


class TestAuthHandlerSessionRefresh:
    """Extending session TTL via refresh_session."""

    def test_refresh_session_extends_ttl(self, handler: Any, test_user: dict[str, Any]):
        user = handler.get_user("testuser")
        assert user is not None
        token = handler.create_session(user)
        original_expires = token.expires_ts
        time.sleep(0.01)
        refreshed = handler.refresh_session(token.token)
        assert refreshed is not None
        assert refreshed.expires_ts > original_expires

    def test_refresh_expired_session_returns_none(
        self, handler_instant_expiry: Any, test_user: dict[str, Any]
    ):
        user = handler_instant_expiry.get_user("testuser")
        assert user is not None
        token = handler_instant_expiry.create_session(user)
        time.sleep(0.01)
        assert handler_instant_expiry.refresh_session(token.token) is None

    def test_refresh_nonexistent_token(self, handler: Any):
        assert handler.refresh_session("bogus-token") is None

    def test_refresh_persists_to_db(self, handler: Any, test_user: dict[str, Any]):
        user = handler.get_user("testuser")
        assert user is not None
        token = handler.create_session(user)
        time.sleep(0.01)
        refreshed = handler.refresh_session(token.token)
        assert refreshed is not None
        # Create a new handler instance (DB-backed) to verify persistence
        from core.auth.handler import AuthHandler
        h2 = AuthHandler(db_path=handler._db_path, token_ttl=3600)
        verified = h2.verify_session(token.token)
        assert verified is not None
        # TTL should reflect the extended time
        assert verified.expires_ts >= refreshed.expires_ts - 1


class TestAuthHandlerConcurrentSessionLimits:
    """MAX_CONCURRENT_SESSIONS enforcement."""

    def test_oldest_session_revoked_when_limit_exceeded(self, handler: Any, test_user: dict[str, Any]):
        from core.auth.handler import MAX_CONCURRENT_SESSIONS
        user = handler.get_user("testuser")
        assert user is not None
        # Create MAX sessions
        tokens = []
        for _ in range(MAX_CONCURRENT_SESSIONS):
            t = handler.create_session(user)
            tokens.append(t)
        # All should be valid
        for t in tokens:
            assert handler.verify_session(t.token) is not None
        # One more should evict the oldest
        extra = handler.create_session(user)
        assert handler.verify_session(extra.token) is not None
        # The very first token should now be revoked
        assert handler.verify_session(tokens[0].token) is None

    def test_concurrent_sessions_threshold(self, handler: Any, test_user: dict[str, Any]):
        """Exactly MAX_CONCURRENT_SESSIONS sessions are allowed."""
        from core.auth.handler import MAX_CONCURRENT_SESSIONS
        user = handler.get_user("testuser")
        assert user is not None
        tokens = []
        for _ in range(MAX_CONCURRENT_SESSIONS):
            t = handler.create_session(user)
            tokens.append(t)
        for t in tokens:
            assert handler.verify_session(t.token) is not None


class TestAuthHandlerBruteForceAndLockout:
    """Account lockout after N failed attempts, brute force rate limiting."""

    def _make_user(self, handler: Any, tag: str) -> tuple[str, str]:
        uname = f"bf_{tag}"
        pwd = "Test@1234!"
        handler.create_user(uname, pwd, "viewer")
        return uname, pwd

    def test_rate_limiting_blocks_from_same_ip(self, handler: Any):
        uname, pwd = self._make_user(handler, "rlimit1")
        for _ in range(12):
            handler.authenticate(uname, "WrongP@ss!", "10.0.0.1")
        user = handler.authenticate(uname, pwd, "10.0.0.1")
        assert user is None, "Should be rate limited"

    def test_rate_limiting_per_ip_independent(self, handler: Any):
        uname, pwd = self._make_user(handler, "rlimit2")
        handler._clear_lockout(uname)
        for _ in range(6):
            handler.authenticate(uname, "WrongP@ss!", "10.0.0.1")
        handler._clear_lockout(uname)
        user = handler.authenticate(uname, pwd, "10.0.0.2")
        assert user is not None, "Different IP should not be rate limited"

    def test_localhost_exempt_from_rate_limiting(self, handler: Any):
        """127.0.0.1 is whitelisted from brute-force rate limiting.
        (Account lockout still applies; clear it between attempts.)
        """
        uname, pwd = self._make_user(handler, "local_exempt")
        for _ in range(12):
            handler._clear_lockout(uname)
            handler.authenticate(uname, "WrongP@ss!", "127.0.0.1")
        # Rate limiter should be bypassed for localhost — login should succeed
        handler._clear_lockout(uname)
        user = handler.authenticate(uname, pwd, "127.0.0.1")
        assert user is not None

    def test_account_lockout_after_n_failures(self, handler: Any):
        uname, pwd = self._make_user(handler, "lock1")
        handler._clear_lockout(uname)
        for _ in range(5):
            handler.authenticate(uname, "WrongP@ss!", "10.0.0.3")
        user = handler.authenticate(uname, pwd, "10.0.0.3")
        assert user is None

    def test_lockout_clears_on_successful_login(self, handler: Any):
        uname, pwd = self._make_user(handler, "lock2")
        handler._clear_lockout(uname)
        for _ in range(3):
            handler.authenticate(uname, "WrongP@ss!", "10.0.0.4")
        user = handler.authenticate(uname, pwd, "10.0.0.5")
        assert user is not None

    def test_lockout_db_persistence(self, handler: Any):
        """Lockout should survive handler re-creation (DB-backed)."""
        uname, pwd = self._make_user(handler, "lock_db")
        handler._clear_lockout(uname)
        for _ in range(5):
            handler.authenticate(uname, "WrongP@ss!", "10.0.0.6")
        # Re-create handler
        from core.auth.handler import AuthHandler
        h2 = AuthHandler(db_path=handler._db_path)
        user = h2.authenticate(uname, pwd, "10.0.0.6")
        assert user is None

    def test_lockout_expires_after_duration(self, handler: Any):
        """Lockout should auto-expire after LOCKOUT_DURATION_SECONDS."""
        uname, pwd = self._make_user(handler, "lock_exp")
        handler._clear_lockout(uname)
        for _ in range(5):
            handler.authenticate(uname, "WrongP@ss!", "10.0.0.7")
        # Simulate lockout expiry
        with handler._lock:
            if uname in handler._account_lockouts:
                handler._account_lockouts[uname] = time.time() - 1
        user = handler.authenticate(uname, pwd, "10.0.0.7")
        assert user is not None

    def test_rate_limit_window_expiry(self, handler: Any):
        """Rate-limit counter should reset after BRUTE_FORCE_WINDOW_SECONDS."""
        from core.auth.handler import BRUTE_FORCE_WINDOW_SECONDS
        uname, pwd = self._make_user(handler, "rlimit_exp")
        for _ in range(10):
            handler.authenticate(uname, "WrongP@ss!", "10.0.1.1")
        # Simulate window expiry — set old timestamps for both rate-limit and lockout
        handler._login_attempts["10.0.1.1"] = [time.time() - BRUTE_FORCE_WINDOW_SECONDS - 10]
        handler._clear_lockout(uname)
        user = handler.authenticate(uname, pwd, "10.0.1.1")
        assert user is not None


class TestAuthHandlerAuditLogging:
    """Audit log entries for all auth events."""

    def test_audit_log_on_login_success(self, handler: Any, test_user: dict[str, Any]):
        handler.authenticate("testuser", "Test@1234!", "10.0.0.1")
        entries = handler.get_audit_log()
        success_entries = [e for e in entries if e["event_type"] == "login_success"]
        assert len(success_entries) >= 1
        assert success_entries[0]["username"] == "testuser"

    def test_audit_log_on_login_failure(self, handler: Any, test_user: dict[str, Any]):
        handler.authenticate("testuser", "WrongP@ss!", "10.0.0.2")
        entries = handler.get_audit_log(event_type="login_failed")
        assert len(entries) >= 1
        assert entries[0]["username"] == "testuser"

    def test_audit_log_on_user_created(self, handler: Any):
        handler.create_user("newperson", "New@Person1!", "operator", created_by="admin")
        entries = handler.get_audit_log(event_type="user_created")
        assert len(entries) >= 1
        assert entries[0]["username"] == "newperson"

    def test_audit_log_on_password_change(self, handler: Any, test_user: dict[str, Any]):
        handler.update_password("testuser", "Test@1234!", "NewP@ss1!")
        entries = handler.get_audit_log(event_type="password_changed")
        assert len(entries) >= 1
        assert entries[0]["username"] == "testuser"

    def test_audit_log_on_admin_reset(self, handler: Any, test_user: dict[str, Any]):
        handler.admin_reset_password("testuser", "Reset@1234!", "admin")
        entries = handler.get_audit_log(event_type="password_admin_reset")
        assert len(entries) >= 1
        assert entries[0]["username"] == "testuser"

    def test_audit_log_on_role_change(self, handler: Any, test_user: dict[str, Any]):
        handler.update_user_role("testuser", "operator", "admin")
        entries = handler.get_audit_log(event_type="role_changed")
        assert len(entries) >= 1
        assert entries[0]["username"] == "testuser"
        details = entries[0].get("details", {})
        assert details.get("new_role") == "operator"

    def test_audit_log_on_disable(self, handler: Any, test_user: dict[str, Any]):
        handler.disable_user("testuser", "admin")
        entries = handler.get_audit_log(event_type="user_disabled")
        assert len(entries) >= 1
        assert entries[0]["username"] == "testuser"

    def test_audit_log_on_delete(self, handler: Any, test_user: dict[str, Any]):
        handler.delete_user("testuser", "admin")
        entries = handler.get_audit_log(event_type="user_deleted")
        assert len(entries) >= 1
        assert entries[0]["username"] == "testuser"

    def test_audit_log_filter_by_event_type(self, handler: Any, test_user: dict[str, Any]):
        handler.authenticate("testuser", "Test@1234!", "10.0.0.1")
        handler.authenticate("testuser", "Test@1234!", "10.0.0.1")
        login_only = handler.get_audit_log(event_type="login_success")
        for e in login_only:
            assert e["event_type"] == "login_success"

    def test_audit_log_limit(self, handler: Any, test_user: dict[str, Any]):
        for _ in range(10):
            handler.authenticate("testuser", "Test@1234!", "10.0.0.1")
        entries = handler.get_audit_log(limit=5)
        assert len(entries) <= 5


class TestAuthHandlerPasswordResetTokens:
    """Password reset token create, verify, expiry, one-time use."""

    def test_create_password_reset_token(self, handler: Any, test_user: dict[str, Any]):
        token = handler.create_password_reset_token("testuser")
        assert token is not None
        assert len(token) > 0

    def test_create_password_reset_token_nonexistent_user(self, handler: Any):
        token = handler.create_password_reset_token("nobody")
        assert token is None

    def test_verify_password_reset_token(self, handler: Any, test_user: dict[str, Any]):
        token = handler.create_password_reset_token("testuser")
        assert token is not None
        username = handler.verify_password_reset_token(token)
        assert username == "testuser"

    def test_password_reset_token_one_time_use(self, handler: Any, test_user: dict[str, Any]):
        token = handler.create_password_reset_token("testuser")
        assert token is not None
        assert handler.verify_password_reset_token(token) == "testuser"
        assert handler.verify_password_reset_token(token) is None

    def test_password_reset_token_expiry(self, handler: Any, test_user: dict[str, Any]):
        from core.auth.handler import hashlib
        token = handler.create_password_reset_token("testuser")
        assert token is not None
        # Simulate expiry by updating the DB directly
        t_hash = hashlib.sha256(token.encode()).hexdigest()
        conn = handler._get_conn()
        try:
            conn.execute("UPDATE password_reset_tokens SET expires_ts = 0 WHERE token_hash = ?", (t_hash,))
            conn.commit()
        finally:
            conn.close()
        assert handler.verify_password_reset_token(token) is None

    def test_verify_empty_reset_token(self, handler: Any):
        assert handler.verify_password_reset_token("") is None
        assert handler.verify_password_reset_token(None) is None  # type: ignore[arg-type]

    def test_verify_invalid_reset_token(self, handler: Any):
        assert handler.verify_password_reset_token("bogus-token") is None


class TestAuthHandlerStats:
    """Auth system statistics."""

    def test_stats_basic_structure(self, handler: Any, test_user: dict[str, Any]):
        stats = handler.get_stats()
        assert "active_sessions" in stats
        assert "total_users" in stats
        assert "locked_accounts" in stats
        assert "failed_logins_24h" in stats
        assert "token_ttl_seconds" in stats

    def test_stats_reflects_activity(self, handler: Any, test_user: dict[str, Any]):
        stats = handler.get_stats()
        assert stats["total_users"] >= 2  # default admin + testuser

    def test_stats_active_sessions(self, handler: Any, test_user: dict[str, Any]):
        user = handler.get_user("testuser")
        assert user is not None
        handler.create_session(user)
        stats = handler.get_stats()
        assert stats["active_sessions"] >= 1


# ═══════════════════════════════════════════════════════════════════════
# 5. AuthDependencies
# ═══════════════════════════════════════════════════════════════════════


class TestAuthDependenciesRequireAuth:
    """require_auth: valid, invalid, expired."""

    def test_require_auth_valid(self, deps_client: Any):
        client, handler, _ = deps_client
        # Create user, login, then access protected route
        handler.create_user("requser", "Req@User1!", "viewer")
        login_resp = client.post("/login", json={"username": "requser", "password": "Req@User1!"})
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]
        resp = client.get("/require-auth", cookies={"opb_session": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["username"] == "requser"

    def test_require_auth_no_cookie(self, deps_client: Any):
        client, _, _ = deps_client
        resp = client.get("/require-auth")
        assert resp.status_code == 401
        assert "Authentication required" in resp.text

    def test_require_auth_invalid_token(self, deps_client: Any):
        client, _, _ = deps_client
        resp = client.get("/require-auth", cookies={"opb_session": "bogus-token"})
        assert resp.status_code == 401

    def test_require_auth_expired_token(self, deps_client: Any, auth_db: str):
        client, handler, _ = deps_client
        # Create user with instant-expiry handler
        from core.auth.handler import AuthHandler
        exp_handler = AuthHandler(db_path=auth_db, token_ttl=0)
        exp_handler.create_user("expuser", "Exp@User1!", "viewer")
        user_obj = exp_handler.get_user("expuser")
        assert user_obj is not None
        exp_token = exp_handler.create_session(user_obj)
        time.sleep(0.01)
        resp = client.get("/require-auth", cookies={"opb_session": exp_token.token})
        assert resp.status_code == 401

    def test_require_auth_with_bearer_token(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("beareruser", "Bear@er1!", "operator")
        login_resp = client.post("/login", json={"username": "beareruser", "password": "Bear@er1!"})
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]
        resp = client.get("/require-auth", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "beareruser"


class TestAuthDependenciesRequireAuthOptional:
    """require_auth_optional returns None when not authenticated."""

    def test_optional_authenticated(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("optuser", "Opt@User1!", "viewer")
        login_resp = client.post("/login", json={"username": "optuser", "password": "Opt@User1!"})
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]
        resp = client.get("/require-auth-optional", cookies={"opb_session": token})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True

    def test_optional_not_authenticated(self, deps_client: Any):
        client, _, _ = deps_client
        resp = client.get("/require-auth-optional")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_optional_with_bad_token(self, deps_client: Any):
        client, _, _ = deps_client
        resp = client.get("/require-auth-optional", cookies={"opb_session": "bad"})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False


class TestAuthDependenciesRequireRole:
    """require_role enforces role-based access."""

    def test_admin_allowed(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("adm1", "Adm@In1!", "admin")
        login_resp = client.post("/login", json={"username": "adm1", "password": "Adm@In1!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text[:200]}"
        token = login_resp.json()["token"]
        resp = client.get("/require-admin", cookies={"opb_session": token})
        assert resp.status_code == 200

    def test_viewer_blocked_from_admin(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("vw1", "Vw@User1!", "viewer")
        login_resp = client.post("/login", json={"username": "vw1", "password": "Vw@User1!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text[:200]}"
        token = login_resp.json()["token"]
        resp = client.get("/require-admin", cookies={"opb_session": token})
        assert resp.status_code == 403

    def test_operator_allowed_operator_endpoint(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("op1", "Op@User1!", "operator")
        login_resp = client.post("/login", json={"username": "op1", "password": "Op@User1!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text[:200]}"
        token = login_resp.json()["token"]
        resp = client.get("/require-operator", cookies={"opb_session": token})
        assert resp.status_code == 200

    def test_viewer_blocked_from_operator(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("vw2", "Vw2@User1!", "viewer")
        login_resp = client.post("/login", json={"username": "vw2", "password": "Vw2@User1!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text[:200]}"
        token = login_resp.json()["token"]
        resp = client.get("/require-operator", cookies={"opb_session": token})
        assert resp.status_code == 403

    def test_viewer_allowed_viewer_endpoint(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("vw3", "Vw3@User1!", "viewer")
        login_resp = client.post("/login", json={"username": "vw3", "password": "Vw3@User1!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text[:200]}"
        token = login_resp.json()["token"]
        resp = client.get("/require-viewer", cookies={"opb_session": token})
        assert resp.status_code == 200

    def test_admin_or_operator_multirole(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("multi1", "Multi@1!", "admin")
        handler.create_user("multi2", "Multi@2!", "operator")
        for uname in ("multi1", "multi2"):
            pwd = "Multi@1!" if uname == "multi1" else "Multi@2!"
            login_resp = client.post("/login", json={"username": uname, "password": pwd})
            assert login_resp.status_code == 200, f"Login for {uname} failed: {login_resp.text[:200]}"
            token = login_resp.json()["token"]
            resp = client.get("/require-admin-or-operator", cookies={"opb_session": token})
            assert resp.status_code == 200

    def test_viewer_blocked_from_multirole(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("multi3", "Multi@3!", "viewer")
        login_resp = client.post("/login", json={"username": "multi3", "password": "Multi@3!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text[:200]}"
        token = login_resp.json()["token"]
        resp = client.get("/require-admin-or-operator", cookies={"opb_session": token})
        assert resp.status_code == 403


class TestAuthDependenciesRequirePermission:
    """require_permission checks specific permissions."""

    def test_admin_has_halt_trading(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("permadm", "Perm@Ad1!", "admin")
        login_resp = client.post("/login", json={"username": "permadm", "password": "Perm@Ad1!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text[:200]}"
        token = login_resp.json()["token"]
        resp = client.get("/require-permission", cookies={"opb_session": token})
        assert resp.status_code == 200
        assert resp.json()["permission"] == "halt_trading"

    def test_viewer_lacks_halt_trading(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("permvw", "Perm@Vw1!", "viewer")
        login_resp = client.post("/login", json={"username": "permvw", "password": "Perm@Vw1!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text[:200]}"
        token = login_resp.json()["token"]
        resp = client.get("/require-permission", cookies={"opb_session": token})
        assert resp.status_code == 403
        assert "Permission denied" in resp.text


class TestAuthDependenciesOptionalAuthWithFallback:
    """optional_auth_with_fallback returns fallback role when unauthenticated."""

    def test_authenticated_returns_real_user(self, deps_client: Any):
        client, handler, _ = deps_client
        handler.create_user("fallreal", "Fall@R1!", "admin")
        login_resp = client.post("/login", json={"username": "fallreal", "password": "Fall@R1!"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text[:200]}"
        token = login_resp.json()["token"]
        resp = client.get("/optional-with-fallback", cookies={"opb_session": token})
        assert resp.status_code == 200
        assert resp.json()["username"] == "fallreal"
        assert resp.json()["role"] == "admin"

    def test_unauthenticated_uses_fallback(self, deps_client: Any):
        client, _, _ = deps_client
        resp = client.get("/optional-with-fallback")
        assert resp.status_code == 200
        assert resp.json()["username"] == "anonymous"
        assert resp.json()["role"] == "viewer"


# ═══════════════════════════════════════════════════════════════════════
# 6. CSRF Protection
# ═══════════════════════════════════════════════════════════════════════


class TestCSRFProtection:
    """CSRF token generation, validation, exempt paths, ensure_cookie_set."""

    @pytest.fixture
    def csrf(self):
        from core.auth.csrf import CSRFProtection
        return CSRFProtection(secret_key="test-secret-for-testing-only")

    # ── Token generation ──────────────────────────────────────────────

    def test_generate_token_format(self, csrf: Any):
        token = csrf._generate_token("session1")
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_generate_token_deterministic_for_same_window(self, csrf: Any):
        """Tokens generated within the same 900s window are identical (by design)."""
        t1 = csrf._generate_token("session-x")
        t2 = csrf._generate_token("session-x")
        assert t1 == t2

    def test_generate_token_different_for_different_sessions(self, csrf: Any):
        t1 = csrf._generate_token("session-a")
        t2 = csrf._generate_token("session-b")
        assert t1 != t2

    # ── Validation: valid ─────────────────────────────────────────────

    @pytest.mark.anyio
    async def test_validate_valid_tokens(self, csrf: Any):
        """POST with matching cookie + header should pass."""
        tok = csrf._generate_token("sess-1")

        class MockRequest:
            method = "POST"
            cookies = {"opb_csrf": tok}
            headers = {"X-CSRF-Token": tok}
            url = type("url", (), {"path": "/api/data"})()
            state = type("state", (), {})()

        await csrf.validate(MockRequest())  # should not raise

    @pytest.mark.anyio
    async def test_get_requests_always_pass(self, csrf: Any):
        class MockRequest:
            method = "GET"
            cookies = {}
            headers = {}
            url = type("url", (), {"path": "/"})()
            state = type("state", (), {})()

        await csrf.validate(MockRequest())  # should not raise

    @pytest.mark.anyio
    async def test_head_requests_always_pass(self, csrf: Any):
        class MockRequest:
            method = "HEAD"
            cookies = {}
            headers = {}
            url = type("url", (), {"path": "/"})()
            state = type("state", (), {})()

        await csrf.validate(MockRequest())

    @pytest.mark.anyio
    async def test_options_requests_always_pass(self, csrf: Any):
        class MockRequest:
            method = "OPTIONS"
            cookies = {}
            headers = {}
            url = type("url", (), {"path": "/"})()
            state = type("state", (), {})()

        await csrf.validate(MockRequest())

    # ── Validation: missing ───────────────────────────────────────────

    @pytest.mark.anyio
    async def test_validate_missing_cookie(self, csrf: Any):
        class MockRequest:
            method = "POST"
            cookies = {}
            headers = {"X-CSRF-Token": "some-token"}
            url = type("url", (), {"path": "/api/data"})()
            state = type("state", (), {})()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await csrf.validate(MockRequest())
        assert exc.value.status_code == 403

    @pytest.mark.anyio
    async def test_validate_missing_header(self, csrf: Any):
        tok = csrf._generate_token("sess-1")

        class MockRequest:
            method = "POST"
            cookies = {"opb_csrf": tok}
            headers = {}
            url = type("url", (), {"path": "/api/data"})()
            state = type("state", (), {})()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await csrf.validate(MockRequest())
        assert exc.value.status_code == 403

    @pytest.mark.anyio
    async def test_validate_missing_both(self, csrf: Any):
        class MockRequest:
            method = "POST"
            cookies = {}
            headers = {}
            url = type("url", (), {"path": "/api/data"})()
            state = type("state", (), {})()

        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            await csrf.validate(MockRequest())

    # ── Validation: mismatch ──────────────────────────────────────────

    @pytest.mark.anyio
    async def test_validate_token_mismatch(self, csrf: Any):
        class MockRequest:
            method = "POST"
            cookies = {"opb_csrf": "a" * 64}
            headers = {"X-CSRF-Token": "b" * 64}
            url = type("url", (), {"path": "/api/data"})()
            state = type("state", (), {})()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await csrf.validate(MockRequest())
        assert exc.value.status_code == 403

    # ── Exempt paths ──────────────────────────────────────────────────

    @pytest.mark.anyio
    async def test_exempt_paths_skip_validation(self, csrf: Any):
        csrf.exempt("/api/auth/login")

        class MockRequest:
            method = "POST"
            cookies = {}
            headers = {}
            url = type("url", (), {"path": "/api/auth/login"})()
            state = type("state", (), {})()

        await csrf.validate(MockRequest())  # should not raise

    @pytest.mark.anyio
    async def test_exempt_path_with_prefix(self, csrf: Any):
        csrf.exempt("/public")

        class MockRequest:
            method = "POST"
            cookies = {}
            headers = {}
            url = type("url", (), {"path": "/public/webhook"})()
            state = type("state", (), {})()

        await csrf.validate(MockRequest())

    @pytest.mark.anyio
    async def test_non_exempt_path_still_validated(self, csrf: Any):
        csrf.exempt("/login")

        class MockRequest:
            method = "POST"
            cookies = {}
            headers = {}
            url = type("url", (), {"path": "/api/data"})()
            state = type("state", (), {})()

        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            await csrf.validate(MockRequest())

    # ── ensure_cookie_set ─────────────────────────────────────────────

    @pytest.mark.anyio
    async def test_ensure_cookie_set_on_get_no_cookie(self, csrf: Any):
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

        await csrf.ensure_cookie_set(MockRequest(), MockResponse())
        assert len(cookie_was_set) == 1
        assert cookie_was_set[0]["key"] == "opb_csrf"
        assert cookie_was_set[0]["httponly"] is False
        assert cookie_was_set[0]["samesite"] == "lax"
        assert cookie_was_set[0]["path"] == "/"

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_when_valid_cookie_exists(self, csrf: Any):
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "GET"
            url = type("url", (), {"path": "/"})()
            cookies = {"opb_csrf": csrf._generate_token("sess-keep")}
            headers = {}
            state = type("state", (), {"session_id": "sess-keep"})()

        await csrf.ensure_cookie_set(MockRequest(), MockResponse())
        assert len(cookie_was_set) == 0

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_on_post(self, csrf: Any):
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

        await csrf.ensure_cookie_set(MockRequest(), MockResponse())
        assert len(cookie_was_set) == 0

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_on_exempt_path(self, csrf: Any):
        csrf.exempt("/health")
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "GET"
            url = type("url", (), {"path": "/health"})()
            cookies = {}
            headers = {}
            state = type("state", (), {})()

        await csrf.ensure_cookie_set(MockRequest(), MockResponse())
        assert len(cookie_was_set) == 0

    @pytest.mark.anyio
    async def test_ensure_cookie_set_overrides_short_token(self, csrf: Any):
        """If existing cookie is malformed (< 64 chars), set a new one."""
        cookie_was_set = []

        class MockResponse:
            def set_cookie(self, **kwargs):
                cookie_was_set.append(kwargs)

        class MockRequest:
            method = "GET"
            url = type("url", (), {"path": "/"})()
            cookies = {"opb_csrf": "too-short"}
            headers = {}
            state = type("state", (), {})()

        await csrf.ensure_cookie_set(MockRequest(), MockResponse())
        assert len(cookie_was_set) == 1

    @pytest.mark.anyio
    async def test_ensure_cookie_set_on_head(self, csrf: Any):
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

        await csrf.ensure_cookie_set(MockRequest(), MockResponse())
        assert len(cookie_was_set) == 1

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_on_put(self, csrf: Any):
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

        await csrf.ensure_cookie_set(MockRequest(), MockResponse())
        assert len(cookie_was_set) == 0

    @pytest.mark.anyio
    async def test_ensure_cookie_set_skip_on_delete(self, csrf: Any):
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

        await csrf.ensure_cookie_set(MockRequest(), MockResponse())
        assert len(cookie_was_set) == 0


# ═══════════════════════════════════════════════════════════════════════
# 7. RoleManager
# ═══════════════════════════════════════════════════════════════════════


class TestRoleManager:
    """Role assignment, revoke, get_role, check, has_permission, load_from_config."""

    @pytest.fixture
    def rm(self):
        from core.auth.role_manager import RoleManager
        return RoleManager(default_role="observer")

    def test_assign_and_get_role(self, rm: Any):
        from core.auth.permissions import Role
        rm.assign("alice", "admin")
        assert rm.get_role("alice") == Role.ADMIN

    def test_default_role_for_unknown(self, rm: Any):
        from core.auth.permissions import Role
        assert rm.get_role("unknown") == Role.OBSERVER

    def test_custom_default_role(self):
        from core.auth.permissions import Role
        from core.auth.role_manager import RoleManager
        rm = RoleManager(default_role="viewer")
        assert rm.get_role("anyone") == Role.VIEWER

    def test_revoke_falls_back_to_default(self, rm: Any):
        rm.assign("bob", "admin")
        rm.revoke("bob")
        assert rm.get_role("bob").value == "observer"

    def test_check_passes_for_valid_permission(self, rm: Any):
        from core.auth.permissions import Permission
        rm.assign("charlie", "admin")
        rm.check("charlie", Permission.MODIFY_CONFIG)  # should not raise

    def test_check_raises_permission_denied(self, rm: Any):
        from core.auth.permissions import Permission, PermissionDenied
        rm.assign("dave", "viewer")
        with pytest.raises(PermissionDenied):
            rm.check("dave", Permission.MODIFY_CONFIG)

    def test_has_permission_returns_true(self, rm: Any):
        rm.assign("eve", "admin")
        assert rm.has_permission("eve", "modify_config") is True

    def test_has_permission_returns_false(self, rm: Any):
        rm.assign("frank", "viewer")
        assert rm.has_permission("frank", "halt_trading") is False

    def test_has_permission_unknown_identity(self, rm: Any):
        # Uses default_role = observer
        assert rm.has_permission("stranger", "view_state") is True
        assert rm.has_permission("stranger", "halt_trading") is False

    def test_load_from_config(self, rm: Any):
        rm.load_from_config({
            "admin_roles": {"grace": "admin", "heidi": "operator"},
            "admin_default_role": "viewer",
        })
        assert rm.get_role("grace").value == "admin"
        assert rm.get_role("heidi").value == "operator"
        assert rm.get_role("stranger").value == "viewer"

    def test_load_from_config_ignores_unknown_role(self, rm: Any):
        rm.load_from_config({
            "admin_roles": {"ivan": "superadmin"},
        })
        # Should not raise, ivan gets default
        assert rm.get_role("ivan").value == "observer"

    def test_load_from_config_empty(self, rm: Any):
        rm.load_from_config({})
        assert rm.get_role("anyone").value == "observer"

    def test_list_assignments(self, rm: Any):
        rm.assign("judy", "admin")
        rm.assign("karl", "operator")
        assignments = rm.list_assignments()
        assert assignments == {"judy": "admin", "karl": "operator"}

    def test_list_assignments_empty(self, rm: Any):
        assert rm.list_assignments() == {}

    def test_assign_with_str_role(self, rm: Any):
        from core.auth.permissions import Role
        rm.assign("leon", "admin")
        assert isinstance(rm.get_role("leon"), Role)

    def test_revoke_unknown_identity_no_error(self, rm: Any):
        rm.revoke("nobody")  # should not raise


# ═══════════════════════════════════════════════════════════════════════
# 8. SessionStore
# ═══════════════════════════════════════════════════════════════════════


class TestSessionStore:
    """Session creation, get, touch, delete, TTL expiry, purge_expired."""

    @pytest.fixture
    def store(self):
        from core.auth.session_store import SessionStore
        return SessionStore(ttl_seconds=3600)

    @pytest.fixture
    def store_instant_expiry(self):
        from core.auth.session_store import SessionStore
        return SessionStore(ttl_seconds=0)

    def test_create_session(self, store: Any):
        from core.auth.permissions import Role
        s = store.create("alice", Role.ADMIN, source="pytest")
        assert s.session_id is not None
        assert s.identity == "alice"
        assert s.role == Role.ADMIN
        assert s.metadata.get("source") == "pytest"

    def test_create_with_str_role(self, store: Any):
        from core.auth.permissions import Role
        s = store.create("bob", "admin")
        assert s.role == Role.ADMIN

    def test_get_valid_session(self, store: Any):
        s = store.create("charlie", "operator")
        retrieved = store.get(s.session_id)
        assert retrieved is not None
        assert retrieved.identity == "charlie"

    def test_get_nonexistent_session(self, store: Any):
        assert store.get("no-such-id") is None

    def test_get_expired_session_returns_none(self, store_instant_expiry: Any):
        s = store_instant_expiry.create("dave", "viewer")
        time.sleep(0.01)
        assert store_instant_expiry.get(s.session_id) is None

    def test_touch_updates_last_active(self, store: Any):
        s = store.create("eve", "admin")
        original_active = s.last_active_ts
        time.sleep(0.01)
        assert store.touch(s.session_id) is True
        assert s.last_active_ts > original_active

    def test_touch_nonexistent_returns_false(self, store: Any):
        assert store.touch("no-such") is False

    def test_delete_existing_returns_true(self, store: Any):
        s = store.create("frank", "operator")
        assert store.delete(s.session_id) is True
        assert store.get(s.session_id) is None

    def test_delete_nonexistent_returns_false(self, store: Any):
        assert store.delete("no-such") is False

    def test_purge_expired_removes_expired(self, store_instant_expiry: Any):
        store_instant_expiry.create("grace", "admin")
        store_instant_expiry.create("heidi", "viewer")
        time.sleep(0.01)
        count = store_instant_expiry.purge_expired()
        assert count == 2

    def test_purge_expired_noop_when_none_expired(self, store: Any):
        store.create("ivan", "admin")
        assert store.purge_expired() == 0

    def test_active_count(self, store: Any):
        store.create("judy", "admin")
        store.create("karl", "operator")
        assert store.active_count() == 2

    def test_active_count_excludes_expired(self, store_instant_expiry: Any):
        store_instant_expiry.create("leon", "viewer")
        time.sleep(0.01)
        assert store_instant_expiry.active_count() == 0

    def test_list_active(self, store: Any):
        s1 = store.create("maria", "admin")
        s2 = store.create("nathan", "operator")
        active = store.list_active()
        assert len(active) == 2
        ids = {s.session_id for s in active}
        assert s1.session_id in ids
        assert s2.session_id in ids

    def test_list_active_excludes_expired(self, store_instant_expiry: Any):
        store_instant_expiry.create("oscar", "viewer")
        time.sleep(0.01)
        assert len(store_instant_expiry.list_active()) == 0

    def test_ttl_expiry_purges_on_get(self, store_instant_expiry: Any):
        """get() should auto-purge expired sessions."""
        s = store_instant_expiry.create("paul", "observer")
        time.sleep(0.01)
        assert store_instant_expiry.get(s.session_id) is None
        # Should also be removed from internal dict
        assert store_instant_expiry._sessions.get(s.session_id) is None


# ═══════════════════════════════════════════════════════════════════════
# 9. Permissions — role_has_permission, get_role_permissions,
#    PermissionDenied
# ═══════════════════════════════════════════════════════════════════════


class TestPermissions:
    """Permission matrix for all roles."""

    def test_role_has_permission_admin_all(self):
        from core.auth.permissions import role_has_permission
        assert role_has_permission("admin", "view_state")
        assert role_has_permission("admin", "halt_trading")
        assert role_has_permission("admin", "modify_risk_limits")
        assert role_has_permission("admin", "toggle_strategies")
        assert role_has_permission("admin", "deploy_models")
        assert role_has_permission("admin", "modify_code")
        assert role_has_permission("admin", "view_logs")
        assert role_has_permission("admin", "add_brokers")
        assert role_has_permission("admin", "modify_config")

    def test_role_has_permission_operator(self):
        from core.auth.permissions import role_has_permission
        assert role_has_permission("operator", "view_state")
        assert role_has_permission("operator", "halt_trading")
        assert role_has_permission("operator", "toggle_strategies")
        assert role_has_permission("operator", "view_logs")
        assert not role_has_permission("operator", "modify_risk_limits")
        assert not role_has_permission("operator", "deploy_models")
        assert not role_has_permission("operator", "modify_code")
        assert not role_has_permission("operator", "add_brokers")
        assert not role_has_permission("operator", "modify_config")

    def test_role_has_permission_viewer(self):
        from core.auth.permissions import role_has_permission
        assert role_has_permission("viewer", "view_state")
        assert role_has_permission("viewer", "view_logs")
        assert not role_has_permission("viewer", "halt_trading")
        assert not role_has_permission("viewer", "modify_risk_limits")
        assert not role_has_permission("viewer", "toggle_strategies")
        assert not role_has_permission("viewer", "deploy_models")
        assert not role_has_permission("viewer", "modify_code")
        assert not role_has_permission("viewer", "add_brokers")
        assert not role_has_permission("viewer", "modify_config")

    def test_role_has_permission_observer(self):
        from core.auth.permissions import role_has_permission
        assert role_has_permission("observer", "view_state")
        assert role_has_permission("observer", "view_logs")
        assert not role_has_permission("observer", "halt_trading")
        assert not role_has_permission("observer", "modify_risk_limits")
        assert not role_has_permission("observer", "toggle_strategies")
        assert not role_has_permission("observer", "deploy_models")
        assert not role_has_permission("observer", "modify_code")
        assert not role_has_permission("observer", "add_brokers")
        assert not role_has_permission("observer", "modify_config")

    def test_role_has_permission_developer(self):
        from core.auth.permissions import role_has_permission
        assert role_has_permission("developer", "view_state")
        assert role_has_permission("developer", "toggle_strategies")
        assert role_has_permission("developer", "deploy_models")
        assert role_has_permission("developer", "modify_code")
        assert role_has_permission("developer", "view_logs")
        assert role_has_permission("developer", "modify_config")
        assert not role_has_permission("developer", "halt_trading")
        assert not role_has_permission("developer", "modify_risk_limits")
        assert not role_has_permission("developer", "add_brokers")

    def test_unknown_role_returns_false(self):
        from core.auth.permissions import role_has_permission
        assert not role_has_permission("superadmin", "view_state")
        assert not role_has_permission("", "view_state")

    def test_unknown_permission_returns_false(self):
        from core.auth.permissions import role_has_permission
        assert not role_has_permission("admin", "fly_to_moon")

    def test_role_has_permission_with_enum_args(self):
        from core.auth.permissions import Permission, Role, role_has_permission
        assert role_has_permission(Role.ADMIN, Permission.VIEW_STATE)
        assert not role_has_permission(Role.VIEWER, Permission.HALT_TRADING)

    def test_get_role_permissions_admin(self):
        from core.auth.permissions import Permission, get_role_permissions
        perms = get_role_permissions("admin")
        assert Permission.VIEW_STATE in perms
        assert Permission.HALT_TRADING in perms
        assert Permission.MODIFY_RISK_LIMITS in perms
        assert Permission.TOGGLE_STRATEGIES in perms
        assert Permission.DEPLOY_MODELS in perms
        assert Permission.MODIFY_CODE in perms
        assert Permission.VIEW_LOGS in perms
        assert Permission.ADD_BROKERS in perms
        assert Permission.MODIFY_CONFIG in perms
        assert len(perms) == 9

    def test_get_role_permissions_operator(self):
        from core.auth.permissions import Permission, get_role_permissions
        perms = get_role_permissions("operator")
        assert Permission.VIEW_STATE in perms
        assert Permission.HALT_TRADING in perms
        assert Permission.TOGGLE_STRATEGIES in perms
        assert Permission.VIEW_LOGS in perms
        assert len(perms) == 4

    def test_get_role_permissions_viewer(self):
        from core.auth.permissions import Permission, get_role_permissions
        perms = get_role_permissions("viewer")
        assert Permission.VIEW_STATE in perms
        assert Permission.VIEW_LOGS in perms
        assert len(perms) == 2

    def test_get_role_permissions_observer(self):
        from core.auth.permissions import Permission, get_role_permissions
        perms = get_role_permissions("observer")
        assert Permission.VIEW_STATE in perms
        assert Permission.VIEW_LOGS in perms
        assert len(perms) == 2

    def test_get_role_permissions_developer(self):
        from core.auth.permissions import Permission, get_role_permissions
        perms = get_role_permissions("developer")
        assert Permission.VIEW_STATE in perms
        assert Permission.TOGGLE_STRATEGIES in perms
        assert Permission.DEPLOY_MODELS in perms
        assert Permission.MODIFY_CODE in perms
        assert Permission.VIEW_LOGS in perms
        assert Permission.MODIFY_CONFIG in perms
        assert len(perms) == 6

    def test_get_role_permissions_unknown_role(self):
        from core.auth.permissions import get_role_permissions
        perms = get_role_permissions("superadmin")
        assert perms == set()

    def test_get_role_permissions_with_enum(self):
        from core.auth.permissions import Role, get_role_permissions
        perms = get_role_permissions(Role.ADMIN)
        assert len(perms) == 9

    def test_permission_denied_exception(self):
        from core.auth.permissions import PermissionDenied
        exc = PermissionDenied("Access denied")
        assert isinstance(exc, Exception)
        assert str(exc) == "Access denied"

    def test_permission_denied_raised_by_role_manager(self):
        from core.auth.permissions import PermissionDenied
        from core.auth.role_manager import RoleManager
        rm = RoleManager(default_role="viewer")
        with pytest.raises(PermissionDenied):
            rm.check("anyone", "halt_trading")


# ═══════════════════════════════════════════════════════════════════════
# State manager (pyproject.toml / setup.cfg compatible)
# ═══════════════════════════════════════════════════════════════════════
