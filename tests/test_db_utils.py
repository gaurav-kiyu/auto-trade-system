"""Tests for core/db_utils.py - shared SQLite connection utilities and AsyncDbWriter.

Covers:
- get_connection (WAL mode, busy_timeout, row_factory)
- _enable_wal, _set_busy_timeout (best-effort)
- get_connection_cached (caching, cache miss, cache invalidation)
- AsyncDbWriter init, submit, execute_sync, stop, stats
- WriteOperation dataclass
- create_database_port factory
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any
from unittest.mock import MagicMock


from core.db_utils import (
    AsyncDbWriter,
    WriteOperation,
    _enable_wal,
    _set_busy_timeout,
    create_database_port,
    get_connection,
    get_connection_cached,
)


# =============================================================================
# WriteOperation Tests
# =============================================================================

class TestWriteOperation:
    def test_creation_defaults(self):
        op = WriteOperation(sql="INSERT INTO test VALUES (?)", params=("val",))
        assert op.sql == "INSERT INTO test VALUES (?)"
        assert op.params == ("val",)
        assert op.callback is None
        assert op.submitted_at > 0

    def test_creation_with_callback(self):
        cb = lambda s, m: None
        op = WriteOperation(sql="UPDATE test SET x=1", callback=cb)
        assert op.callback is cb


# =============================================================================
# get_connection Tests
# =============================================================================

class TestGetConnection:
    def test_creates_connection(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        conn = get_connection(db_path)
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_row_factory_set(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        conn = get_connection(db_path, row_factory=True)
        assert conn.row_factory is sqlite3.Row
        conn.close()

    def test_no_row_factory(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        conn = get_connection(db_path, row_factory=False)
        assert conn.row_factory is None
        conn.close()

    def test_wal_mode(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        conn = get_connection(db_path, wal=True)
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0].upper()
        assert "WAL" in mode
        conn.close()

    def test_busy_timeout(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        conn = get_connection(db_path, busy_timeout_ms=3000)
        cursor = conn.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        assert timeout == 3000
        conn.close()

    def test_default_busy_timeout(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        conn = get_connection(db_path)
        cursor = conn.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        assert timeout == 5000
        conn.close()

    def test_check_same_thread_false(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        conn = get_connection(db_path, check_same_thread=False)
        # Should not raise when used from another thread
        assert conn is not None
        conn.close()

    def test_writes_and_reads(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO test VALUES (?, ?)", (1, "test"))
        row = conn.execute("SELECT * FROM test WHERE id = ?", (1,)).fetchone()
        assert row["name"] == "test"
        conn.close()


class TestEnableWal:
    def test_enables_wal(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(str(db_path))
        _enable_wal(conn)
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0].upper()
        assert "WAL" in mode
        conn.close()

    def test_handles_error_gracefully(self):
        """_enable_wal should log warning instead of raising."""
        conn = MagicMock(spec=sqlite3.Connection)
        conn.execute.side_effect = sqlite3.Error("Cannot enable WAL")
        _enable_wal(conn)  # Should not raise
        conn.execute.assert_called_once()


class TestSetBusyTimeout:
    def test_sets_timeout(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(str(db_path))
        _set_busy_timeout(conn, 5000)
        cursor = conn.execute("PRAGMA busy_timeout")
        assert cursor.fetchone()[0] == 5000
        conn.close()

    def test_handles_error_gracefully(self):
        conn = MagicMock(spec=sqlite3.Connection)
        conn.execute.side_effect = sqlite3.Error("Cannot set busy timeout")
        _set_busy_timeout(conn, 5000)  # Should not raise


# =============================================================================
# get_connection_cached Tests
# =============================================================================

class TestGetConnectionCached:
    def test_returns_cached_connection(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        cache: dict = {}
        conn1 = get_connection_cached(db_path, cache)
        conn2 = get_connection_cached(db_path, cache)
        assert conn1 is conn2  # Same object returned
        conn1.close()

    def test_different_paths_different_connections(self, tmp_path: Any):
        cache: dict = {}
        conn1 = get_connection_cached(str(tmp_path / "db1.db"), cache)
        conn2 = get_connection_cached(str(tmp_path / "db2.db"), cache)
        assert conn1 is not conn2
        conn1.close()
        conn2.close()

    def test_custom_key(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        cache: dict = {}
        conn = get_connection_cached(db_path, cache, key="my_key")
        assert cache["my_key"] is conn
        conn.close()

    def test_replaces_deleted_cache_entry(self, tmp_path: Any):
        db_path = str(tmp_path / "test.db")
        cache: dict[str, Any] = {str(db_path): None}
        conn = get_connection_cached(db_path, cache)
        assert conn is not None
        conn.close()


# =============================================================================
# AsyncDbWriter Tests
# =============================================================================

class TestAsyncDbWriter:
    def test_init_creates_writer(self, tmp_path: Any):
        db_path = str(tmp_path / "async.db")
        writer = AsyncDbWriter(db_path)
        assert writer.stats["is_running"] is True
        writer.stop(block=True, timeout=2)

    def test_submit_and_verify(self, tmp_path: Any):
        db_path = str(tmp_path / "async.db")
        init_sql = "CREATE TABLE IF NOT EXISTS test (id INTEGER, val TEXT)"
        writer = AsyncDbWriter(db_path, init_sql=init_sql)
        writer.submit("INSERT INTO test VALUES (?, ?)", (1, "hello"))
        time.sleep(0.5)  # Allow async write to complete
        rows = writer.execute_sync("SELECT * FROM test")
        assert len(rows) == 1
        assert rows[0]["val"] == "hello"
        writer.stop(block=True, timeout=2)

    def test_multiple_submits(self, tmp_path: Any):
        db_path = str(tmp_path / "async.db")
        init_sql = "CREATE TABLE IF NOT EXISTS test (id INTEGER, val TEXT)"
        writer = AsyncDbWriter(db_path, init_sql=init_sql)
        for i in range(5):
            writer.submit("INSERT INTO test VALUES (?, ?)", (i, f"val-{i}"))
        time.sleep(0.5)
        rows = writer.execute_sync("SELECT COUNT(*) AS cnt FROM test")
        assert rows[0]["cnt"] == 5
        writer.stop(block=True, timeout=2)

    def test_writer_stats(self, tmp_path: Any):
        db_path = str(tmp_path / "async.db")
        writer = AsyncDbWriter(db_path)
        stats = writer.stats
        assert stats["db_path"] == db_path
        assert stats["is_running"] is True
        assert stats["written"] >= 0
        writer.stop(block=True, timeout=2)

    def test_submit_after_stop_returns_false(self, tmp_path: Any):
        db_path = str(tmp_path / "async.db")
        writer = AsyncDbWriter(db_path)
        writer.stop(block=True, timeout=2)
        result = writer.submit("INSERT INTO test VALUES (1)", ())
        assert result is False

    def test_callback_invoked_on_success(self, tmp_path: Any):
        db_path = str(tmp_path / "async.db")
        init_sql = "CREATE TABLE IF NOT EXISTS test (id INTEGER)"
        writer = AsyncDbWriter(db_path, init_sql=init_sql)
        callback = MagicMock()
        writer.submit("INSERT INTO test VALUES (1)", (), callback=callback)
        time.sleep(0.5)
        callback.assert_called_once_with(True, "")
        writer.stop(block=True, timeout=2)

    def test_callback_invoked_on_error(self, tmp_path: Any):
        db_path = str(tmp_path / "async.db")
        writer = AsyncDbWriter(db_path)
        callback = MagicMock()
        writer.submit("INSERT INTO nonexistent VALUES (1)", (), callback=callback)
        time.sleep(0.5)
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] is False
        writer.stop(block=True, timeout=2)


class TestAsyncDbWriterInit:
    def test_custom_max_queue_size(self, tmp_path: Any):
        writer = AsyncDbWriter(str(tmp_path / "q.db"), max_queue_size=10)
        assert writer._max_queue_size == 10
        writer.stop()

    def test_no_wal(self, tmp_path: Any):
        db_path = str(tmp_path / "nowal.db")
        writer = AsyncDbWriter(db_path, wal=False)
        assert writer._wal is False
        writer.stop()


# =============================================================================
# create_database_port Tests
# =============================================================================

class TestCreateDatabasePort:
    def test_creates_sqlite_adapter(self, tmp_path: Any):
        db_path = str(tmp_path / "port.db")
        port = create_database_port(db_path)
        assert port is not None
        assert hasattr(port, "connect")
        assert hasattr(port, "execute")
        assert hasattr(port, "disconnect")

    def test_created_port_works(self, tmp_path: Any):
        db_path = str(tmp_path / "port.db")
        port = create_database_port(db_path)
        port.connect()
        port.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER)")
        port.execute("INSERT INTO test VALUES (1)")
        row = port.fetchone("SELECT * FROM test")
        assert row is not None
        port.disconnect()
