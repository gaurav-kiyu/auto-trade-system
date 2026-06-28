"""
AD-KIYU Enterprise Auth Handler - password hashing, JWT tokens,
session management, brute-force protection, account lockout.

This module contains the AuthHandler class.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
import uuid
from typing import Any

from core.auth.handler.constants import (
    BRUTE_FORCE_MAX_ATTEMPTS,
    BRUTE_FORCE_WINDOW_SECONDS,
    DEFAULT_ADMIN_USERNAME,
    LOCKOUT_DURATION_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    TOKEN_TTL_SECONDS,
)
from core.auth.handler.mfa_handler import MfaHandlerMixin
from core.auth.handler.models import AuthToken, AuthUser, PasswordResetToken
from core.auth.handler.password import (
    generate_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from core.auth.handler.session_manager import SessionManagerMixin
from core.db_utils import get_connection
from core.exceptions import DatabaseError

_log = logging.getLogger(__name__)


class AuthHandler(MfaHandlerMixin, SessionManagerMixin):
    """Thread-safe authentication handler with SQLite-backed user storage.

    Inherits MFA management from MfaHandlerMixin and
    session/token management from SessionManagerMixin.
    """

    def __init__(self, db_path: str = "auth.db", token_ttl: int = TOKEN_TTL_SECONDS):
        self._db_path = db_path
        self._token_ttl = token_ttl
        self._lock = threading.RLock()

        # In-memory caches
        self._tokens: dict[str, AuthToken] = {}
        self._refresh_tokens: dict[str, AuthToken] = {}
        self._login_attempts: dict[str, list[float]] = {}  # ip -> [timestamps]
        self._account_lockouts: dict[str, float] = {}  # username -> unlock_ts
        self._password_reset_tokens: dict[str, PasswordResetToken] = {}

        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = get_connection(self._db_path, busy_timeout_ms=3000)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize auth database schema."""
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'viewer',
                    display_name TEXT DEFAULT '',
                    must_change_password INTEGER DEFAULT 0,
                    disabled INTEGER DEFAULT 0,
                    created_ts REAL NOT NULL,
                    last_login_ts REAL,
                    metadata TEXT DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    created_ts REAL NOT NULL,
                    expires_ts REAL NOT NULL,
                    ip_address TEXT DEFAULT '',
                    user_agent TEXT DEFAULT '',
                    revoked INTEGER DEFAULT 0,
                    token_data TEXT DEFAULT '{}',
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    username TEXT,
                    ip_address TEXT,
                    details TEXT DEFAULT '{}',
                    success INTEGER DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
                CREATE TABLE IF NOT EXISTS account_lockouts (
                    username TEXT PRIMARY KEY,
                    unlock_ts REAL NOT NULL,
                    created_ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    expires_ts REAL NOT NULL,
                    used INTEGER DEFAULT 0,
                    created_ts REAL NOT NULL
                )""")
            conn.commit()
            # Migration: add token_data column if missing (backward compat)
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN token_data TEXT DEFAULT '{}'")
                conn.commit()
            except (sqlite3.Error, OSError):
                _log.warning("[AUTH] ALTER TABLE migration skipped")
            # Migration: add MFA columns (v2.53+)
            for col, col_type in [("mfa_secret", "TEXT DEFAULT ''"),
                                  ("mfa_enabled", "INTEGER DEFAULT 0"),
                                  ("mfa_recovery_codes", "TEXT DEFAULT '[]'")]:
                try:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                    _log.info("[AUTH] Added MFA column: %s", col)
                except (sqlite3.Error, OSError):
                    _log.debug("[AUTH] MFA column %s already exists", col)
            conn.commit()

            # Create default admin if not exists
            cursor = conn.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                self._create_default_admin(conn)
        finally:
            conn.close()

    def _create_default_admin(self, conn: sqlite3.Connection) -> None:
        """Create default admin user with must_change_password flag."""
        default_pass = os.environ.get("OPBUYING_DEFAULT_ADMIN_PASSWORD", secrets.token_hex(16))
        pwd_hash = hash_password(default_pass)
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, role, display_name, must_change_password, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex[:16], DEFAULT_ADMIN_USERNAME, pwd_hash, "admin", "Administrator", 1, time.time()),
        )
        conn.commit()
        _log.warning("[AUTH] Default admin user created - FORCE PASSWORD CHANGE REQUIRED")

    # ── User management ────────────────────────────────────────────────────────

    def authenticate(self, username: str, password: str, ip_address: str = "") -> AuthUser | None:
        """Authenticate a user. Returns AuthUser or None."""
        now = time.time()
        username = username.strip().lower()

        # Brute force check
        if self._is_rate_limited(ip_address):
            _log.warning("[AUTH] Rate limited login attempt from %s for %s", ip_address, username)
            self._audit_log("login_rate_limited", username, ip_address, {"reason": "rate_limited"})
            return None

        # Account lockout check
        if self._is_account_locked(username):
            _log.warning("[AUTH] Locked account login attempt for %s from %s", username, ip_address)
            self._audit_log("login_locked", username, ip_address, {"reason": "account_locked"})
            return None

        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            if row is None:
                self._record_attempt(ip_address, False)
                self._audit_log("login_failed", username, ip_address, {"reason": "user_not_found"})
                return None

            if row["disabled"]:
                self._audit_log("login_disabled", username, ip_address, {"reason": "account_disabled"})
                return None

            if not verify_password(password, row["password_hash"]):
                self._record_attempt(ip_address, False)
                self._audit_log("login_failed", username, ip_address, {"reason": "wrong_password"})
                self._check_lockout(username)
                return None

            # Success
            self._record_attempt(ip_address, True)
            self._clear_lockout(username)
            conn.execute(
                "UPDATE users SET last_login_ts = ? WHERE user_id = ?",
                (now, row["user_id"]),
            )
            conn.commit()

            user = AuthUser(
                user_id=row["user_id"],
                username=row["username"],
                role=row["role"],
                display_name=row["display_name"] or row["username"],
                must_change_password=bool(row["must_change_password"]),
                disabled=bool(row["disabled"]),
                created_ts=row["created_ts"],
                last_login_ts=now,
            )
            self._audit_log("login_success", username, ip_address)
            return user
        finally:
            conn.close()

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "viewer",
        display_name: str = "",
        created_by: str = "",
    ) -> dict[str, Any]:
        """Create a new user. Returns result dict."""
        username = username.strip().lower()
        if not username or len(username) < 3:
            return {"success": False, "error": "Username must be at least 3 characters"}
        if role not in ("admin", "operator", "viewer"):
            return {"success": False, "error": f"Invalid role: {role}"}
        valid, msg = validate_password_strength(password)
        if not valid:
            return {"success": False, "error": msg}

        conn = self._get_conn()
        try:
            existing = conn.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone()
            if existing:
                return {"success": False, "error": "Username already exists"}
            pwd_hash = hash_password(password)
            user_id = uuid.uuid4().hex[:16]
            conn.execute(
                "INSERT INTO users (user_id, username, password_hash, role, display_name, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, pwd_hash, role, display_name or username, time.time()),
            )
            conn.commit()
            self._audit_log("user_created", username, "", {"created_by": created_by, "role": role})
            return {"success": True, "user_id": user_id, "username": username, "role": role}
        except sqlite3.IntegrityError:
            return {"success": False, "error": "Username already exists"}
        finally:
            conn.close()

    def update_password(self, username: str, current_password: str, new_password: str) -> dict[str, Any]:
        """Update user password. Validates current password first."""
        username = username.strip().lower()
        valid, msg = validate_password_strength(new_password)
        if not valid:
            return {"success": False, "error": msg}

        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            if row is None:
                return {"success": False, "error": "User not found"}
            if not verify_password(current_password, row["password_hash"]):
                return {"success": False, "error": "Current password is incorrect"}
            pwd_hash = hash_password(new_password)
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE username = ?",
                (pwd_hash, username),
            )
            conn.commit()
            self._audit_log("password_changed", username, "")
            return {"success": True}
        finally:
            conn.close()

    def admin_reset_password(self, username: str, new_password: str, admin_username: str) -> dict[str, Any]:
        """Admin-forced password reset."""
        username = username.strip().lower()
        valid, msg = validate_password_strength(new_password)
        if not valid:
            return {"success": False, "error": msg}

        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,))
            if cursor.fetchone() is None:
                return {"success": False, "error": "User not found"}
            pwd_hash = hash_password(new_password)
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE username = ?",
                (pwd_hash, username),
            )
            conn.commit()
            self._audit_log("password_admin_reset", username, "", {"admin": admin_username})
            return {"success": True}
        finally:
            conn.close()

    def get_user(self, username: str) -> AuthUser | None:
        """Get user by username."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip().lower(),))
            row = cursor.fetchone()
            if row is None:
                return None
            return AuthUser(
                user_id=row["user_id"],
                username=row["username"],
                role=row["role"],
                display_name=row["display_name"] or row["username"],
                must_change_password=bool(row["must_change_password"]),
                disabled=bool(row["disabled"]),
                created_ts=row["created_ts"],
                last_login_ts=row["last_login_ts"],
            )
        finally:
            conn.close()

    def get_user_by_id(self, user_id: str) -> AuthUser | None:
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return AuthUser(
                user_id=row["user_id"],
                username=row["username"],
                role=row["role"],
                display_name=row["display_name"] or row["username"],
                must_change_password=bool(row["must_change_password"]),
                disabled=bool(row["disabled"]),
                created_ts=row["created_ts"],
                last_login_ts=row["last_login_ts"],
            )
        finally:
            conn.close()

    def list_users(self) -> list[dict[str, Any]]:
        """List all users."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT user_id, username, role, display_name, must_change_password, disabled, created_ts, last_login_ts "
                "FROM users ORDER BY created_ts"
            )
            return [
                {
                    "user_id": r["user_id"],
                    "username": r["username"],
                    "role": r["role"],
                    "display_name": r["display_name"] or r["username"],
                    "must_change_password": bool(r["must_change_password"]),
                    "disabled": bool(r["disabled"]),
                    "created_ts": r["created_ts"],
                    "last_login_ts": r["last_login_ts"],
                }
                for r in cursor.fetchall()
            ]
        finally:
            conn.close()

    def update_user_role(self, username: str, new_role: str, admin_username: str) -> dict[str, Any]:
        """Update a user's role."""
        username = username.strip().lower()
        if new_role not in ("admin", "operator", "viewer"):
            return {"success": False, "error": f"Invalid role: {new_role}"}
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,))
            if cursor.fetchone() is None:
                return {"success": False, "error": "User not found"}
            conn.execute("UPDATE users SET role = ? WHERE username = ?", (new_role, username))
            conn.commit()
            self._audit_log("role_changed", username, "", {"new_role": new_role, "admin": admin_username})
            return {"success": True}
        finally:
            conn.close()

    def disable_user(self, username: str, admin_username: str) -> dict[str, Any]:
        """Disable a user account."""
        username = username.strip().lower()
        conn = self._get_conn()
        try:
            conn.execute("UPDATE users SET disabled = 1 WHERE username = ?", (username,))
            conn.commit()
            self._audit_log("user_disabled", username, "", {"admin": admin_username})
            return {"success": True}
        finally:
            conn.close()

    def enable_user(self, username: str, admin_username: str) -> dict[str, Any]:
        """Enable a disabled user account."""
        username = username.strip().lower()
        conn = self._get_conn()
        try:
            conn.execute("UPDATE users SET disabled = 0 WHERE username = ?", (username,))
            conn.commit()
            self._audit_log("user_enabled", username, "", {"admin": admin_username})
            return {"success": True}
        finally:
            conn.close()

    def delete_user(self, username: str, admin_username: str) -> dict[str, Any]:
        """Permanently delete a user."""
        username = username.strip().lower()
        if username == DEFAULT_ADMIN_USERNAME:
            return {"success": False, "error": "Cannot delete default admin user"}
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.commit()
            self._audit_log("user_deleted", username, "", {"admin": admin_username})
            return {"success": True}
        finally:
            conn.close()

    # ── Brute-force / Rate limiting ───────────────────────────────────────────

    def _is_rate_limited(self, ip_address: str) -> bool:
        if not ip_address or ip_address in ("127.0.0.1", "::1", "localhost"):
            return False
        now = time.time()
        with self._lock:
            attempts = self._login_attempts.get(ip_address, [])
            attempts = [t for t in attempts if now - t < BRUTE_FORCE_WINDOW_SECONDS]
            self._login_attempts[ip_address] = attempts
            return len(attempts) >= BRUTE_FORCE_MAX_ATTEMPTS

    def _record_attempt(self, ip_address: str, success: bool) -> None:
        if not ip_address:
            return
        now = time.time()
        with self._lock:
            if not success:
                attempts = self._login_attempts.get(ip_address, [])
                attempts.append(now)
                self._login_attempts[ip_address] = attempts

    def _check_lockout(self, username: str) -> None:
        """Check if user should be locked out based on recent failed attempts."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM audit_log "
                "WHERE event_type = 'login_failed' AND username = ? AND timestamp > ?",
                (username, time.time() - LOCKOUT_DURATION_SECONDS),
            )
            row = cursor.fetchone()
            if row and row["cnt"] >= MAX_LOGIN_ATTEMPTS:
                unlock_ts = time.time() + LOCKOUT_DURATION_SECONDS
                with self._lock:
                    self._account_lockouts[username] = unlock_ts
                # Persist lockout to DB (survives restart)
                conn.execute(
                    "INSERT OR REPLACE INTO account_lockouts (username, unlock_ts, created_ts) VALUES (?, ?, ?)",
                    (username, unlock_ts, time.time()),
                )
                conn.commit()
                _log.warning("[AUTH] Account %s locked until %s", username, unlock_ts)
                self._audit_log("account_locked", username, "", {"duration_seconds": LOCKOUT_DURATION_SECONDS})
        finally:
            conn.close()

    def _clear_lockout(self, username: str) -> None:
        with self._lock:
            self._account_lockouts.pop(username, None)
        try:
            conn = self._get_conn()
            conn.execute("DELETE FROM account_lockouts WHERE username = ?", (username,))
            conn.commit()
            conn.close()
        except (DatabaseError, sqlite3.Error, OSError):
            _log.debug("[AUTH] Failed to clear lockout")

    def _is_account_locked(self, username: str) -> bool:
        with self._lock:
            unlock_ts = self._account_lockouts.get(username)
            if unlock_ts is not None:
                if time.time() >= unlock_ts:
                    self._account_lockouts.pop(username, None)
                    return False
                return True
        # Check DB for persistent lockout (survives restart)
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT unlock_ts FROM account_lockouts WHERE username = ?", (username,)
            ).fetchone()
            conn.close()
            if row is not None:
                db_unlock = row["unlock_ts"]
                if time.time() >= db_unlock:
                    conn = self._get_conn()
                    conn.execute("DELETE FROM account_lockouts WHERE username = ?", (username,))
                    conn.commit()
                    conn.close()
                    return False
                # Restore to in-memory cache
                with self._lock:
                    self._account_lockouts[username] = db_unlock
                return True
        except (DatabaseError, sqlite3.Error, OSError):
            _log.debug("[AUTH] DB lockout check failed")
        return False

    # ── Audit logging ─────────────────────────────────────────────────────────

    def _audit_log(self, event_type: str, username: str, ip_address: str = "", details: dict | None = None) -> None:
        try:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO audit_log (timestamp, event_type, username, ip_address, details, success) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (time.time(), event_type, username, ip_address,
                     json.dumps(details or {}), 1 if "success" in event_type else 0),
                )
                conn.commit()
            finally:
                conn.close()
        except (OSError, ValueError, TypeError) as e:
            _log.warning("[AUTH] Audit log write failed: %s", e)

    def get_audit_log(self, limit: int = 100, event_type: str | None = None) -> list[dict[str, Any]]:
        """Get audit log entries."""
        conn = self._get_conn()
        try:
            if event_type:
                cursor = conn.execute(
                    "SELECT * FROM audit_log WHERE event_type = ? ORDER BY timestamp DESC LIMIT ?",
                    (event_type, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
                )
            return [
                {
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "event_type": r["event_type"],
                    "username": r["username"],
                    "ip_address": r["ip_address"],
                    "details": json.loads(r["details"]) if isinstance(r["details"], str) else {},
                    "success": bool(r["success"]),
                }
                for r in cursor.fetchall()
            ]
        finally:
            conn.close()

    # ── Password Reset Tokens (DB-backed) ────────────────────────────────────

    def _init_password_reset_table(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                expires_ts REAL NOT NULL,
                used INTEGER DEFAULT 0,
                created_ts REAL NOT NULL
            );
        """)

    def create_password_reset_token(self, username: str) -> str | None:
        """Create a password reset token (DB-backed). Returns None if user not found."""
        user = self.get_user(username)
        if user is None:
            return None
        token_str = generate_token()
        t_hash = hashlib.sha256(token_str.encode()).hexdigest()
        conn = self._get_conn()
        try:
            self._init_password_reset_table(conn)
            conn.execute(
                "INSERT INTO password_reset_tokens (token_hash, username, expires_ts, used, created_ts) "
                "VALUES (?, ?, ?, 0, ?)",
                (t_hash, username, time.time() + 3600, time.time()),
            )
            conn.commit()
            _log.info("[AUTH] Password reset token created for %s", username)
            return token_str
        except (DatabaseError, sqlite3.Error, OSError) as e:
            _log.exception("[AUTH] Failed to create password reset token")
            return None
        finally:
            conn.close()

    def verify_password_reset_token(self, token_str: str) -> str | None:
        """Verify a DB-backed password reset token. Returns username or None."""
        if not token_str:
            return None
        t_hash = hashlib.sha256(token_str.encode()).hexdigest()
        conn = self._get_conn()
        try:
            self._init_password_reset_table(conn)
            cursor = conn.execute(
                "SELECT username, expires_ts, used FROM password_reset_tokens WHERE token_hash = ?",
                (t_hash,),
            )
            row = cursor.fetchone()
            if row is None or row["used"] or time.time() >= row["expires_ts"]:
                if row is not None:
                    conn.execute("DELETE FROM password_reset_tokens WHERE token_hash = ?", (t_hash,))
                    conn.commit()
                return None
            conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE token_hash = ?", (t_hash,))
            conn.commit()
            return row["username"]
        except (DatabaseError, sqlite3.Error, OSError, ValueError) as e:
            _log.exception("[AUTH] Failed to verify password reset token")
            return None
        finally:
            conn.close()

    # ── Password Reset / Stats (stays in handler) ────────────────────────
