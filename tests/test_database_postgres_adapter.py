"""
Contract tests for the PostgreSQLDatabaseAdapter.

Tests mirror the SQLiteDatabaseAdapter contract tests in test_database_port.py
but configured for PostgreSQL. They are conditionally skipped if psycopg2 is
not installed or no PostgreSQL instance is available.

Usage:
    # Requires psycopg2-binary and a running PostgreSQL instance
    python -m pytest tests/test_database_postgres_adapter.py -v

    # Skip PostgreSQL-dependent tests:
    python -m pytest tests/test_database_postgres_adapter.py -v -k "not postgres"
"""

from __future__ import annotations

import os
import threading
from collections.abc import Generator

import pytest
from core.adapters.database import PostgreSQLDatabaseAdapter
from core.ports.database import DatabasePort, DatabaseStats

# ── Skip condition ─────────────────────────────────────────────────────────

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")

# Check if a PostgreSQL instance is available (via env vars or default)
PG_HOST = os.environ.get("PG_TEST_HOST", "")
PG_PORT = int(os.environ.get("PG_TEST_PORT", "5432"))
PG_USER = os.environ.get("PG_TEST_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_TEST_PASSWORD", "postgres")
PG_DBNAME = os.environ.get("PG_TEST_DBNAME", "postgres")

PG_AVAILABLE = bool(
    os.environ.get("PG_TEST_HOST")
    or os.environ.get("PG_TEST_AVAILABLE")
)

needs_pg = pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="No PostgreSQL instance available. Set PG_TEST_HOST to enable.",
)


# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


def _pg_connect() -> DatabasePort:
    """Create and connect a PostgreSQL adapter using env vars or defaults."""
    adapter: DatabasePort = PostgreSQLDatabaseAdapter(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DBNAME,
        user=PG_USER,
        password=PG_PASSWORD,
        connect_timeout=3,
    )
    adapter.connect()
    return adapter


@pytest.fixture
def pg_db() -> Generator[DatabasePort, None, None]:
    """Provide a connected PostgreSQL adapter with a test table.

    Uses a schema-prefixed table to allow parallel test runs without
    cross-contamination.
    """
    adapter = _pg_connect()
    # Create a test schema and table
    adapter.execute("CREATE SCHEMA IF NOT EXISTS test_schema")
    adapter.execute(
        "CREATE TABLE IF NOT EXISTS test_schema.items ("
        "  id SERIAL PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  value DOUBLE PRECISION"
        ")"
    )
    adapter.execute("DELETE FROM test_schema.items")
    adapter.commit()
    yield adapter
    try:
        adapter.execute("DROP TABLE IF EXISTS test_schema.items")
        adapter.execute("DROP SCHEMA IF EXISTS test_schema CASCADE")
        adapter.commit()
    except Exception:
        pass
    adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Connection lifecycle
# ═════════════════════════════════════════════════════════════════════════


@needs_pg
class TestConnectionLifecycle:
    def test_connect_disconnect(self) -> None:
        adapter: DatabasePort = PostgreSQLDatabaseAdapter(
            host=PG_HOST, port=PG_PORT, dbname=PG_DBNAME,
            user=PG_USER, password=PG_PASSWORD, connect_timeout=3,
        )
        assert not adapter.is_connected()
        assert adapter.connect() is True
        assert adapter.is_connected()
        assert adapter.connect() is False  # already connected
        adapter.disconnect()
        assert not adapter.is_connected()
        adapter.disconnect()  # safe to call twice

    def test_reconnect(self) -> None:
        adapter = _pg_connect()
        adapter.execute("CREATE TABLE IF NOT EXISTS test_schema.ping (x INTEGER)")
        adapter.commit()
        assert adapter.reconnect() is True
        assert adapter.is_connected()
        # Table should still exist
        assert adapter.table_exists("ping")
        adapter.execute("DROP TABLE IF EXISTS test_schema.ping")
        adapter.commit()
        adapter.disconnect()

    def test_context_manager(self) -> None:
        with PostgreSQLDatabaseAdapter(
            host=PG_HOST, port=PG_PORT, dbname=PG_DBNAME,
            user=PG_USER, password=PG_PASSWORD, connect_timeout=3,
        ) as db:
            assert db.is_connected()
            db.execute("SELECT 1")
        assert not db.is_connected()

    def test_execute_without_connect_raises(self) -> None:
        adapter: DatabasePort = PostgreSQLDatabaseAdapter(
            host=PG_HOST, port=PG_PORT,
        )
        with pytest.raises(ConnectionError):
            adapter.execute("SELECT 1")

    def test_dsn_string(self) -> None:
        """Connect using a DSN string instead of keyword args."""
        dsn = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DBNAME}"
        adapter: DatabasePort = PostgreSQLDatabaseAdapter(dsn=dsn, connect_timeout=3)
        adapter.connect()
        row = adapter.fetchone("SELECT 1 as v")
        assert row is not None
        assert row[0] == 1
        adapter.disconnect()

    def test_connection_refused(self) -> None:
        """Connecting to a non-existent host raises ConnectionError."""
        adapter: DatabasePort = PostgreSQLDatabaseAdapter(
            host="127.0.0.1", port=1, dbname="test",
            user="test", password="test", connect_timeout=2,
        )
        with pytest.raises(ConnectionError):
            adapter.connect()


# ═════════════════════════════════════════════════════════════════════════
# CRUD operations (PostgreSQL uses %s placeholders, not ?)
# ═════════════════════════════════════════════════════════════════════════


@needs_pg
class TestCrud:
    def test_insert_and_fetchone(self, pg_db: DatabasePort) -> None:
        pg_db.execute(
            "INSERT INTO test_schema.items (name, value) VALUES (%s, %s)",
            ("alpha", 10.5),
        )
        row = pg_db.fetchone(
            "SELECT * FROM test_schema.items WHERE name = %s", ("alpha",)
        )
        assert row is not None
        assert row[1] == "alpha"  # name column (index 1, after id)
        assert row[2] == 10.5     # value column (index 2)

    def test_fetchall(self, pg_db: DatabasePort) -> None:
        pg_db.execute(
            "INSERT INTO test_schema.items (name, value) VALUES (%s, %s)",
            ("a", 1.0),
        )
        pg_db.execute(
            "INSERT INTO test_schema.items (name, value) VALUES (%s, %s)",
            ("b", 2.0),
        )
        rows = pg_db.fetchall(
            "SELECT * FROM test_schema.items ORDER BY name"
        )
        assert len(rows) == 2
        assert rows[0][1] == "a"
        assert rows[1][1] == "b"

    def test_fetchone_no_match(self, pg_db: DatabasePort) -> None:
        row = pg_db.fetchone(
            "SELECT * FROM test_schema.items WHERE id = %s", (999,)
        )
        assert row is None

    def test_fetchall_empty(self, pg_db: DatabasePort) -> None:
        rows = pg_db.fetchall("SELECT * FROM test_schema.items")
        assert rows == []

    def test_execute_many(self, pg_db: DatabasePort) -> None:
        pg_db.execute_many(
            "INSERT INTO test_schema.items (name, value) VALUES (%s, %s)",
            [("x", 1.0), ("y", 2.0), ("z", 3.0)],
        )
        rows = pg_db.fetchall(
            "SELECT * FROM test_schema.items ORDER BY id"
        )
        assert len(rows) == 3

    def test_commit_persists(self) -> None:
        adapter = _pg_connect()
        adapter.execute("CREATE SCHEMA IF NOT EXISTS test_schema")
        adapter.execute(
            "CREATE TABLE IF NOT EXISTS test_schema.commit_test ("
            "  id SERIAL PRIMARY KEY, val TEXT"
            ")"
        )
        adapter.execute("DELETE FROM test_schema.commit_test")
        adapter.execute(
            "INSERT INTO test_schema.commit_test (val) VALUES (%s)", ("hello",)
        )
        adapter.commit()
        adapter.disconnect()

        # Re-open and verify
        adapter2 = _pg_connect()
        row = adapter2.fetchone(
            "SELECT val FROM test_schema.commit_test WHERE val = %s", ("hello",)
        )
        assert row is not None
        assert row[0] == "hello"
        adapter2.execute("DROP TABLE IF EXISTS test_schema.commit_test")
        adapter2.execute("DROP SCHEMA IF EXISTS test_schema CASCADE")
        adapter2.commit()
        adapter2.disconnect()

    def test_rollback_does_not_persist(self, pg_db: DatabasePort) -> None:
        pg_db.execute(
            "INSERT INTO test_schema.items (name, value) VALUES (%s, %s)",
            ("rollback_test", 99.9),
        )
        pg_db.rollback()
        row = pg_db.fetchone(
            "SELECT * FROM test_schema.items WHERE name = %s", ("rollback_test",)
        )
        assert row is None


# ═════════════════════════════════════════════════════════════════════════
# Transactions
# ═════════════════════════════════════════════════════════════════════════


@needs_pg
class TestTransactions:
    def test_begin_commit(self, pg_db: DatabasePort) -> None:
        pg_db.begin()
        pg_db.execute(
            "INSERT INTO test_schema.items (name, value) VALUES (%s, %s)",
            ("txn", 1.0),
        )
        pg_db.commit()
        row = pg_db.fetchone(
            "SELECT * FROM test_schema.items WHERE name = %s", ("txn",)
        )
        assert row is not None

    def test_begin_rollback(self, pg_db: DatabasePort) -> None:
        pg_db.begin()
        pg_db.execute(
            "INSERT INTO test_schema.items (name, value) VALUES (%s, %s)",
            ("rollback", 2.0),
        )
        pg_db.rollback()
        row = pg_db.fetchone(
            "SELECT * FROM test_schema.items WHERE name = %s", ("rollback",)
        )
        assert row is None


# ═════════════════════════════════════════════════════════════════════════
# DDL helpers
# ═════════════════════════════════════════════════════════════════════════


@needs_pg
class TestDdl:
    def test_table_exists(self, pg_db: DatabasePort) -> None:
        assert pg_db.table_exists("items") is True
        assert pg_db.table_exists("nonexistent_table_xyz") is False

    def test_create_table(self) -> None:
        adapter = _pg_connect()
        result = adapter.create_table(
            "CREATE TABLE IF NOT EXISTS test_schema.ddl_test ("
            "  id SERIAL PRIMARY KEY, val TEXT"
            ")"
        )
        assert result is True
        assert adapter.table_exists("ddl_test") is True
        adapter.execute("DROP TABLE IF EXISTS test_schema.ddl_test")
        adapter.execute("DROP SCHEMA IF EXISTS test_schema CASCADE")
        adapter.commit()
        adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Health & stats
# ═════════════════════════════════════════════════════════════════════════


@needs_pg
class TestHealthAndStats:
    def test_health_check_connected(self, pg_db: DatabasePort) -> None:
        hc = pg_db.health_check()
        assert hc["status"] == "healthy"
        assert hc["connected"] is True
        assert hc["backend"] == "PostgreSQL"
        assert "latency_ms" in hc

    def test_health_check_disconnected(self) -> None:
        adapter: DatabasePort = PostgreSQLDatabaseAdapter(
            host=PG_HOST, port=PG_PORT,
        )
        hc = adapter.health_check()
        assert hc["status"] == "disconnected"
        assert hc["connected"] is False

    def test_stats(self, pg_db: DatabasePort) -> None:
        pg_db.execute("SELECT 1")
        stats = pg_db.stats()
        assert isinstance(stats, DatabaseStats)
        assert stats.is_connected is True
        assert stats.queries_executed >= 1
        assert stats.backend == "PostgreSQL"

    def test_health_check_after_error(self, pg_db: DatabasePort) -> None:
        with pytest.raises(Exception):
            pg_db.execute("INVALID SQL")
        hc = pg_db.health_check()
        assert hc["status"] in ("healthy", "unhealthy")


# ═════════════════════════════════════════════════════════════════════════
# Thread safety
# ═════════════════════════════════════════════════════════════════════════


@needs_pg
class TestThreadSafety:
    def test_concurrent_reads(self) -> None:
        adapter = _pg_connect()
        adapter.execute("CREATE SCHEMA IF NOT EXISTS test_schema")
        adapter.execute(
            "CREATE TABLE IF NOT EXISTS test_schema.conc_test ("
            "  id SERIAL PRIMARY KEY, val INTEGER"
            ")"
        )
        adapter.execute("DELETE FROM test_schema.conc_test")
        for i in range(100):
            adapter.execute(
                "INSERT INTO test_schema.conc_test (val) VALUES (%s)", (i,)
            )
        adapter.commit()

        results: list[int] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def reader() -> None:
            try:
                rows = adapter.fetchall(
                    "SELECT val FROM test_schema.conc_test ORDER BY id"
                )
                with lock:
                    results.extend(row[0] for row in rows)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

        assert len(errors) == 0, f"Concurrent read errors: {errors}"
        assert len(results) == 400  # 4 threads × 100 rows

        adapter.execute("DROP TABLE IF EXISTS test_schema.conc_test")
        adapter.execute("DROP SCHEMA IF EXISTS test_schema CASCADE")
        adapter.commit()
        adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# DSN parsing
# ═════════════════════════════════════════════════════════════════════════


class TestDsnParsing:
    """Unit tests for DSN parsing (no PostgreSQL connection needed)."""

    def test_full_dsn(self) -> None:
        from core.adapters.database.postgres_adapter import _parse_dsn
        params = _parse_dsn("postgresql://user:pass@host1:5432/mydb")
        assert params["host"] == "host1"
        assert params["port"] == 5432
        assert params["dbname"] == "mydb"
        assert params["user"] == "user"
        assert params["password"] == "pass"

    def test_dsn_no_password(self) -> None:
        from core.adapters.database.postgres_adapter import _parse_dsn
        params = _parse_dsn("postgresql://user@host/mydb")
        assert params["host"] == "host"
        assert params["user"] == "user"
        assert "password" not in params or params.get("password") is None

    def test_dsn_simple_host(self) -> None:
        from core.adapters.database.postgres_adapter import _parse_dsn
        params = _parse_dsn("localhost")
        assert params["host"] == "localhost"

    def test_dsn_traditional_format(self) -> None:
        from core.adapters.database.postgres_adapter import _parse_dsn
        params = _parse_dsn("localhost:5432:mydb:user:pass")
        assert params["host"] == "localhost"
        assert params["port"] == 5432
        assert params["dbname"] == "mydb"
        assert params["user"] == "user"
        assert params["password"] == "pass"

    def test_dsn_url_no_prefix(self) -> None:
        from core.adapters.database.postgres_adapter import _parse_dsn
        params = _parse_dsn("user:pass@host:5432/mydb")
        assert params["host"] == "host"
        assert params["user"] == "user"
        assert params["password"] == "pass"
        assert params["dbname"] == "mydb"
