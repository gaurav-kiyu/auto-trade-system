"""Tests for core/auth/handler.py - AuthHandler with password hashing, sessions, brute-force protection."""

from __future__ import annotations

import os
import threading
import time
from unittest.mock import patch

import pytest
from core.auth.handler import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    DEFAULT_ADMIN_USERNAME,
    MAX_CONCURRENT_SESSIONS,
    MIN_PASSWORD_LENGTH,
    SESSION_COOKIE_NAME,
    TOKEN_TTL_SECONDS,
    AuthHandler,
    AuthToken,
    AuthUser,
    generate_csrf_token,
    generate_token,
    hash_password,
    validate_password_strength,
    verify_password,
)

# ── Password Utilities ────────────────────────────────────────────────────────


class TestHashPassword:
    def test_hash_returns_string(self):
        h = hash_password("test123!")
        assert isinstance(h, str)
        assert "$" in h

    def test_hash_contains_salt_and_digest(self):
        h = hash_password("test123!")
        parts = h.split("$")
        assert len(parts) == 3
        assert parts[0].isdigit()  # iterations
        assert len(bytes.fromhex(parts[1])) == 32  # 32-byte salt
        assert len(bytes.fromhex(parts[2])) == 32  # 32-byte hash

    def test_unique_salts(self):
        h1 = hash_password("test123!")
        h2 = hash_password("test123!")
        assert h1 != h2  # Different salts


class TestVerifyPassword:
    def test_verify_correct(self):
        h = hash_password("myPass123!")
        assert verify_password("myPass123!", h) is True

    def test_verify_incorrect(self):
        h = hash_password("myPass123!")
        assert verify_password("wrongPass!", h) is False

    def test_verify_empty_password(self):
        h = hash_password("myPass123!")
        assert verify_password("", h) is False

    def test_verify_malformed_hash(self):
        assert verify_password("test", "invalid_hash") is False
        assert verify_password("test", "") is False


class TestValidatePasswordStrength:
    def test_min_length_fails(self):
        valid, msg = validate_password_strength("Ab1!")
        assert valid is False
        assert "at least" in msg

    def test_missing_uppercase(self):
        valid, msg = validate_password_strength("abcd1234!")
        assert valid is False
        assert "uppercase" in msg

    def test_missing_lowercase(self):
        valid, msg = validate_password_strength("ABCD1234!")
        assert valid is False
        assert "lowercase" in msg

    def test_missing_digit(self):
        valid, msg = validate_password_strength("Abcdefgh!")
        assert valid is False
        assert "digit" in msg

    def test_missing_special(self):
        valid, msg = validate_password_strength("Abcdefgh1")
        assert valid is False
        assert "special" in msg

    def test_common_word_fails(self):
        valid, msg = validate_password_strength("Password123!")
        assert valid is False
        assert "common" in msg

    def test_valid_strong_password(self):
        valid, msg = validate_password_strength("MySecureP@ss1")
        assert valid is True
        assert msg == ""


class TestGenerateToken:
    def test_token_length(self):
        t = generate_token()
        assert len(t) == 96  # TOKEN_BYTES=48, hex => 96 chars

    def test_unique_tokens(self):
        t1 = generate_token()
        t2 = generate_token()
        assert t1 != t2


class TestGenerateCsrfToken:
    def test_csrf_token_length(self):
        t = generate_csrf_token()
        assert len(t) == 64  # 32 bytes hex => 64 chars

    def test_unique_csrf_tokens(self):
        t1 = generate_csrf_token()
        t2 = generate_csrf_token()
        assert t1 != t2


# ── AuthHandler Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def auth(tmp_path) -> AuthHandler:
    """AuthHandler with isolated temp DB."""
    db_path = str(tmp_path / "test_auth.db")
    return AuthHandler(db_path=db_path)


@pytest.fixture
def auth_with_user(auth: AuthHandler) -> AuthHandler:
    """AuthHandler with a pre-created test user."""
    auth.create_user("testuser", "TestPass123!", "operator")
    return auth


# ── Initialization ────────────────────────────────────────────────────────────


class TestInit:
    def test_init_creates_db(self, tmp_path):
        db_path = str(tmp_path / "new_auth.db")
        AuthHandler(db_path=db_path)
        assert os.path.exists(db_path)

    def test_init_creates_default_admin(self, auth: AuthHandler):
        users = auth.list_users()
        usernames = [u["username"] for u in users]
        assert DEFAULT_ADMIN_USERNAME in usernames

    def test_init_default_admin_must_change_password(self, auth: AuthHandler):
        admin = auth.get_user(DEFAULT_ADMIN_USERNAME)
        assert admin is not None
        assert admin.must_change_password is True

    def test_init_creates_tables(self, auth: AuthHandler):
        """Verify that all required tables were created."""
        import sqlite3
        conn = sqlite3.connect(auth._db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('users', 'sessions', 'audit_log', 'account_lockouts')"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "users" in tables
        assert "sessions" in tables
        assert "audit_log" in tables
        assert "account_lockouts" in tables


# ── User Management ───────────────────────────────────────────────────────────


class TestCreateUser:
    def test_create_user_success(self, auth: AuthHandler):
        result = auth.create_user("newuser", "ValidPass1!", "viewer")
        assert result["success"] is True
        assert result["username"] == "newuser"

    def test_create_user_duplicate(self, auth_with_user: AuthHandler):
        result = auth_with_user.create_user("testuser", "OtherPass1!", "viewer")
        assert result["success"] is False
        assert "already exists" in result.get("error", "")

    def test_create_user_invalid_role(self, auth: AuthHandler):
        result = auth.create_user("user", "ValidPass1!", "superadmin")
        assert result["success"] is False
        assert "Invalid role" in result.get("error", "")

    def test_create_user_short_username(self, auth: AuthHandler):
        result = auth.create_user("ab", "ValidPass1!", "viewer")
        assert result["success"] is False

    def test_create_user_weak_password(self, auth: AuthHandler):
        result = auth.create_user("user", "weak", "viewer")
        assert result["success"] is False

    def test_create_user_strips_whitespace(self, auth: AuthHandler):
        result = auth.create_user("  Alice  ", "ValidPass1!", "viewer")
        assert result["success"] is True
        assert result["username"] == "alice"

    def test_create_user_lowercases_username(self, auth: AuthHandler):
        auth.create_user("Alice", "ValidPass1!", "viewer")
        # Should be stored as lowercase
        user = auth.get_user("Alice")
        assert user is not None
        assert user.username == "alice"


class TestAuthenticate:
    def test_authenticate_success(self, auth_with_user: AuthHandler):
        user = auth_with_user.authenticate("testuser", "TestPass123!", "127.0.0.1")
        assert user is not None
        assert user.username == "testuser"
        assert user.role == "operator"

    def test_authenticate_wrong_password(self, auth_with_user: AuthHandler):
        user = auth_with_user.authenticate("testuser", "WrongPass1!", "127.0.0.1")
        assert user is None

    def test_authenticate_nonexistent(self, auth_with_user: AuthHandler):
        user = auth_with_user.authenticate("nonexistent", "TestPass123!", "127.0.0.1")
        assert user is None

    def test_authenticate_disabled_user(self, auth_with_user: AuthHandler):
        auth_with_user.disable_user("testuser", "admin")
        user = auth_with_user.authenticate("testuser", "TestPass123!", "127.0.0.1")
        assert user is None

    def test_authenticate_updates_last_login(self, auth_with_user: AuthHandler):
        original = auth_with_user.get_user("testuser")
        assert original is not None
        original_ts = original.last_login_ts
        time.sleep(0.01)
        auth_with_user.authenticate("testuser", "TestPass123!", "127.0.0.1")
        updated = auth_with_user.get_user("testuser")
        assert updated is not None
        assert updated.last_login_ts is not None
        if original_ts is not None:
            assert updated.last_login_ts > original_ts
        else:
            assert updated.last_login_ts is not None


class TestGetUser:
    def test_get_user_by_username(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        assert user.role == "operator"

    def test_get_user_case_insensitive(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("TestUser")
        assert user is not None

    def test_get_user_nonexistent(self, auth: AuthHandler):
        user = auth.get_user("nonexistent")
        assert user is None


class TestGetUserById:
    def test_get_user_by_id(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        by_id = auth_with_user.get_user_by_id(user.user_id)
        assert by_id is not None
        assert by_id.username == "testuser"

    def test_get_user_by_id_nonexistent(self, auth: AuthHandler):
        assert auth.get_user_by_id("nonexistent") is None


class TestListUsers:
    def test_list_users(self, auth: AuthHandler):
        users = auth.list_users()
        assert len(users) >= 1  # At least default admin

    def test_list_users_includes_metadata(self, auth_with_user: AuthHandler):
        users = auth_with_user.list_users()
        usernames = [u["username"] for u in users]
        assert "testuser" in usernames
        assert "admin" in usernames

    def test_list_users_sorted(self, auth: AuthHandler):
        auth.create_user("b", "ValidPass1!", "viewer")
        auth.create_user("a", "ValidPass1!", "viewer")
        users = auth.list_users()
        # Should be ordered by created_ts, not username
        timestamps = [u["created_ts"] for u in users]
        assert timestamps == sorted(timestamps)


class TestUpdatePassword:
    def test_update_password_success(self, auth_with_user: AuthHandler):
        result = auth_with_user.update_password("testuser", "TestPass123!", "NewValid1!")
        assert result["success"] is True

    def test_update_password_wrong_current(self, auth_with_user: AuthHandler):
        result = auth_with_user.update_password("testuser", "WrongPass1!", "NewValid1!")
        assert result["success"] is False
        assert "incorrect" in result.get("error", "")

    def test_update_password_weak_new(self, auth_with_user: AuthHandler):
        result = auth_with_user.update_password("testuser", "TestPass123!", "weak")
        assert result["success"] is False

    def test_update_password_nonexistent(self, auth: AuthHandler):
        result = auth.update_password("nonexistent", "Pass123!", "NewValid1!")
        assert result["success"] is False


class TestAdminResetPassword:
    def test_admin_reset_success(self, auth_with_user: AuthHandler):
        result = auth_with_user.admin_reset_password("testuser", "NewValid1!", "admin")
        assert result["success"] is True
        # User should be able to login with new password
        user = auth_with_user.authenticate("testuser", "NewValid1!", "127.0.0.1")
        assert user is not None

    def test_admin_reset_sets_must_change(self, auth_with_user: AuthHandler):
        auth_with_user.admin_reset_password("testuser", "NewValid1!", "admin")
        user = auth_with_user.get_user("testuser")
        assert user is not None
        assert user.must_change_password is True

    def test_admin_reset_nonexistent(self, auth: AuthHandler):
        result = auth.admin_reset_password("nonexistent", "NewValid1!", "admin")
        assert result["success"] is False


class TestUpdateUserRole:
    def test_update_role_success(self, auth_with_user: AuthHandler):
        result = auth_with_user.update_user_role("testuser", "admin", "admin")
        assert result["success"] is True
        user = auth_with_user.get_user("testuser")
        assert user is not None
        assert user.role == "admin"

    def test_update_role_invalid(self, auth_with_user: AuthHandler):
        result = auth_with_user.update_user_role("testuser", "superadmin", "admin")
        assert result["success"] is False

    def test_update_role_nonexistent(self, auth: AuthHandler):
        result = auth.update_user_role("nonexistent", "admin", "admin")
        assert result["success"] is False


class TestDisableEnableUser:
    def test_disable_user(self, auth_with_user: AuthHandler):
        result = auth_with_user.disable_user("testuser", "admin")
        assert result["success"] is True
        user = auth_with_user.get_user("testuser")
        assert user is not None
        assert user.disabled is True

    def test_enable_user(self, auth_with_user: AuthHandler):
        auth_with_user.disable_user("testuser", "admin")
        result = auth_with_user.enable_user("testuser", "admin")
        assert result["success"] is True
        user = auth_with_user.get_user("testuser")
        assert user is not None
        assert user.disabled is False


class TestDeleteUser:
    def test_delete_user(self, auth_with_user: AuthHandler):
        result = auth_with_user.delete_user("testuser", "admin")
        assert result["success"] is True
        assert auth_with_user.get_user("testuser") is None

    def test_delete_admin_protected(self, auth: AuthHandler):
        result = auth.delete_user(DEFAULT_ADMIN_USERNAME, "admin")
        assert result["success"] is False
        assert "default admin" in result.get("error", "").lower()


# ── Session / Token Management ────────────────────────────────────────────────


class TestCreateSession:
    def test_create_session_returns_token(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        token = auth_with_user.create_session(user, "127.0.0.1", "test-agent")
        assert isinstance(token, AuthToken)
        assert token.username == "testuser"
        assert token.role == "operator"
        assert token.csrf_token != ""

    def test_create_session_includes_csrf(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        token = auth_with_user.create_session(user)
        assert len(token.csrf_token) == 64  # 32 bytes hex

    def test_create_session_enforces_max_concurrent(self, auth_with_user: AuthHandler):
        """Creating more than MAX_CONCURRENT_SESSIONS should evict oldest."""
        user = auth_with_user.get_user("testuser")
        assert user is not None
        tokens = []
        for _ in range(MAX_CONCURRENT_SESSIONS + 2):
            t = auth_with_user.create_session(user, "127.0.0.1")
            tokens.append(t)
        # Should have at most MAX_CONCURRENT_SESSIONS active
        active = sum(1 for t in tokens if auth_with_user.verify_session(t.token) is not None)
        assert active <= MAX_CONCURRENT_SESSIONS


class TestVerifySession:
    def test_verify_valid_session(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        token = auth_with_user.create_session(user, "127.0.0.1")
        verified = auth_with_user.verify_session(token.token)
        assert verified is not None
        assert verified.username == "testuser"

    def test_verify_expired_session(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        token = auth_with_user.create_session(user, "127.0.0.1")
        # Manually expire the token
        token.expires_ts = time.time() - 1
        verified = auth_with_user.verify_session(token.token)
        assert verified is None

    def test_verify_nonexistent_session(self, auth: AuthHandler):
        verified = auth.verify_session("nonexistent_token")
        assert verified is None

    def test_verify_empty_token(self, auth: AuthHandler):
        verified = auth.verify_session("")
        assert verified is None


class TestRevokeSession:
    def test_revoke_existing(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        token = auth_with_user.create_session(user)
        result = auth_with_user.revoke_session(token.token)
        assert result is True
        assert auth_with_user.verify_session(token.token) is None

    def test_revoke_nonexistent(self, auth: AuthHandler):
        result = auth.revoke_session("nonexistent")
        assert result is False


class TestRevokeAllUserSessions:
    def test_revoke_all(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        # Create multiple sessions
        token1 = auth_with_user.create_session(user)
        token2 = auth_with_user.create_session(user)
        count = auth_with_user.revoke_all_user_sessions("testuser")
        assert count == 2
        assert auth_with_user.verify_session(token1.token) is None
        assert auth_with_user.verify_session(token2.token) is None

    def test_revoke_all_nonexistent(self, auth: AuthHandler):
        count = auth.revoke_all_user_sessions("nonexistent")
        assert count == 0


class TestGetUserSessions:
    def test_get_user_sessions(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        auth_with_user.create_session(user, "127.0.0.1")
        sessions = auth_with_user.get_user_sessions(user.user_id)
        assert len(sessions) >= 1
        assert sessions[0]["ip_address"] == "127.0.0.1"

    def test_get_user_sessions_empty(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        sessions = auth_with_user.get_user_sessions(user.user_id)
        assert len(sessions) == 0


# ── Brute-force / Rate Limiting ──────────────────────────────────────────────


class TestRateLimiting:
    def test_rate_limited_ip_blocked(self, auth: AuthHandler):
        """Exceeding BRUTE_FORCE_MAX_ATTEMPTS from same IP should block."""
        for _ in range(15):
            auth._record_attempt("10.0.0.1", False)
        assert auth._is_rate_limited("10.0.0.1") is True

    def test_localhost_not_rate_limited(self, auth: AuthHandler):
        """Localhost should never be rate limited."""
        for _ in range(20):
            auth._record_attempt("127.0.0.1", False)
        assert auth._is_rate_limited("127.0.0.1") is False

    def test_rate_limit_window_expires(self, auth: AuthHandler):
        """Rate limit should expire after BRUTE_FORCE_WINDOW_SECONDS."""
        ip = "10.0.0.1"
        for _ in range(10):
            auth._record_attempt(ip, False)
        # Mock time to advance past the window
        original_time = time.time
        try:
            time.time = lambda: original_time() + 120  # 2 minutes later
            assert auth._is_rate_limited(ip) is False
        finally:
            time.time = original_time


class TestAccountLockout:
    def test_lockout_after_max_attempts(self, auth_with_user: AuthHandler):
        """After MAX_LOGIN_ATTEMPTS failed logins, account should lock."""
        for _ in range(6):
            auth_with_user.authenticate("testuser", "WrongPass1!", "10.0.0.1")
        # Should be locked
        user = auth_with_user.authenticate("testuser", "TestPass123!", "10.0.0.1")
        assert user is None  # Locked out despite correct password

    def test_lockout_clears_on_success(self, auth_with_user: AuthHandler):
        """A successful login should clear lockout state."""
        # Trigger some failures
        for _ in range(3):
            auth_with_user.authenticate("testuser", "WrongPass1!", "10.0.0.1")
        # Then succeed
        user = auth_with_user.authenticate("testuser", "TestPass123!", "10.0.0.1")
        assert user is not None


# ── Session Refresh ───────────────────────────────────────────────────────────


class TestRefreshSession:
    def test_refresh_valid_session(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        token = auth_with_user.create_session(user)
        original_expiry = token.expires_ts
        time.sleep(0.01)
        refreshed = auth_with_user.refresh_session(token.token)
        assert refreshed is not None
        assert refreshed.expires_ts > original_expiry

    def test_refresh_expired_session(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        token = auth_with_user.create_session(user)
        token.expires_ts = time.time() - 1
        refreshed = auth_with_user.refresh_session(token.token)
        assert refreshed is None

    def test_refresh_nonexistent(self, auth: AuthHandler):
        result = auth.refresh_session("nonexistent")
        assert result is None


# ── Password Reset Tokens ─────────────────────────────────────────────────────


class TestPasswordResetToken:
    def test_create_reset_token(self, auth_with_user: AuthHandler):
        token = auth_with_user.create_password_reset_token("testuser")
        assert token is not None
        assert len(token) > 20

    def test_create_reset_token_nonexistent(self, auth: AuthHandler):
        token = auth.create_password_reset_token("nonexistent")
        assert token is None

    def test_verify_reset_token(self, auth_with_user: AuthHandler):
        token = auth_with_user.create_password_reset_token("testuser")
        assert token is not None
        username = auth_with_user.verify_password_reset_token(token)
        assert username == "testuser"

    def test_verify_reset_token_used_once(self, auth_with_user: AuthHandler):
        token = auth_with_user.create_password_reset_token("testuser")
        assert token is not None
        # First use should succeed
        username = auth_with_user.verify_password_reset_token(token)
        assert username == "testuser"
        # Second use should fail (already marked as used)
        username2 = auth_with_user.verify_password_reset_token(token)
        assert username2 is None

    def test_verify_expired_token(self, auth_with_user: AuthHandler):
        token = auth_with_user.create_password_reset_token("testuser")
        assert token is not None
        # Advance time past 1-hour expiry
        with patch("time.time", return_value=time.time() + 4000):
            username = auth_with_user.verify_password_reset_token(token)
            assert username is None

    def test_verify_invalid_token(self, auth: AuthHandler):
        result = auth.verify_password_reset_token("invalid")
        assert result is None


# ── Audit Log ─────────────────────────────────────────────────────────────────


class TestAuditLog:
    def test_audit_log_records_events(self, auth_with_user: AuthHandler):
        auth_with_user.authenticate("testuser", "TestPass123!", "10.0.0.1")
        logs = auth_with_user.get_audit_log(limit=10)
        assert len(logs) >= 1
        assert logs[0]["event_type"] == "login_success"

    def test_audit_log_filter(self, auth_with_user: AuthHandler):
        auth_with_user.authenticate("testuser", "TestPass123!", "10.0.0.1")
        auth_with_user.authenticate("testuser", "WrongPass1!", "10.0.0.2")
        failed = auth_with_user.get_audit_log(limit=10, event_type="login_failed")
        assert len(failed) >= 1
        assert failed[0]["event_type"] == "login_failed"

    def test_audit_log_limit(self, auth_with_user: AuthHandler):
        for _ in range(5):
            auth_with_user.authenticate("testuser", "TestPass123!", "10.0.0.1")
        logs = auth_with_user.get_audit_log(limit=3)
        assert len(logs) <= 3


# ── Cleanup ───────────────────────────────────────────────────────────────────


class TestPurgeExpiredSessions:
    def test_purge_expired(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        auth_with_user.create_session(user)
        # Create a very short-lived handler to test purge with real expiry
        short_handler = AuthHandler(db_path=auth_with_user._db_path, token_ttl=1)
        short_user = short_handler.get_user("testuser")
        assert short_user is not None
        short_token = short_handler.create_session(short_user)
        # Wait for it to naturally expire
        time.sleep(1.1)
        count = short_handler.purge_expired_sessions()
        assert count >= 1
        assert short_handler.verify_session(short_token.token) is None

    def test_purge_no_expired(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        auth_with_user.create_session(user)
        count = auth_with_user.purge_expired_sessions()
        assert count == 0


class TestGetStats:
    def test_get_stats(self, auth_with_user: AuthHandler):
        stats = auth_with_user.get_stats()
        assert "active_sessions" in stats
        assert "total_users" in stats
        assert "locked_accounts" in stats
        assert "failed_logins_24h" in stats
        assert stats["total_users"] >= 2  # admin + testuser

    def test_get_stats_after_session(self, auth_with_user: AuthHandler):
        user = auth_with_user.get_user("testuser")
        assert user is not None
        auth_with_user.create_session(user)
        stats = auth_with_user.get_stats()
        assert stats["active_sessions"] >= 1

    def test_get_stats_after_failed_login(self, auth_with_user: AuthHandler):
        auth_with_user.authenticate("testuser", "WrongPass1!", "10.0.0.1")
        stats = auth_with_user.get_stats()
        assert stats["failed_logins_24h"] >= 1


# ── Thread Safety ─────────────────────────────────────────────────────────────


class TestAuthHandlerThreadSafety:
    def test_concurrent_authenticate(self, auth_with_user: AuthHandler):
        """Multiple concurrent authentication attempts should be safe."""
        errors = []
        lock = threading.Lock()

        def _login():
            try:
                auth_with_user.authenticate("testuser", "TestPass123!", "10.0.0.1")
            except Exception as e:
                with lock:
                    errors.append(e)

        # Use many concurrent threads to stress-test
        threads = [threading.Thread(target=_login) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_session_create(self, auth_with_user: AuthHandler):
        """Concurrent session creation should be thread-safe."""
        user = auth_with_user.get_user("testuser")
        assert user is not None
        errors = []
        lock = threading.Lock()

        def _create_session():
            try:
                auth_with_user.create_session(user, "10.0.0.1")
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=_create_session) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_verify_and_revoke(self, auth_with_user: AuthHandler):
        """Concurrent verify/revoke should not crash."""
        user = auth_with_user.get_user("testuser")
        assert user is not None
        tokens = [auth_with_user.create_session(user) for _ in range(5)]
        errors = []

        def _verify(t):
            try:
                auth_with_user.verify_session(t.token)
            except Exception as e:
                errors.append(e)

        def _revoke(t):
            try:
                auth_with_user.revoke_session(t.token)
            except Exception as e:
                errors.append(e)

        threads = []
        for t in tokens:
            threads.append(threading.Thread(target=_verify, args=(t,)))
            threads.append(threading.Thread(target=_revoke, args=(t,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_user_ops(self, auth: AuthHandler):
        """Concurrent user create/delete operations should be thread-safe."""
        errors = []

        def _create_user(i):
            try:
                auth.create_user(f"bulk_user_{i}", f"ValidPass{i}!", "viewer")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_create_user, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(auth.list_users()) >= 20


# ── AuthUser / AuthToken Data Classes ─────────────────────────────────────────


class TestAuthUser:
    def test_to_dict(self):
        user = AuthUser(user_id="uid1", username="alice", role="operator",
                        display_name="Alice")
        d = user.to_dict()
        assert d["username"] == "alice"
        assert d["role"] == "operator"
        assert d["display_name"] == "Alice"

    def test_to_dict_excludes_hash(self):
        user = AuthUser(user_id="uid1", username="alice", role="viewer")
        d = user.to_dict()
        assert "password_hash" not in d


class TestAuthToken:
    def test_is_expired_false(self):
        token = AuthToken(
            token="abc", user_id="uid1", username="alice", role="admin",
            created_ts=time.time(), expires_ts=time.time() + 3600,
        )
        assert token.is_expired() is False

    def test_is_expired_true(self):
        token = AuthToken(
            token="abc", user_id="uid1", username="alice", role="admin",
            created_ts=time.time() - 10, expires_ts=time.time() - 1,
        )
        assert token.is_expired() is True

    def test_to_dict(self):
        token = AuthToken(
            token="abc", user_id="uid1", username="alice", role="admin",
            created_ts=1000, expires_ts=2000, csrf_token="csrf123",
        )
        d = token.to_dict()
        assert d["username"] == "alice"
        assert d["csrf_token"] == "csrf123"
        assert d["expires_in"] >= 0


# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_session_cookie_name(self):
        assert SESSION_COOKIE_NAME == "opb_session"

    def test_csrf_constants(self):
        assert CSRF_COOKIE_NAME == "opb_csrf"
        assert CSRF_HEADER_NAME == "X-CSRF-Token"

    def test_token_ttl_default(self):
        assert TOKEN_TTL_SECONDS == 3600

    def test_min_password_length(self):
        assert MIN_PASSWORD_LENGTH == 8
