"""
Session Manager Mixin — extracted from AuthHandler for SRP compliance.

Provides session token management methods that are mixed into the AuthHandler class.
Handles session creation, verification, revocation, refresh, and cleanup.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import uuid
from typing import Any

from core.auth.handler.constants import MAX_CONCURRENT_SESSIONS
from core.auth.handler.models import AuthToken, AuthUser
from core.auth.handler.password import generate_csrf_token, generate_token
from core.exceptions import DatabaseError

_log = logging.getLogger(__name__)


class SessionManagerMixin:
    """Mixin providing session/token management for AuthHandler.

    Expects the host class to provide:
      - self._get_conn() -> sqlite3.Connection
      - self._lock (threading.RLock)
      - self._tokens (dict[str, AuthToken])
      - self._token_ttl (int)
      - self._lockout_strategy (optional, for get_stats)
      - self._account_lockouts (dict[str, float])
    """

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
            cursor = conn.execute(
                "UPDATE sessions SET revoked = 1 WHERE expires_ts < ? AND revoked = 0", (now,)
            )
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


__all__ = [
    "SessionManagerMixin",
]
