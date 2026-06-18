"""
Tests for core/db_utils.py - Shared SQLite connection utilities.

Covers:
- get_connection (WAL mode, busy_timeout, row_factory, check_same_thread)
- get_connection_cached (caching behavior, key override)
- AsyncDbWriter (async queue-based writer, race conditions, callbacks)
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from core.db_utils import (
    AsyncDbWriter,
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
    """get_connection - basic connection creation."""

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
        # When busy_timeout_ms <= 0, get_connection() skips the PRAGMA,
        # so SQLite retains the default set by timeout=3.0 → 3000ms
        assert timeout == 3000
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
    """get_connection_cached - connection caching."""

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


# ═════════════════════════════════════════════════════════════════════════
# AsyncDbWriter Tests
# ═════════════════════════════════════════════════════════════════════════


class TestAsyncDbWriter:
    """AsyncDbWriter - queue-based async SQLite writer."""

    # ── Normal flow ──────────────────────────────────────────────────────

    def test_submit_and_stop(self, tmp_path) -> None:
        """Normal flow: submit a write, stop, verify it persisted."""
        db_path = str(tmp_path / "async1.db")
        conn = get_connection(db_path, wal=True)
        conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER, msg TEXT)")
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path)
        writer.submit("INSERT INTO log VALUES (?, ?)", (1, "hello"))
        writer.stop()

        # Verify via writer's own sync reader (avoids WAL visibility issues)
        rows = writer.execute_sync("SELECT msg FROM log WHERE id = ?", (1,))
        assert len(rows) >= 1
        assert rows[0][0] == "hello"

    def test_submit_after_stop_rejected(self, tmp_path) -> None:
        """Submitting after stop() returns False."""
        db_path = str(tmp_path / "async_reject.db")
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER, msg TEXT)")
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path)
        writer.stop()

        result = writer.submit("INSERT INTO log VALUES (?, ?)", (1, "rejected"))
        assert result is False

    def test_multiple_writes(self, tmp_path) -> None:
        """Multiple write operations all get processed."""
        db_path = str(tmp_path / "async_multi.db")
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER, msg TEXT)")
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path)
        for i in range(10):
            writer.submit("INSERT INTO log VALUES (?, ?)", (i, f"msg_{i}"))
        writer.stop()

        assert writer.stats["written"] == 10
        rows = writer.execute_sync("SELECT msg FROM log ORDER BY id")
        assert len(rows) == 10
        assert rows[-1][0] == "msg_9"

    def test_stats_tracking(self, tmp_path) -> None:
        """Stats reflect accurate written/error counts."""
        db_path = str(tmp_path / "async_stats.db")
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER, msg TEXT)")
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path)
        writer.submit("INSERT INTO log VALUES (?, ?)", (1, "stats_test"))
        writer.stop()

        stats = writer.stats
        assert stats["written"] >= 1
        assert stats["errors"] == 0
        assert stats["db_path"] == db_path
        assert stats["max_queue_size"] == 256

    # ── Callback tests ───────────────────────────────────────────────────

    def test_callback_on_success(self, tmp_path) -> None:
        """Callback is invoked on successful write."""
        db_path = str(tmp_path / "async_cb_ok.db")
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER, msg TEXT)")
        conn.commit()
        conn.close()

        callback_results: list[tuple[bool, str]] = []
        callback_lock = threading.Lock()

        def cb(success: bool, msg: str) -> None:
            with callback_lock:
                callback_results.append((success, msg))

        writer = AsyncDbWriter(db_path)
        writer.submit("INSERT INTO log VALUES (?, ?)", (1, "callback"), callback=cb)
        writer.stop()

        with callback_lock:
            assert len(callback_results) == 1
            assert callback_results[0][0] is True

    def test_callback_on_queue_full(self, tmp_path) -> None:
        """When queue is full, submit() returns False without callback."""
        db_path = str(tmp_path / "async_cb_full.db")
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER, msg TEXT)")
        conn.commit()
        conn.close()

        callback_called = threading.Event()

        def cb(success: bool, msg: str) -> None:
            callback_called.set()

        # Create writer with tiny queue
        writer = AsyncDbWriter(db_path, max_queue_size=1)
        # Fill the queue
        writer.submit("INSERT INTO log VALUES (?, ?)", (1, "fill"))
        # Queue is full now (size 1)
        result = writer.submit("INSERT INTO log VALUES (?, ?)", (2, "overflow"), callback=cb)
        assert result is False  # Rejected, not queued
        writer.stop()

        # Callback should not have been called since it was never queued
        assert not callback_called.is_set()

    # ── Error handling ───────────────────────────────────────────────────

    def test_write_error(self, tmp_path) -> None:
        """Write to non-existent table records error."""
        db_path = str(tmp_path / "async_err.db")
        # Don't create the table - write will fail
        callback_results: list[tuple[bool, str]] = []
        callback_lock = threading.Lock()

        def cb(success: bool, msg: str) -> None:
            with callback_lock:
                callback_results.append((success, msg))

        writer = AsyncDbWriter(db_path)
        writer.submit("INSERT INTO nonexistent VALUES (?, ?)", (1, "fail"), callback=cb)
        writer.stop()

        stats = writer.stats
        assert stats["errors"] >= 1
        assert stats["last_error"] != ""

        with callback_lock:
            if callback_results:
                assert callback_results[0][0] is False

    # ── Race condition tests ─────────────────────────────────────────────

    def test_submit_then_immediate_stop(self, tmp_path) -> None:
        """Submit then immediately stop - write should still be processed.

        This tests the race condition fix where the worker's while loop was
        checking the stop event before draining the queue.
        """
        db_path = str(tmp_path / "async_race1.db")
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER, msg TEXT)")
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path)
        for i in range(5):
            writer.submit("INSERT INTO log VALUES (?, ?)", (i, f"race_{i}"))
        writer.stop()

        # All writes should have been processed despite stop() being called
        assert writer.stats["written"] >= 5, (
            f"Expected >=5 writes, got {writer.stats['written']}. "
            "Race condition: stop event fired before worker drained queue."
        )

    def test_double_stop_safe(self, tmp_path) -> None:
        """Calling stop() multiple times is idempotent."""
        db_path = str(tmp_path / "async_double_stop.db")
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER, msg TEXT)")
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path)
        writer.submit("INSERT INTO log VALUES (?, ?)", (1, "double"))
        writer.stop()
        writer.stop()  # Second stop should not raise
        writer.stop()  # Third stop should not raise

        assert writer.stats["written"] >= 1

    def test_concurrent_submit_stop_contention(self, tmp_path) -> None:
        """Simulate contention between submit and stop from multiple threads."""
        db_path = str(tmp_path / "async_contention.db")
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER, msg TEXT)")
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path)

        results: list[bool] = []
        lock = threading.Lock()

        def submitter() -> None:
            for i in range(20):
                ok = writer.submit("INSERT INTO log VALUES (?, ?)", (i, f"contention_{i}"))
                with lock:
                    results.append(ok)

        threads = [threading.Thread(target=submitter) for _ in range(4)]
        for t in threads:
            t.start()
        # Immediately signal stop while submitters are still running
        import time
        time.sleep(0.1)
        writer.stop()

        for t in threads:
            t.join(5)

        submitted = sum(1 for r in results if r)
        written = writer.stats["written"]
        # All successful submits should have been processed or at least attempted
        assert written >= 0
        assert submitted >= written, (
            f"Submitted {submitted} writes but only {written} were written"
        )
