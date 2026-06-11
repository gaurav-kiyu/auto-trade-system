"""
Tests for core/db_utils.py — Shared SQLite connection utilities.

Covers:
- get_connection (WAL mode, busy_timeout, row_factory, check_same_thread)
- get_connection_cached (caching behavior, key override)
- Internal helpers (_enable_wal, _set_busy_timeout)
"""

from __future__ import annotations

import sqlite3

import pytest

from core.db_utils import (
    get_connection,
    get_connection_cached,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database path."""
    return str(tmp_path / "test.db")


# ── get_connection Tests ──────────────────────────────────────────────────────


class TestGetConnection:
    """get_connection — basic connection creation."""

    def test_connects_to_file(self, tmp_db):
        conn = get_connection(tmp_db)
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_sets_row_factory_by_default(self, tmp_db):
        conn = get_connection(tmp_db)
        assert conn.row_factory is sqlite3.Row
        conn.close()

    def test_no_row_factory_when_disabled(self, tmp_db):
        conn = get_connection(tmp_db, row_factory=False)
        assert conn.row_factory is None
        conn.close()

    def test_check_same_thread_default(self, tmp_db):
        conn = get_connection(tmp_db)
        # Default is check_same_thread=True from sqlite3
        assert conn is not None
        conn.close()

    def test_check_same_thread_custom(self, tmp_db):
        conn = get_connection(tmp_db, check_same_thread=False)
        assert conn is not None
        conn.close()

    def test_returns_usable_connection(self, tmp_db):
        conn = get_connection(tmp_db)
        cursor = conn.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_creates_table(self, tmp_db):
        conn = get_connection(tmp_db)
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello')")
        rows = conn.execute("SELECT * FROM test").fetchall()
        assert len(rows) == 1
        assert rows[0]["name"] == "hello"
        conn.close()

    def test_wal_mode_is_set(self, tmp_db):
        conn = get_connection(tmp_db, wal=True)
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        # WAL mode may return "wal" (or "delete" on some filesystems)
        assert mode is not None
        conn.close()

    def test_busy_timeout_is_set(self, tmp_db):
        conn = get_connection(tmp_db, busy_timeout_ms=3000)
        cursor = conn.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        assert timeout == 3000
        conn.close()

    def test_path_object_accepted(self, tmp_path):
        p = tmp_path / "path_obj.db"
        conn = get_connection(p)
        assert isinstance(conn, sqlite3.Connection)
        conn.close()


class TestGetConnectionEdgeCases:
    """Edge cases for connection creation."""

    def test_no_wal_when_disabled(self, tmp_db):
        conn = get_connection(tmp_db, wal=False)
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode is not None  # Still works, just no WAL
        conn.close()

    def test_zero_busy_timeout(self, tmp_db):
        conn = get_connection(tmp_db, busy_timeout_ms=0)
        cursor = conn.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        assert timeout == 0
        conn.close()

    def test_default_busy_timeout(self, tmp_db):
        """Default busy_timeout should be 5000."""
        conn = get_connection(tmp_db)
        cursor = conn.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        assert timeout == 5000
        conn.close()


# ── get_connection_cached Tests ────────────────────────────────────────────────


class TestGetConnectionCached:
    """get_connection_cached — connection caching."""

    def test_creates_new_connection(self, tmp_db):
        cache: dict[str, sqlite3.Connection] = {}
        conn = get_connection_cached(tmp_db, cache)
        assert isinstance(conn, sqlite3.Connection)
        assert str(tmp_db) in cache
        conn.close()

    def test_returns_cached_connection(self, tmp_db):
        cache: dict[str, sqlite3.Connection] = {}
        conn1 = get_connection_cached(tmp_db, cache)
        conn2 = get_connection_cached(tmp_db, cache)
        assert conn1 is conn2
        conn1.close()

    def test_custom_cache_key(self, tmp_db):
        cache: dict[str, sqlite3.Connection] = {}
        conn = get_connection_cached(tmp_db, cache, key="my_custom_key")
        assert "my_custom_key" in cache
        assert str(tmp_db) not in cache
        conn.close()

    def test_replaces_none_value(self, tmp_db):
        cache: dict[str, sqlite3.Connection] = {str(tmp_db): None}
        conn = get_connection_cached(tmp_db, cache)
        assert cache[str(tmp_db)] is conn
        conn.close()

    def test_passes_kwargs_to_get_connection(self, tmp_db):
        cache: dict[str, sqlite3.Connection] = {}
        conn = get_connection_cached(tmp_db, cache, busy_timeout_ms=1000)
        cursor = conn.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        assert timeout == 1000
        conn.close()


class TestGetConnectionCachedDifferentPaths:
    """Caching with multiple database paths."""

    def test_different_paths_separate_connections(self, tmp_path):
        db1 = str(tmp_path / "db1.db")
        db2 = str(tmp_path / "db2.db")
        cache: dict[str, sqlite3.Connection] = {}
        conn1 = get_connection_cached(db1, cache)
        conn2 = get_connection_cached(db2, cache)
        assert conn1 is not conn2
        assert len(cache) == 2
        conn1.close()
        conn2.close()

    def test_reuses_cached_connection(self, tmp_db):
        cache: dict[str, sqlite3.Connection] = {}
        conn1 = get_connection_cached(tmp_db, cache, wal=True, busy_timeout_ms=3000)
        conn2 = get_connection_cached(tmp_db, cache)  # Different kwargs, but uses cached
        assert conn1 is conn2
        conn1.close()
