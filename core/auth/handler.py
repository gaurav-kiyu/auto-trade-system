"""
AD-KIYU Enterprise Auth Handler - password hashing, JWT tokens,
session management, brute-force protection, account lockout.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.db_utils import get_connection
from core.exceptions import DatabaseError

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

HASH_ALGO = "sha256"
PBKDF2_ITERATIONS = 600000
SALT_BYTES = 32
TOKEN_BYTES = 48
TOKEN_TTL_SECONDS = 3600  # 1 hour
REFRESH_TTL_SECONDS = 86400 * 7  # 7 days
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 900  # 15 minutes
BRUTE_FORCE_WINDOW_SECONDS = 60
BRUTE_FORCE_MAX_ATTEMPTS = 10
MAX_CONCURRENT_SESSIONS = 10
SESSION_COOKIE_NAME = "opb_session"
CSRF_COOKIE_NAME = "opb_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
MIN_PASSWORD_LENGTH = 8
DEFAULT_ADMIN_USERNAME = "admin"


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class AuthUser:
    user_id: str
    username: str
    role: str
    display_name: str = ""
    must_change_password: bool = False
    disabled: bool = False
    created_ts: float = field(default_factory=time.time)
    last_login_ts: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "display_name": self.display_name or self.username,
            "must_change_password": self.must_change_password,
            "disabled": self.disabled,
            "created_ts": self.created_ts,
            "last_login_ts": self.last_login_ts,
        }


@dataclass
class AuthToken:
    token: str
    user_id: str
    username: str
    role: str
    created_ts: float
    expires_ts: float
    csrf_token: str = ""

    def is_expired(self) -> bool:
        return time.time() >= self.expires_ts

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "created_ts": self.created_ts,
            "expires_ts": self.expires_ts,
            "csrf_token": self.csrf_token,
            "expires_in": max(0, int(self.expires_ts - time.time())),
        }


# ── Password utilities ─────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-SHA256 + random salt."""
    salt = os.urandom(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(HASH_ALGO, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a PBKDF2 hash."""
    try:
        iterations_str, salt_hex, dk_hex = hashed.split("$")
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected_dk = bytes.fromhex(dk_hex)
        dk = hashlib.pbkdf2_hmac(HASH_ALGO, password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk, expected_dk)
    except (ValueError, AttributeError):
        return False


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password strength. Returns (valid, message)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain an uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain a lowercase letter"
    if not re.search(r"\d", password):
        return False, "Password must contain a digit"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-]", password):
        return False, "Password must contain a special character"
    common = ["password", "admin", "123456", "qwerty", "letmein"]
    if any(word in password.lower() for word in common):
        return False, "Password contains a common word"
    return True, ""


def generate_token() -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_hex(TOKEN_BYTES)


def generate_csrf_token() -> str:
    """Generate a CSRF token."""
    return secrets.token_hex(32)


# ── Password Reset Token ───────────────────────────────────────────────────────

@dataclass
class PasswordResetToken:
    token: str
    username: str
    expires_ts: float
    used: bool = False


# ── AuthHandler ────────────────────────────────────────────────────────────────

class AuthHandler:
    """Thread-safe authentication handler with SQLite-backed user storage."""

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

    # ── MFA Management ──────────────────────────────────────────────────────

    def get_mfa_secret(self, username: str) -> str:
        """Get the MFA secret for a user. Returns empty string if not set."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT mfa_secret FROM users WHERE username = ?",
                (username.strip().lower(),),
            )
            row = cursor.fetchone()
            if row is None:
                return ""
            return row["mfa_secret"] or ""
        finally:
            conn.close()

    def set_mfa_secret(self, username: str, secret: str) -> bool:
        """Set (or reset) the MFA secret for a user. MFA remains disabled until verified."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE users SET mfa_secret = ?, mfa_enabled = 0 WHERE username = ?",
                (secret, username.strip().lower()),
            )
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def enable_mfa(self, username: str, recovery_codes: list[str]) -> bool:
        """Enable MFA for a user by setting mfa_enabled=1 and storing recovery codes.

        Args:
            username: The user to enable MFA for.
            recovery_codes: List of hashed recovery codes.

        Returns:
            True if successful.
        """
        import json
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE users SET mfa_enabled = 1, mfa_recovery_codes = ? WHERE username = ?",
                (json.dumps(recovery_codes), username.strip().lower()),
            )
            conn.commit()
            ok = conn.total_changes > 0
            if ok:
                _log.info("[AUTH] MFA enabled for %s", username)
                self._audit_log("mfa_enabled", username, "")
            return ok
        finally:
            conn.close()

    def disable_mfa(self, username: str) -> bool:
        """Disable MFA for a user by clearing the secret and recovery codes."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE users SET mfa_enabled = 0, mfa_secret = '', mfa_recovery_codes = '[]' "
                "WHERE username = ?",
                (username.strip().lower(),),
            )
            conn.commit()
            ok = conn.total_changes > 0
            if ok:
                _log.info("[AUTH] MFA disabled for %s", username)
                self._audit_log("mfa_disabled", username, "")
            return ok
        finally:
            conn.close()

    def is_mfa_enabled(self, username: str) -> bool:
        """Check if MFA is enabled for a user."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT mfa_enabled FROM users WHERE username = ?",
                (username.strip().lower(),),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            return bool(row["mfa_enabled"])
        finally:
            conn.close()

    def get_mfa_recovery_codes(self, username: str) -> list[str]:
        """Get the hashed recovery codes for a user."""
        import json
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT mfa_recovery_codes FROM users WHERE username = ?",
                (username.strip().lower(),),
            )
            row = cursor.fetchone()
            if row is None or not row["mfa_recovery_codes"]:
                return []
            try:
                return json.loads(row["mfa_recovery_codes"])
            except (json.JSONDecodeError, TypeError):
                return []
        finally:
            conn.close()

    def update_mfa_recovery_codes(self, username: str, recovery_codes: list[str]) -> bool:
        """Update (e.g., after consuming a recovery code) the stored recovery codes."""
        import json
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE users SET mfa_recovery_codes = ? WHERE username = ?",
                (json.dumps(recovery_codes), username.strip().lower()),
            )
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def use_recovery_code(self, username: str, code: str) -> bool:
        """Verify and consume a recovery code for a user.

        Args:
            username: The user's username.
            code: The raw recovery code to verify and consume.

        Returns:
            True if the recovery code was valid and consumed.
        """
        from core.auth.mfa import consume_recovery_code, hash_recovery_code, verify_recovery_code
        codes = self.get_mfa_recovery_codes(username)
        if not codes:
            return False
        if not verify_recovery_code(code, codes):
            return False
        updated = consume_recovery_code(code, codes)
        self.update_mfa_recovery_codes(username, updated)
        self._audit_log("mfa_recovery_code_used", username, "", {"remaining": len(updated)})
        return True

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

    # ── Session / Token management ────────────────────────────────────────────

    def create_session(self, user: AuthUser, ip_address: str = "", user_agent: str = "") -> AuthToken:
        """Create a new session token for a user."""
        token_str = generate_token()
        token_hash = hashlib.sha256(token_str.encode()).hexdigest()
        csrf_token = generate_csrf_token()
        now = time.time()

        token = AuthToken(
            token=token_str,
            user_id=user.user_id,
            username=user.username,
            role=user.role,
            created_ts=now,
            expires_ts=now + self._token_ttl,
            csrf_token=csrf_token,
        )

        with self._lock:
            # Enforce max concurrent sessions per user
            user_sessions = {k: v for k, v in self._tokens.items() if v.user_id == user.user_id}
            if len(user_sessions) >= MAX_CONCURRENT_SESSIONS:
                # Revoke the oldest session
                oldest_key = min(user_sessions, key=lambda k: user_sessions[k].created_ts)
                self._tokens.pop(oldest_key, None)
                self._purge_db_session(oldest_key)
            self._tokens[token_str] = token

        conn = self._get_conn()
        try:
            # Store only non-sensitive metadata (no raw token)
            token_meta = json.dumps({
                "user_id": user.user_id,
                "username": user.username,
                "role": user.role,
                "created_ts": now,
                "expires_ts": now + self._token_ttl,
                "csrf_token": csrf_token,
            })
            conn.execute(
                "INSERT INTO sessions (session_id, user_id, token_hash, created_ts, expires_ts, "
                "ip_address, user_agent, token_data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:16], user.user_id, token_hash, now, now + self._token_ttl,
                 ip_address, user_agent, token_meta),
            )
            conn.commit()
        finally:
            conn.close()

        return token

    def verify_session(self, token_str: str) -> AuthToken | None:
        """Verify a session token with DB-backed fallback persistence."""
        if not token_str:
            return None
        # Check in-memory cache first
        with self._lock:
            token = self._tokens.get(token_str)
            if token is not None:
                if token.is_expired():
                    self._tokens.pop(token_str, None)
                    self._purge_db_session(token_str)
                    return None
                return token

        # Fallback: recover from DB (survives server restarts)
        token_hash = hashlib.sha256(token_str.encode()).hexdigest()
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT token_data, expires_ts, revoked FROM sessions "
                "WHERE token_hash = ? AND revoked = 0 LIMIT 1",
                (token_hash,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            if row["revoked"]:
                return None
            if time.time() >= row["expires_ts"]:
                conn.execute("UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (token_hash,))
                conn.commit()
                return None
            # Recover token from stored data (token_str from request is the token)
            try:
                data = json.loads(row["token_data"]) if isinstance(row["token_data"], str) else {}
            except (json.JSONDecodeError, TypeError):
                data = {}
            recovered = AuthToken(
                token=token_str,
                user_id=data.get("user_id", ""),
                username=data.get("username", ""),
                role=data.get("role", ""),
                created_ts=data.get("created_ts", 0),
                expires_ts=data.get("expires_ts", 0),
                csrf_token=data.get("csrf_token", ""),
            )
            # Restore to in-memory cache
            with self._lock:
                self._tokens[token_str] = recovered
            return recovered
        finally:
            conn.close()

    def revoke_session(self, token_str: str) -> bool:
        """Revoke a specific session."""
        with self._lock:
            was = self._tokens.pop(token_str, None)
        self._purge_db_session(token_str)
        return was is not None

    def _purge_db_session(self, token_str: str) -> None:
        """Mark a session as revoked in the DB."""
        if not token_str:
            return
        token_hash = hashlib.sha256(token_str.encode()).hexdigest()
        conn = self._get_conn()
        try:
            conn.execute("UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (token_hash,))
            conn.commit()
        finally:
            conn.close()

    def revoke_all_user_sessions(self, username: str) -> int:
        """Revoke all sessions for a user."""
        user = self.get_user(username)
        if user is None:
            return 0
        count = 0
        with self._lock:
            to_remove = [k for k, v in self._tokens.items() if v.user_id == user.user_id]
            for k in to_remove:
                self._tokens.pop(k, None)
                count += 1
        conn = self._get_conn()
        try:
            conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user.user_id,))
            conn.commit()
        finally:
            conn.close()
        return count

    def get_user_sessions(self, user_id: str) -> list[dict[str, Any]]:
        """Get active sessions for a user."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT session_id, created_ts, expires_ts, ip_address, user_agent, revoked "
                "FROM sessions WHERE user_id = ? AND revoked = 0 AND expires_ts > ? "
                "ORDER BY created_ts DESC",
                (user_id, time.time()),
            )
            return [dict(r) for r in cursor.fetchall()]
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

    # ── Session refresh (extend TTL on activity) ─────────────────────────────

    def refresh_session(self, token_str: str) -> AuthToken | None:
        """Extend session TTL on verified activity. Returns refreshed token or None."""
        with self._lock:
            token = self._tokens.get(token_str)
            if token is None or token.is_expired():
                return None
            token.expires_ts = time.time() + self._token_ttl
            self._tokens[token_str] = token
        conn = self._get_conn()
        try:
            t_hash = hashlib.sha256(token_str.encode()).hexdigest()
            conn.execute(
                "UPDATE sessions SET expires_ts = ?, token_data = ? WHERE token_hash = ?",
                (token.expires_ts, json.dumps({
                    "user_id": token.user_id,
                    "username": token.username,
                    "role": token.role,
                    "created_ts": token.created_ts,
                    "expires_ts": token.expires_ts,
                    "csrf_token": token.csrf_token,
                }), t_hash),
            )
            conn.commit()
        except (DatabaseError, sqlite3.Error, OSError):
            _log.exception("[AUTH] Session refresh DB write failed")
        finally:
            conn.close()
        return token

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

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def purge_expired_sessions(self) -> int:
        """Remove expired sessions from memory and DB."""
        now = time.time()
        count = 0
        with self._lock:
            expired = [k for k, v in self._tokens.items() if v.is_expired()]
            for k in expired:
                self._tokens.pop(k, None)
                count += 1
        # Also purge from DB
        conn = self._get_conn()
        try:
            cursor = conn.execute("UPDATE sessions SET revoked = 1 WHERE expires_ts < ? AND revoked = 0", (now,))
            db_count = cursor.rowcount
            if db_count:
                _log.debug("[AUTH] Purged %d expired DB sessions", db_count)
                count += db_count
            conn.commit()
        finally:
            conn.close()
        if count:
            _log.debug("[AUTH] Purged %d total expired sessions", count)
        return count

    def get_stats(self) -> dict[str, Any]:
        """Get auth system statistics."""
        with self._lock:
            active_sessions = len(self._tokens)
            locked_accounts = len(self._account_lockouts)
        conn = self._get_conn()
        try:
            user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            failed_logins = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE event_type LIKE 'login_fail%' AND timestamp > ?",
                (time.time() - 86400,),
            ).fetchone()[0]
        except (DatabaseError, sqlite3.Error, OSError):
            user_count = 0
            failed_logins = 0
        finally:
            conn.close()
        return {
            "active_sessions": active_sessions,
            "total_users": user_count,
            "locked_accounts": locked_accounts,
            "failed_logins_24h": failed_logins,
            "token_ttl_seconds": self._token_ttl,
        }
