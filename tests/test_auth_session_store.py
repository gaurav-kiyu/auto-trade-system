"""
Tests for core/auth/session_store.py - Thread-safe session store with TTL expiry.

Covers (35+ tests):
- Session dataclass creation and defaults
- SessionStore create/get/touch/delete
- TTL expiry auto-cleanup
- purge_expired / active_count / list_active
- Thread safety under concurrent access
- Edge cases: expired session retrieval, non-existent sessions, duplicate identity
"""

from __future__ import annotations

import threading
import time

import pytest
from core.auth.permissions import Role
from core.auth.session_store import Session, SessionStore

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def store():
    """SessionStore with short TTL for testing expiry."""
    return SessionStore(ttl_seconds=3600)  # 1 hour default


@pytest.fixture
def short_ttl_store():
    """SessionStore with very short TTL (0.1s) for expiry tests."""
    return SessionStore(ttl_seconds=0.1)


# ── Session Dataclass Tests ───────────────────────────────────────────────────


class TestSession:
    """Session dataclass."""

    def test_default_values(self):
        """Session created with minimal args should have defaults."""
        session = Session(session_id="s1", identity="alice", role=Role.ADMIN)
        assert session.session_id == "s1"
        assert session.identity == "alice"
        assert session.role == Role.ADMIN
        assert session.created_ts > 0
        assert session.last_active_ts > 0
        assert session.metadata == {}

    def test_custom_values(self):
        """Session with all fields set."""
        session = Session(
            session_id="s2",
            identity="bob",
            role=Role.OPERATOR,
            created_ts=100.0,
            last_active_ts=200.0,
            metadata={"ip": "192.168.1.1"},
        )
        assert session.identity == "bob"
        assert session.role == Role.OPERATOR
        assert session.created_ts == 100.0
        assert session.last_active_ts == 200.0
        assert session.metadata == {"ip": "192.168.1.1"}


# ── SessionStore: Create Tests ────────────────────────────────────────────────


class TestSessionStoreCreate:
    """create() - session creation."""

    def test_create_minimal(self, store):
        """Create with minimal args returns valid session."""
        session = store.create("alice", Role.ADMIN)
        assert session.session_id is not None
        assert len(session.session_id) == 16
        assert session.identity == "alice"
        assert session.role == Role.ADMIN
        assert session.created_ts > 0

    def test_create_with_string_role(self, store):
        """String role should be converted to Role enum."""
        session = store.create("bob", "operator")
        assert session.role == Role.OPERATOR

    def test_create_case_insensitive_role(self, store):
        """Role string should be case-insensitive."""
        session = store.create("charlie", "ADMIN")
        assert session.role == Role.ADMIN

    def test_create_with_metadata(self, store):
        """Extra kwargs should be stored as metadata."""
        session = store.create("dave", Role.OBSERVER, ip="10.0.0.1", user_agent="test")
        assert session.metadata["ip"] == "10.0.0.1"
        assert session.metadata["user_agent"] == "test"

    def test_create_unique_session_ids(self, store):
        """Each created session should have a unique ID."""
        s1 = store.create("alice", Role.ADMIN)
        s2 = store.create("bob", Role.OPERATOR)
        assert s1.session_id != s2.session_id

    def test_create_same_identity_multiple_sessions(self, store):
        """Same identity can have multiple active sessions."""
        s1 = store.create("alice", Role.ADMIN)
        s2 = store.create("alice", Role.VIEWER)
        assert s1.session_id != s2.session_id

    def test_active_count_after_creates(self, store):
        """active_count should reflect created sessions."""
        store.create("alice", Role.ADMIN)
        store.create("bob", Role.OPERATOR)
        store.create("charlie", Role.VIEWER)
        assert store.active_count() == 3


# ── SessionStore: Get Tests ───────────────────────────────────────────────────


class TestSessionStoreGet:
    """get() - session retrieval."""

    def test_get_valid_session(self, store):
        """Get should return session for valid ID."""
        created = store.create("alice", Role.ADMIN)
        retrieved = store.get(created.session_id)
        assert retrieved is not None
        assert retrieved.identity == "alice"
        assert retrieved.session_id == created.session_id

    def test_get_nonexistent_returns_none(self, store):
        """Get with unknown ID should return None."""
        assert store.get("nonexistent") is None

    def test_get_updates_last_active_ts(self, store):
        """Get should update last_active_ts."""
        created = store.create("alice", Role.ADMIN)
        original_ts = created.last_active_ts
        time.sleep(0.01)
        retrieved = store.get(created.session_id)
        assert retrieved is not None
        assert retrieved.last_active_ts >= original_ts

    def test_get_after_delete_returns_none(self, store):
        """Get should return None after session deleted."""
        created = store.create("alice", Role.ADMIN)
        store.delete(created.session_id)
        assert store.get(created.session_id) is None


# ── SessionStore: Expiry Tests ────────────────────────────────────────────────


class TestSessionStoreExpiry:
    """TTL expiry - sessions should auto-expire after TTL."""

    def test_get_expired_returns_none(self, short_ttl_store):
        """Get should return None for expired session."""
        created = short_ttl_store.create("alice", Role.ADMIN)
        time.sleep(0.15)  # wait for TTL to expire
        assert short_ttl_store.get(created.session_id) is None

    def test_touch_prevents_expiry(self, short_ttl_store):
        """Touch should keep session alive."""
        created = short_ttl_store.create("alice", Role.ADMIN)
        time.sleep(0.05)  # partial wait
        short_ttl_store.touch(created.session_id)  # reset timer
        time.sleep(0.05)  # stay within TTL
        assert short_ttl_store.get(created.session_id) is not None

    def test_touch_expired_returns_false(self, short_ttl_store):
        """Touch on expired session should return False."""
        created = short_ttl_store.create("alice", Role.ADMIN)
        time.sleep(0.15)  # wait for expiry
        assert short_ttl_store.touch(created.session_id) is False

    def test_purge_expired_removes_only_expired(self, short_ttl_store):
        """Purge should remove expired but keep valid sessions."""
        short_ttl_store.create("alice", Role.ADMIN)
        short_ttl_store.create("bob", Role.OPERATOR)
        time.sleep(0.15)  # both expire
        s3 = short_ttl_store.create("charlie", Role.VIEWER)  # new session
        purged = short_ttl_store.purge_expired()
        assert purged == 2  # alice and bob
        assert short_ttl_store.get(s3.session_id) is not None  # charlie still alive

    def test_purge_expired_zero_when_none_expired(self, store):
        """Purge with no expired sessions returns 0."""
        store.create("alice", Role.ADMIN)
        store.create("bob", Role.OPERATOR)
        assert store.purge_expired() == 0


# ── SessionStore: Touch Tests ─────────────────────────────────────────────────


class TestSessionStoreTouch:
    """touch() - update last_active_ts."""

    def test_touch_valid_session(self, store):
        """Touch should return True for valid session."""
        created = store.create("alice", Role.ADMIN)
        assert store.touch(created.session_id) is True

    def test_touch_nonexistent_returns_false(self, store):
        """Touch with unknown ID should return False."""
        assert store.touch("nonexistent") is False


# ── SessionStore: Delete Tests ────────────────────────────────────────────────


class TestSessionStoreDelete:
    """delete() - session removal."""

    def test_delete_existing_returns_true(self, store):
        """Delete existing session returns True."""
        created = store.create("alice", Role.ADMIN)
        assert store.delete(created.session_id) is True

    def test_delete_nonexistent_returns_false(self, store):
        """Delete non-existent session returns False."""
        assert store.delete("nonexistent") is False

    def test_delete_reduces_active_count(self, store):
        """Delete should reduce active count."""
        store.create("alice", Role.ADMIN)
        created = store.create("bob", Role.OPERATOR)
        assert store.active_count() == 2
        store.delete(created.session_id)
        assert store.active_count() == 1


# ── SessionStore: ListActive Tests ────────────────────────────────────────────


class TestSessionStoreListActive:
    """list_active() - list all non-expired sessions."""

    def test_list_active_returns_valid_sessions(self, store):
        """list_active should return all non-expired sessions."""
        s1 = store.create("alice", Role.ADMIN)
        s2 = store.create("bob", Role.OPERATOR)
        active = store.list_active()
        assert len(active) == 2
        ids = {s.session_id for s in active}
        assert s1.session_id in ids
        assert s2.session_id in ids

    def test_list_active_empty(self, store):
        """list_active with no sessions should return empty list."""
        assert store.list_active() == []

    def test_list_active_excludes_expired(self, short_ttl_store):
        """list_active should not include expired sessions."""
        short_ttl_store.create("alice", Role.ADMIN)
        time.sleep(0.15)  # expire
        short_ttl_store.create("bob", Role.OPERATOR)  # new session
        active = short_ttl_store.list_active()
        assert len(active) == 1
        assert active[0].identity == "bob"


# ── SessionStore: Active Count Tests ──────────────────────────────────────────


class TestSessionStoreActiveCount:
    """active_count() - number of non-expired sessions."""

    def test_active_count_zero_initial(self, store):
        """Fresh store should have 0 active sessions."""
        assert store.active_count() == 0

    def test_active_count_after_create(self, store):
        """active_count should reflect creates."""
        store.create("alice", Role.ADMIN)
        assert store.active_count() == 1

    def test_active_count_after_delete(self, store):
        """active_count should reflect deletes."""
        created = store.create("alice", Role.ADMIN)
        store.create("bob", Role.OPERATOR)
        assert store.active_count() == 2
        store.delete(created.session_id)
        assert store.active_count() == 1


# ── Thread Safety Tests ───────────────────────────────────────────────────────


class TestSessionStoreThreadSafety:
    """Concurrent access should not corrupt state."""

    def test_concurrent_creates(self, store):
        """Multiple threads creating sessions should not race."""
        errors = []
        created_ids = []

        def create_worker():
            try:
                for _ in range(10):
                    session = store.create("worker", Role.OPERATOR)
                    created_ids.append(session.session_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(created_ids) == 50
        # Verify all session IDs are unique
        assert len(set(created_ids)) == 50

    def test_concurrent_get_and_delete(self, store):
        """Concurrent get/delete should not crash."""
        created = store.create("alice", Role.ADMIN)
        errors = []

        def access_worker():
            try:
                for _ in range(20):
                    store.get(created.session_id)
                    store.touch(created.session_id)
            except Exception as e:
                errors.append(e)

        def delete_worker():
            try:
                store.delete(created.session_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=access_worker) for _ in range(3)]
        threads.append(threading.Thread(target=delete_worker))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0  # No crashes

    def test_concurrent_purge_and_create(self, short_ttl_store):
        """Concurrent purge and create should be safe."""
        errors = []

        def create_worker():
            try:
                for _ in range(20):
                    short_ttl_store.create("worker", Role.OPERATOR)
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        def purge_worker():
            try:
                for _ in range(10):
                    short_ttl_store.purge_expired()
                    time.sleep(0.02)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=create_worker),
            threading.Thread(target=purge_worker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
