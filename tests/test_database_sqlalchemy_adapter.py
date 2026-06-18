"""
Contract tests for the SQLAlchemyDatabaseAdapter.

Tests use SQLite in-memory database (always available, no external deps)
to validate the full DatabasePort contract through the SQLAlchemy layer.

Usage:
    python -m pytest tests/test_database_sqlalchemy_adapter.py -v
"""

from __future__ import annotations

import threading
from typing import Any, Generator

import pytest

from core.adapters.database import SQLAlchemyDatabaseAdapter
from core.ports.database import DatabasePort, DatabaseStats

_IN_MEMORY_URL = "sqlite:///:memory:"


# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


@pytest.fixture
def db() -> Generator[DatabasePort, None, None]:
    """Provide a connected SQLAlchemy in-memory adapter with a clean table."""
    adapter: DatabasePort = SQLAlchemyDatabaseAdapter(_IN_MEMORY_URL)
    adapter.connect()
    adapter.execute(
        "CREATE TABLE IF NOT EXISTS test_items ("
        "id INTEGER, name TEXT, val DOUBLE"
        ")"
    )
    yield adapter
    adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Connection lifecycle
# ═════════════════════════════════════════════════════════════════════════


class TestConnectionLifecycle:
    def test_connect_disconnect(self) -> None:
        adapter: DatabasePort = SQLAlchemyDatabaseAdapter(_IN_MEMORY_URL)
        assert not adapter.is_connected()
        assert adapter.connect() is True
        assert adapter.is_connected()
        assert adapter.connect() is False
        adapter.disconnect()
        assert not adapter.is_connected()
        adapter.disconnect()

    def test_context_manager(self) -> None:
        with SQLAlchemyDatabaseAdapter(_IN_MEMORY_URL) as d:
            assert d.is_connected()
            d.execute("SELECT 1")
        assert not d.is_connected()

    def test_execute_without_connect_raises(self) -> None:
        adapter: DatabasePort = SQLAlchemyDatabaseAdapter(_IN_MEMORY_URL)
        with pytest.raises(ConnectionError):
            adapter.execute("SELECT 1")

    def test_reconnect(self) -> None:
        adapter: DatabasePort = SQLAlchemyDatabaseAdapter(_IN_MEMORY_URL)
        adapter.connect()
        adapter.disconnect()
        assert adapter.reconnect() is True
        assert adapter.is_connected()
        adapter.disconnect()

    def test_invalid_url_raises(self) -> None:
        adapter: DatabasePort = SQLAlchemyDatabaseAdapter("not-a-url")
        with pytest.raises(ConnectionError):
            adapter.connect()


# ═════════════════════════════════════════════════════════════════════════
# CRUD operations
# ═════════════════════════════════════════════════════════════════════════


class TestCrud:
    def test_insert_and_fetchone(self, db: DatabasePort) -> None:
        db.execute("INSERT INTO test_items VALUES (?, ?, ?)", (1, "alpha", 10.5))
        row = db.fetchone("SELECT * FROM test_items WHERE id = ?", (1,))
        assert row is not None
        assert row[1] == "alpha"
        assert row[2] == 10.5

    def test_fetchone_no_match(self, db: DatabasePort) -> None:
        row = db.fetchone("SELECT * FROM test_items WHERE id = ?", (999,))
        assert row is None

    def test_fetchall(self, db: DatabasePort) -> None:
        db.execute("INSERT INTO test_items VALUES (?, ?, ?)", (1, "a", 1.0))
        db.execute("INSERT INTO test_items VALUES (?, ?, ?)", (2, "b", 2.0))
        rows = db.fetchall("SELECT * FROM test_items ORDER BY id")
        assert len(rows) == 2
        names = {r[1] for r in rows}
        assert "a" in names
        assert "b" in names

    def test_fetchall_empty(self, db: DatabasePort) -> None:
        rows = db.fetchall("SELECT * FROM test_items")
        assert rows == []

    def test_execute_many(self, db: DatabasePort) -> None:
        count = db.execute_many(
            "INSERT INTO test_items VALUES (?, ?, ?)",
            [(1, "x", 1.0), (2, "y", 2.0), (3, "z", 3.0)],
        )
        assert count == 3
        rows = db.fetchall("SELECT * FROM test_items ORDER BY id")
        assert len(rows) == 3

    def test_update(self, db: DatabasePort) -> None:
        db.execute("INSERT INTO test_items VALUES (?, ?, ?)", (1, "updatable", 1.0))
        db.execute("UPDATE test_items SET val = ? WHERE name = ?", (99.0, "updatable"))
        row = db.fetchone("SELECT val FROM test_items WHERE name = ?", ("updatable",))
        assert row is not None
        assert row[0] == 99.0

    def test_delete(self, db: DatabasePort) -> None:
        db.execute("INSERT INTO test_items VALUES (?, ?, ?)", (1, "deletable", 1.0))
        db.execute("DELETE FROM test_items WHERE name = ?", ("deletable",))
        row = db.fetchone("SELECT * FROM test_items WHERE name = ?", ("deletable",))
        assert row is None


# ═════════════════════════════════════════════════════════════════════════
# Transactions
# ═════════════════════════════════════════════════════════════════════════


class TestTransactions:
    def test_commit(self, db: DatabasePort) -> None:
        db.begin()
        db.execute("INSERT INTO test_items VALUES (?, ?, ?)", (1, "txn", 1.0))
        db.commit()
        row = db.fetchone("SELECT name FROM test_items WHERE id = ?", (1,))
        assert row is not None

    def test_rollback(self, db: DatabasePort) -> None:
        db.begin()
        db.execute("INSERT INTO test_items VALUES (?, ?, ?)", (2, "rollback_me", 2.0))
        db.rollback()
        row = db.fetchone("SELECT name FROM test_items WHERE id = ?", (2,))
        assert row is None


# ═════════════════════════════════════════════════════════════════════════
# DDL helpers
# ═════════════════════════════════════════════════════════════════════════


class TestDdl:
    def test_table_exists_true(self, db: DatabasePort) -> None:
        assert db.table_exists("test_items") is True

    def test_table_exists_false(self, db: DatabasePort) -> None:
        assert db.table_exists("nonexistent_table_xyz") is False

    def test_create_table(self) -> None:
        adapter: DatabasePort = SQLAlchemyDatabaseAdapter(_IN_MEMORY_URL)
        adapter.connect()
        result = adapter.create_table(
            "CREATE TABLE IF NOT EXISTS new_table (id INTEGER, name TEXT)"
        )
        assert result is True
        assert adapter.table_exists("new_table") is True
        adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Thread safety
# ═════════════════════════════════════════════════════════════════════════


class TestThreadSafety:
    def test_concurrent_reads(self) -> None:
        adapter: DatabasePort = SQLAlchemyDatabaseAdapter(_IN_MEMORY_URL)
        adapter.connect()
        adapter.execute("CREATE TABLE IF NOT EXISTS thr_items (id INTEGER, val TEXT)")
        for i in range(100):
            adapter.execute("INSERT INTO thr_items VALUES (?, ?)", (i, f"v_{i}"))

        results: list[Any] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def reader() -> None:
            try:
                rows = adapter.fetchall("SELECT * FROM thr_items ORDER BY id")
                with lock:
                    results.extend(rows)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

        assert len(errors) == 0, f"Concurrent read errors: {errors}"
        assert len(results) >= 100, f"Expected >=100 rows, got {len(results)}"
        adapter.execute("DROP TABLE IF EXISTS thr_items")
        adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Health & stats
# ═════════════════════════════════════════════════════════════════════════


class TestHealthAndStats:
    def test_health_check_connected(self, db: DatabasePort) -> None:
        hc = db.health_check()
        assert hc["status"] == "healthy"
        assert hc["connected"] is True
        assert "SQLAlchemy" in hc["backend"]
        assert "latency_ms" in hc

    def test_health_check_disconnected(self) -> None:
        adapter: DatabasePort = SQLAlchemyDatabaseAdapter(_IN_MEMORY_URL)
        hc = adapter.health_check()
        assert hc["status"] == "disconnected"
        assert hc["connected"] is False

    def test_stats(self, db: DatabasePort) -> None:
        db.execute("SELECT 1")
        stats = db.stats()
        assert isinstance(stats, DatabaseStats)
        assert stats.is_connected is True
        assert stats.queries_executed >= 1
        assert "SQLAlchemy" in stats.backend

    def test_stats_disconnected(self) -> None:
        adapter: DatabasePort = SQLAlchemyDatabaseAdapter(_IN_MEMORY_URL)
        stats = adapter.stats()
        assert isinstance(stats, DatabaseStats)
        assert stats.is_connected is False


# ═════════════════════════════════════════════════════════════════════════
# Dialect-specific behavior
# ═════════════════════════════════════════════════════════════════════════


class TestDialectBehavior:
    """Tests that verify SQLAlchemy correctly handles dialect differences."""

    def test_parameter_style_positional(self, db: DatabasePort) -> None:
        """SQLite (via SQLAlchemy) uses ? for positional params."""
        db.execute("INSERT INTO test_items VALUES (?, ?, ?)", (1, "test", 1.0))
        row = db.fetchone("SELECT name, val FROM test_items WHERE id = ?", (1,))
        assert row is not None
        assert row[0] == "test"

    def test_named_parameters(self, db: DatabasePort) -> None:
        """SQLAlchemy supports :param style named parameters."""
        db.execute(
            "INSERT INTO test_items VALUES (:id, :name, :val)",
            {"id": 10, "name": "named", "val": 99.5},
        )
        row = db.fetchone("SELECT name FROM test_items WHERE id = ?", (10,))
        assert row is not None
        assert row[0] == "named"
