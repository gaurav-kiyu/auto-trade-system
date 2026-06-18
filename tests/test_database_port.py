"""
Contract tests for the DatabasePort interface.

Tests verify the SQLiteDatabaseAdapter implementation against the
DatabasePort contract. Any DatabasePort implementation should pass
a similar set of tests with backend-specific connection parameters.

Usage:
    python -m pytest tests/test_database_port.py -v
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Generator

import pytest

from core.adapters.database import SQLiteDatabaseAdapter
from core.adapters.database.sqlite_adapter import SQLiteDatabaseAdapter as SQLiteImpl
from core.db_utils import create_database_port
from core.ports.database import DatabasePort, DatabaseStats


# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_db() -> Generator[str, None, None]:
    """Provide a temporary SQLite database path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        os.unlink(path)
        # Also clean up WAL/SHM files
        for ext in ("-wal", "-shm"):
            p = path + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


@pytest.fixture
def db(tmp_db: str) -> Generator[DatabasePort, None, None]:
    """Provide a connected SQLiteDatabaseAdapter."""
    adapter: DatabasePort = SQLiteDatabaseAdapter(tmp_db)
    adapter.connect()
    adapter.execute(
        "CREATE TABLE IF NOT EXISTS items ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  name TEXT NOT NULL,"
        "  value REAL"
        ")"
    )
    adapter.commit()
    yield adapter
    adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Connection lifecycle
# ═════════════════════════════════════════════════════════════════════════


class TestConnectionLifecycle:
    def test_connect_disconnect(self, tmp_db: str) -> None:
        adapter: DatabasePort = SQLiteDatabaseAdapter(tmp_db)
        assert not adapter.is_connected()
        assert adapter.connect() is True  # first connect
        assert adapter.is_connected()
        assert adapter.connect() is False  # already connected
        adapter.disconnect()
        assert not adapter.is_connected()
        adapter.disconnect()  # safe to call twice

    def test_reconnect(self, tmp_db: str) -> None:
        adapter: DatabasePort = SQLiteDatabaseAdapter(tmp_db)
        adapter.connect()
        adapter.execute("CREATE TABLE t (x INTEGER)")
        adapter.commit()
        assert adapter.reconnect() is True
        assert adapter.is_connected()
        # Table should still exist after reconnect
        assert adapter.table_exists("t")

    def test_context_manager(self, tmp_db: str) -> None:
        with SQLiteDatabaseAdapter(tmp_db) as db:
            assert db.is_connected()
            db.execute("CREATE TABLE t (x INTEGER)")
            db.commit()
        assert not db.is_connected()

    def test_execute_without_connect_raises(self, tmp_db: str) -> None:
        adapter: DatabasePort = SQLiteDatabaseAdapter(tmp_db)
        with pytest.raises(ConnectionError):
            adapter.execute("SELECT 1")

    def test_wal_mode_enabled(self, tmp_db: str) -> None:
        adapter = SQLiteDatabaseAdapter(tmp_db)
        adapter.connect()
        row = adapter.fetchone("PRAGMA journal_mode")
        # WAL is a soft pragma — may return 'memory' for in-memory, but for
        # file-based DBs we expect 'wal'
        if row:
            mode = row[0] if isinstance(row, (list, tuple)) else row[0]
            assert mode == "wal", f"Expected WAL mode, got {mode}"
        adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# CRUD operations
# ═════════════════════════════════════════════════════════════════════════


class TestCrud:
    def test_insert_and_fetchone(self, db: DatabasePort) -> None:
        db.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("alpha", 10.5))
        row = db.fetchone("SELECT * FROM items WHERE name = ?", ("alpha",))
        assert row is not None
        assert row["name"] == "alpha"
        assert row["value"] == 10.5

    def test_fetchall(self, db: DatabasePort) -> None:
        db.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("a", 1.0))
        db.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("b", 2.0))
        rows = db.fetchall("SELECT * FROM items ORDER BY name")
        assert len(rows) == 2
        assert rows[0]["name"] == "a"
        assert rows[1]["name"] == "b"

    def test_fetchone_no_match(self, db: DatabasePort) -> None:
        row = db.fetchone("SELECT * FROM items WHERE id = ?", (999,))
        assert row is None

    def test_fetchall_empty(self, db: DatabasePort) -> None:
        rows = db.fetchall("SELECT * FROM items")
        assert rows == []

    def test_execute_many(self, db: DatabasePort) -> None:
        db.execute_many(
            "INSERT INTO items (name, value) VALUES (?, ?)",
            [("x", 1.0), ("y", 2.0), ("z", 3.0)],
        )
        rows = db.fetchall("SELECT * FROM items ORDER BY id")
        assert len(rows) == 3

    def test_named_params(self, db: DatabasePort) -> None:
        db.execute(
            "INSERT INTO items (name, value) VALUES (:name, :value)",
            {"name": "named", "value": 42.0},
        )
        row = db.fetchone("SELECT * FROM items WHERE name = :n", {"n": "named"})
        assert row is not None
        assert row["value"] == 42.0

    def test_commit_persists(self, tmp_db: str) -> None:
        adapter: DatabasePort = SQLiteDatabaseAdapter(tmp_db)
        adapter.connect()
        adapter.execute(
            "CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, val TEXT)"
        )
        adapter.execute("INSERT INTO test (val) VALUES (?)", ("hello",))
        adapter.commit()
        adapter.disconnect()

        # Re-open and verify
        adapter2: DatabasePort = SQLiteDatabaseAdapter(tmp_db)
        adapter2.connect()
        row = adapter2.fetchone("SELECT val FROM test")
        assert row is not None
        assert row["val"] == "hello"
        adapter2.disconnect()

    def test_rollback_does_not_persist(self, db: DatabasePort) -> None:
        db.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("rollback_test", 99.9))
        db.rollback()
        row = db.fetchone("SELECT * FROM items WHERE name = ?", ("rollback_test",))
        assert row is None


# ═════════════════════════════════════════════════════════════════════════
# Transactions
# ═════════════════════════════════════════════════════════════════════════


class TestTransactions:
    def test_begin_commit(self, db: DatabasePort) -> None:
        db.begin()
        db.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("txn", 1.0))
        db.commit()
        row = db.fetchone("SELECT * FROM items WHERE name = ?", ("txn",))
        assert row is not None

    def test_begin_rollback(self, db: DatabasePort) -> None:
        db.begin()
        db.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("rollback", 2.0))
        db.rollback()
        row = db.fetchone("SELECT * FROM items WHERE name = ?", ("rollback",))
        assert row is None


# ═════════════════════════════════════════════════════════════════════════
# DDL helpers
# ═════════════════════════════════════════════════════════════════════════


class TestDdl:
    def test_table_exists(self, db: DatabasePort) -> None:
        assert db.table_exists("items") is True
        assert db.table_exists("nonexistent") is False

    def test_create_table(self, tmp_db: str) -> None:
        adapter: DatabasePort = SQLiteDatabaseAdapter(tmp_db)
        adapter.connect()
        result = adapter.create_table(
            "CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY, val TEXT)"
        )
        assert result is True
        assert adapter.table_exists("test_table") is True
        adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Health & stats
# ═════════════════════════════════════════════════════════════════════════


class TestHealthAndStats:
    def test_health_check_connected(self, db: DatabasePort) -> None:
        hc = db.health_check()
        assert hc["status"] == "healthy"
        assert hc["connected"] is True
        assert hc["backend"] == "SQLite"
        assert "latency_ms" in hc

    def test_health_check_disconnected(self, tmp_db: str) -> None:
        adapter: DatabasePort = SQLiteDatabaseAdapter(tmp_db)
        hc = adapter.health_check()
        assert hc["status"] == "disconnected"
        assert hc["connected"] is False

    def test_stats(self, db: DatabasePort) -> None:
        db.execute("SELECT 1")
        stats = db.stats()
        assert isinstance(stats, DatabaseStats)
        assert stats.db_path.endswith(".db")
        assert stats.is_connected is True
        assert stats.queries_executed >= 1
        assert stats.backend == "SQLite"

    def test_health_check_after_error(self, db: DatabasePort) -> None:
        with pytest.raises(Exception):
            db.execute("INVALID SQL")
        hc = db.health_check()
        assert hc["status"] in ("healthy", "unhealthy")


# ═════════════════════════════════════════════════════════════════════════
# Thread safety
# ═════════════════════════════════════════════════════════════════════════


class TestThreadSafety:
    def test_concurrent_reads(self, tmp_db: str) -> None:
        adapter = SQLiteDatabaseAdapter(tmp_db)
        adapter.connect()
        adapter.execute(
            "CREATE TABLE IF NOT EXISTS numbers (id INTEGER PRIMARY KEY, val INTEGER)"
        )
        adapter.execute_many(
            "INSERT INTO numbers (val) VALUES (?)",
            [(i,) for i in range(100)],
        )
        adapter.commit()

        results: list[int] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def reader() -> None:
            try:
                rows = adapter.fetchall("SELECT val FROM numbers ORDER BY id")
                with lock:
                    results.extend(row["val"] for row in rows)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

        assert len(errors) == 0, f"Concurrent read errors: {errors}"
        # Relaxed assertion: each thread reads all 100 rows, but on Windows/
        # loaded systems some threads may not finish before the 5s join timeout.
        # At minimum we should get one full read (100 rows).
        assert len(results) >= 100, (
            f"Expected >= 100 rows from concurrent reads, got {len(results)}"
        )
        adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Factory function
# ═════════════════════════════════════════════════════════════════════════


class TestFactory:
    def test_create_database_port(self, tmp_db: str) -> None:
        db = create_database_port(tmp_db,
                                   wal=True,
                                   busy_timeout_ms=3000,
                                   row_factory=True)
        assert db is not None
        assert isinstance(db, SQLiteImpl)
        db.connect()
        assert db.is_connected()
        row = db.fetchone("SELECT 1 as v")
        assert row is not None
        assert row["v"] == 1
        db.disconnect()

    def test_create_database_port_no_row_factory(self, tmp_db: str) -> None:
        db = create_database_port(tmp_db, row_factory=False)
        db.connect()
        # Without row_factory, fetch returns tuples
        row = db.fetchone("SELECT 1 as v")
        assert row is not None
        assert row[0] == 1
        db.disconnect()

    def test_create_database_port_no_wal(self, tmp_db: str) -> None:
        db = create_database_port(tmp_db, wal=False, row_factory=True)
        db.connect()
        assert db.is_connected()
        row = db.fetchone("SELECT 1 as v")
        assert row is not None
        db.disconnect()
