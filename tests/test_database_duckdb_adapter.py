"""
Contract tests for the DuckDBDatabaseAdapter.

Tests mirror the SQLiteDatabaseAdapter contract tests, adapted for DuckDB's
syntax (no AUTOINCREMENT, uses RETURNING, etc.).

DuckDB is embedded so these tests always run (no external server needed).

Usage:
    python -m pytest tests/test_database_duckdb_adapter.py -v
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from typing import Any

import pytest
from core.adapters.database import DuckDBDatabaseAdapter
from core.adapters.database.duckdb_adapter import _parse_duckdb_dsn
from core.ports.database import DatabasePort, DatabaseStats

# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


@pytest.fixture
def db() -> Generator[DatabasePort, None, None]:
    """Provide a connected in-memory DuckDB adapter with a clean test table."""
    adapter: DatabasePort = DuckDBDatabaseAdapter(":memory:")
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
        adapter: DatabasePort = DuckDBDatabaseAdapter()
        assert not adapter.is_connected()
        assert adapter.connect() is True
        assert adapter.is_connected()
        assert adapter.connect() is False
        adapter.disconnect()
        assert not adapter.is_connected()
        adapter.disconnect()

    def test_context_manager(self) -> None:
        with DuckDBDatabaseAdapter(":memory:") as d:
            assert d.is_connected()
            d.execute("SELECT 1")
        assert not d.is_connected()

    def test_execute_without_connect_raises(self) -> None:
        adapter: DatabasePort = DuckDBDatabaseAdapter()
        with pytest.raises(ConnectionError):
            adapter.execute("SELECT 1")

    def test_file_based_db(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "test.duckdb")
        adapter: DatabasePort = DuckDBDatabaseAdapter(db_path)
        adapter.connect()
        assert adapter.is_connected()
        row = adapter.fetchone("SELECT 1 AS x")
        assert row is not None
        adapter.disconnect()
        # Clean up
        import os
        if os.path.exists(db_path):
            os.remove(db_path)

    def test_reconnect(self) -> None:
        adapter: DatabasePort = DuckDBDatabaseAdapter(":memory:")
        adapter.connect()
        adapter.disconnect()
        assert adapter.reconnect() is True
        assert adapter.is_connected()
        adapter.disconnect()


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
        adapter: DatabasePort = DuckDBDatabaseAdapter(":memory:")
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
        adapter: DatabasePort = DuckDBDatabaseAdapter(":memory:")
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
        assert hc["backend"] == "DuckDB"
        assert "latency_ms" in hc

    def test_health_check_disconnected(self) -> None:
        adapter: DatabasePort = DuckDBDatabaseAdapter(":memory:")
        hc = adapter.health_check()
        assert hc["status"] == "disconnected"
        assert hc["connected"] is False

    def test_stats(self, db: DatabasePort) -> None:
        db.execute("SELECT 1")
        stats = db.stats()
        assert isinstance(stats, DatabaseStats)
        assert stats.is_connected is True
        assert stats.queries_executed >= 1
        assert stats.backend == "DuckDB"

    def test_stats_disconnected(self) -> None:
        adapter: DatabasePort = DuckDBDatabaseAdapter(":memory:")
        stats = adapter.stats()
        assert isinstance(stats, DatabaseStats)
        assert stats.is_connected is False


# ═════════════════════════════════════════════════════════════════════════
# DSN parsing
# ═════════════════════════════════════════════════════════════════════════


class TestDsnParsing:
    """Unit tests for DuckDB DSN parsing (no connection needed)."""

    def test_memory(self) -> None:
        path, config = _parse_duckdb_dsn(":memory:")
        assert path == ":memory:"
        assert config == {}

    def test_file_path(self) -> None:
        path, config = _parse_duckdb_dsn("/data/analytics.duckdb")
        assert path == "/data/analytics.duckdb"
        assert config == {}

    def test_with_config(self) -> None:
        path, config = _parse_duckdb_dsn("metrics.duckdb?read_only=true&threads=4")
        assert path == "metrics.duckdb"
        assert config == {"read_only": True, "threads": "4"}

    def test_plain_name(self) -> None:
        path, config = _parse_duckdb_dsn("my_db")
        assert path == "my_db"
        assert config == {}


# ═════════════════════════════════════════════════════════════════════════
# Parquet integration (DuckDB standout feature)
# ═════════════════════════════════════════════════════════════════════════


class TestParquetIntegration:
    """Tests for DuckDB's native Parquet file querying capability."""

    def test_query_parquet_file(self, tmp_path: Any) -> None:
        """Write data to Parquet via DuckDB and read it back with SQL."""
        parquet_path = str(tmp_path / "test_data.parquet")

        with DuckDBDatabaseAdapter(":memory:") as db:
            # Create some data and export to Parquet
            db.execute("CREATE TABLE src (id INTEGER, symbol TEXT, score DOUBLE)")
            db.execute("INSERT INTO src VALUES (?, ?, ?)", (1, "NIFTY", 8.5))
            db.execute("INSERT INTO src VALUES (?, ?, ?)", (2, "BANKNIFTY", 7.2))
            db.execute("INSERT INTO src VALUES (?, ?, ?)", (3, "FINNIFTY", 6.8))
            db.execute(f"COPY src TO '{parquet_path}' (FORMAT PARQUET)")

        # Read Parquet file with a fresh in-memory DuckDB
        with DuckDBDatabaseAdapter(":memory:") as db:
            rows = db.fetchall(f"SELECT * FROM '{parquet_path}' ORDER BY id")
            assert len(rows) == 3
            assert rows[0][1] == "NIFTY"
            assert rows[1][2] == 7.2
            assert rows[2][0] == 3

    def test_parquet_filter_pushdown(self, tmp_path: Any) -> None:
        """Parquet query with WHERE filter uses DuckDB's filter pushdown."""
        parquet_path = str(tmp_path / "filter_test.parquet")

        with DuckDBDatabaseAdapter(":memory:") as db:
            db.execute("CREATE TABLE src (id INTEGER, sector TEXT, value DOUBLE)")
            db.execute("INSERT INTO src VALUES (?, ?, ?)", (1, "IT", 95.5))
            db.execute("INSERT INTO src VALUES (?, ?, ?)", (2, "BANKING", 88.0))
            db.execute("INSERT INTO src VALUES (?, ?, ?)", (3, "IT", 78.3))
            db.execute(f"COPY src TO '{parquet_path}' (FORMAT PARQUET)")

        with DuckDBDatabaseAdapter(":memory:") as db:
            rows = db.fetchall(
                f"SELECT id, value FROM '{parquet_path}' WHERE sector = ? ORDER BY id",
                ("IT",),
            )
            assert len(rows) == 2
            assert rows[0][1] == 95.5

    def test_parquet_aggregation(self, tmp_path: Any) -> None:
        """Run an aggregation query directly on a Parquet file."""
        parquet_path = str(tmp_path / "agg_test.parquet")

        with DuckDBDatabaseAdapter(":memory:") as db:
            db.execute("CREATE TABLE src (symbol TEXT, volume INTEGER, price DOUBLE)")
            db.execute("INSERT INTO src VALUES (?, ?, ?)", ("NIFTY", 1000, 23500))
            db.execute("INSERT INTO src VALUES (?, ?, ?)", ("BANKNIFTY", 800, 48500))
            db.execute("INSERT INTO src VALUES (?, ?, ?)", ("NIFTY", 1200, 23510))
            db.execute(f"COPY src TO '{parquet_path}' (FORMAT PARQUET)")

        with DuckDBDatabaseAdapter(":memory:") as db:
            row = db.fetchone(
                f"SELECT symbol, SUM(volume) as total_vol FROM '{parquet_path}' "
                "WHERE symbol = ? GROUP BY symbol",
                ("NIFTY",),
            )
            assert row is not None
            assert row[0] == "NIFTY"
            assert row[1] == 2200  # 1000 + 1200

    def test_parquet_join_with_duckdb_table(self, tmp_path: Any) -> None:
        """Join a Parquet file with a DuckDB table."""
        parquet_path = str(tmp_path / "join_scores.parquet")

        with DuckDBDatabaseAdapter(":memory:") as db:
            # Create Parquet data
            db.execute("CREATE TABLE scores (symbol TEXT, score DOUBLE)")
            db.execute("INSERT INTO scores VALUES (?, ?)", ("NIFTY", 8.5))
            db.execute("INSERT INTO scores VALUES (?, ?)", ("BANKNIFTY", 7.2))
            db.execute(f"COPY scores TO '{parquet_path}' (FORMAT PARQUET)")

            # Create lookup table in DuckDB
            db.execute("CREATE TABLE categories (symbol TEXT, sector TEXT)")
            db.execute("INSERT INTO categories VALUES (?, ?)", ("NIFTY", "BROAD"))
            db.execute("INSERT INTO categories VALUES (?, ?)", ("BANKNIFTY", "FINANCIAL"))

            # Join Parquet with DuckDB table
            rows = db.fetchall(
                f"SELECT p.symbol, p.score, c.sector "
                f"FROM '{parquet_path}' p "
                f"JOIN categories c ON p.symbol = c.symbol "
                f"ORDER BY p.score DESC"
            )
            assert len(rows) == 2
            assert rows[0][0] == "NIFTY"
            assert rows[0][2] == "BROAD"
            assert rows[1][0] == "BANKNIFTY"
            assert rows[1][2] == "FINANCIAL"
