"""
AD-KIYU RBAC - Session Store.

Thread-safe session tracking with TTL expiry for operator sessions.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.auth.permissions import Role

_log = logging.getLogger(__name__)


@dataclass
class Session:
    session_id: str
    identity: str
    role: Role
    created_ts: float = field(default_factory=time.time)
    last_active_ts: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class SessionStore:
    """Thread-safe in-memory session store with TTL expiry."""

    def __init__(self, ttl_seconds: int = 3600):
        self._lock = threading.RLock()
        self._ttl = ttl_seconds
        self._sessions: dict[str, Session] = {}

    def create(self, identity: str, role: Role | str, **metadata) -> Session:
        """Create a new session for the given identity."""
        if isinstance(role, str):
            role = Role(role.lower())
        session = Session(
            session_id=uuid.uuid4().hex[:16],
            identity=identity,
            role=role,
            metadata=metadata,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        _log.info(f"[AUTH] Session created for {identity!r}: {session.session_id}")
        return session

    def get(self, session_id: str) -> Session | None:
        """Get a session by ID. Returns None if expired or not found."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if time.time() - session.last_active_ts > self._ttl:
                self._sessions.pop(session_id, None)
                return None
            session.last_active_ts = time.time()
            return session

    def touch(self, session_id: str) -> bool:
        """Update last_active_ts for a session. Returns False if not found."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.last_active_ts = time.time()
            return True

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if existed."""
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def purge_expired(self) -> int:
        """Remove all expired sessions. Returns count of purged."""
        now = time.time()
        purged = 0
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if now - s.last_active_ts > self._ttl]
            for sid in expired:
                self._sessions.pop(sid, None)
                purged += 1
        if purged:
            _log.info(f"[AUTH] Purged {purged} expired sessions")
        return purged

    def active_count(self) -> int:
        """Return number of non-expired sessions."""
        self.purge_expired()
        with self._lock:
            return len(self._sessions)

    def list_active(self) -> list[Session]:
        """List all active (non-expired) sessions."""
        self.purge_expired()
        with self._lock:
            return list(self._sessions.values())
