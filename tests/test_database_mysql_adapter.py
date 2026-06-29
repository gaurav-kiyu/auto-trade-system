"""
Contract tests for the MySQLDatabaseAdapter.

Tests mirror the SQLiteDatabaseAdapter contract tests in test_database_port.py
but configured for MySQL. They are conditionally skipped if pymysql is
not installed or no MySQL instance is available.

Usage:
    # Requires pymysql and a running MySQL instance
    python -m pytest tests/test_database_mysql_adapter.py -v

    # Skip MySQL-dependent tests:
    python -m pytest tests/test_database_mysql_adapter.py -v -k "not mysql"
"""

from __future__ import annotations

import os
import threading
from collections.abc import Generator

import pytest
from core.adapters.database import MySQLDatabaseAdapter
from core.adapters.database.mysql_adapter import _parse_mysql_dsn
from core.ports.database import DatabasePort, DatabaseStats

# ── Skip condition ─────────────────────────────────────────────────────────

pymysql = pytest.importorskip("pymysql", reason="pymysql not installed")

# Check if a MySQL instance is available (via env vars or defaults)
MYSQL_HOST = os.environ.get("MYSQL_TEST_HOST", "")
MYSQL_PORT = int(os.environ.get("MYSQL_TEST_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_TEST_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_TEST_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("MYSQL_TEST_DATABASE", "test")

MYSQL_AVAILABLE = bool(os.environ.get("MYSQL_TEST_HOST"))

needs_mysql = pytest.mark.skipif(
    not MYSQL_AVAILABLE,
    reason="No MySQL instance available. Set MYSQL_TEST_HOST to enable.",
)


# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


def _mysql_connect() -> DatabasePort:
    """Create and connect a MySQL adapter using env vars or defaults."""
    adapter: DatabasePort = MySQLDatabaseAdapter(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        connect_timeout=3,
    )
    adapter.connect()
    return adapter


@pytest.fixture
def mysql_db() -> Generator[DatabasePort, None, None]:
    """Provide a connected MySQL adapter with a test table."""
    adapter = _mysql_connect()
    adapter.execute(
        "CREATE TABLE IF NOT EXISTS items ("
        "  id INT AUTO_INCREMENT PRIMARY KEY,"
        "  name VARCHAR(255) NOT NULL,"
        "  value DOUBLE"
        ")"
    )
    adapter.execute("DELETE FROM items")
    adapter.commit()
    yield adapter
    try:
        adapter.execute("DROP TABLE IF EXISTS items")
        adapter.commit()
    except Exception:
        pass
    adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Connection lifecycle
# ═════════════════════════════════════════════════════════════════════════


@needs_mysql
class TestConnectionLifecycle:
    def test_connect_disconnect(self) -> None:
        adapter: DatabasePort = MySQLDatabaseAdapter(
            host=MYSQL_HOST, port=MYSQL_PORT, database=MYSQL_DATABASE,
            user=MYSQL_USER, password=MYSQL_PASSWORD, connect_timeout=3,
        )
        assert not adapter.is_connected()
        assert adapter.connect() is True
        assert adapter.is_connected()
        assert adapter.connect() is False  # already connected
        adapter.disconnect()
        assert not adapter.is_connected()
        adapter.disconnect()  # safe to call twice

    def test_reconnect(self) -> None:
        adapter = _mysql_connect()
        adapter.execute("CREATE TABLE IF NOT EXISTS ping (x INT)")
        adapter.commit()
        assert adapter.reconnect() is True
        assert adapter.is_connected()
        # Table should still exist
        assert adapter.table_exists("ping") is True
        adapter.execute("DROP TABLE IF EXISTS ping")
        adapter.commit()
        adapter.disconnect()

    def test_context_manager(self) -> None:
        with MySQLDatabaseAdapter(
            host=MYSQL_HOST, port=MYSQL_PORT, database=MYSQL_DATABASE,
            user=MYSQL_USER, password=MYSQL_PASSWORD, connect_timeout=3,
        ) as db:
            assert db.is_connected()
            db.execute("SELECT 1")
        assert not db.is_connected()

    def test_execute_without_connect_raises(self) -> None:
        adapter: DatabasePort = MySQLDatabaseAdapter(
            host=MYSQL_HOST, port=MYSQL_PORT,
        )
        with pytest.raises(ConnectionError):
            adapter.execute("SELECT 1")

    def test_dsn_string(self) -> None:
        """Connect using a DSN string instead of keyword args."""
        dsn = f"mysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
        adapter: DatabasePort = MySQLDatabaseAdapter(dsn=dsn, connect_timeout=3)
        adapter.connect()
        row = adapter.fetchone("SELECT 1 as v")
        assert row is not None
        assert row[0] == 1
        adapter.disconnect()

    def test_connection_refused(self) -> None:
        """Connecting to a non-existent host raises ConnectionError."""
        adapter: DatabasePort = MySQLDatabaseAdapter(
            host="127.0.0.1", port=1, database="test",
            user="test", password="test", connect_timeout=2,
        )
        with pytest.raises(ConnectionError):
            adapter.connect()


# ═════════════════════════════════════════════════════════════════════════
# CRUD operations (MySQL uses %s placeholders, not ?)
# ═════════════════════════════════════════════════════════════════════════


@needs_mysql
class TestCrud:
    def test_insert_and_fetchone(self, mysql_db: DatabasePort) -> None:
        mysql_db.execute(
            "INSERT INTO items (name, value) VALUES (%s, %s)",
            ("alpha", 10.5),
        )
        row = mysql_db.fetchone(
            "SELECT * FROM items WHERE name = %s", ("alpha",)
        )
        assert row is not None
        assert row[1] == "alpha"    # name column (index 1, after id)
        assert row[2] == 10.5       # value column (index 2)

    def test_fetchall(self, mysql_db: DatabasePort) -> None:
        mysql_db.execute(
            "INSERT INTO items (name, value) VALUES (%s, %s)", ("a", 1.0),
        )
        mysql_db.execute(
            "INSERT INTO items (name, value) VALUES (%s, %s)", ("b", 2.0),
        )
        rows = mysql_db.fetchall("SELECT * FROM items ORDER BY name")
        assert len(rows) == 2
        assert rows[0][1] == "a"
        assert rows[1][1] == "b"

    def test_fetchone_no_match(self, mysql_db: DatabasePort) -> None:
        row = mysql_db.fetchone(
            "SELECT * FROM items WHERE id = %s", (999,)
        )
        assert row is None

    def test_fetchall_empty(self, mysql_db: DatabasePort) -> None:
        rows = mysql_db.fetchall("SELECT * FROM items")
        assert rows == []

    def test_execute_many(self, mysql_db: DatabasePort) -> None:
        mysql_db.execute_many(
            "INSERT INTO items (name, value) VALUES (%s, %s)",
            [("x", 1.0), ("y", 2.0), ("z", 3.0)],
        )
        rows = mysql_db.fetchall("SELECT * FROM items ORDER BY id")
        assert len(rows) == 3

    def test_commit_persists(self) -> None:
        adapter = _mysql_connect()
        adapter.execute(
            "CREATE TABLE IF NOT EXISTS commit_test ("
            "  id INT AUTO_INCREMENT PRIMARY KEY, val TEXT"
            ")"
        )
        adapter.execute("DELETE FROM commit_test")
        adapter.execute(
            "INSERT INTO commit_test (val) VALUES (%s)", ("hello",)
        )
        adapter.commit()
        adapter.disconnect()

        # Re-open and verify
        adapter2 = _mysql_connect()
        row = adapter2.fetchone(
            "SELECT val FROM commit_test WHERE val = %s", ("hello",)
        )
        assert row is not None
        assert row[0] == "hello"
        adapter2.execute("DROP TABLE IF EXISTS commit_test")
        adapter2.commit()
        adapter2.disconnect()

    def test_rollback_does_not_persist(self, mysql_db: DatabasePort) -> None:
        mysql_db.execute(
            "INSERT INTO items (name, value) VALUES (%s, %s)",
            ("rollback_test", 99.9),
        )
        mysql_db.rollback()
        row = mysql_db.fetchone(
            "SELECT * FROM items WHERE name = %s", ("rollback_test",)
        )
        assert row is None


# ═════════════════════════════════════════════════════════════════════════
# Transactions
# ═════════════════════════════════════════════════════════════════════════


@needs_mysql
class TestTransactions:
    def test_begin_commit(self, mysql_db: DatabasePort) -> None:
        mysql_db.begin()
        mysql_db.execute(
            "INSERT INTO items (name, value) VALUES (%s, %s)", ("txn", 1.0),
        )
        mysql_db.commit()
        row = mysql_db.fetchone(
            "SELECT * FROM items WHERE name = %s", ("txn",)
        )
        assert row is not None

    def test_begin_rollback(self, mysql_db: DatabasePort) -> None:
        mysql_db.begin()
        mysql_db.execute(
            "INSERT INTO items (name, value) VALUES (%s, %s)",
            ("rollback", 2.0),
        )
        mysql_db.rollback()
        row = mysql_db.fetchone(
            "SELECT * FROM items WHERE name = %s", ("rollback",)
        )
        assert row is None


# ═════════════════════════════════════════════════════════════════════════
# DDL helpers
# ═════════════════════════════════════════════════════════════════════════


@needs_mysql
class TestDdl:
    def test_table_exists(self, mysql_db: DatabasePort) -> None:
        assert mysql_db.table_exists("items") is True
        assert mysql_db.table_exists("nonexistent_table_xyz") is False

    def test_create_table(self) -> None:
        adapter = _mysql_connect()
        result = adapter.create_table(
            "CREATE TABLE IF NOT EXISTS ddl_test ("
            "  id INT AUTO_INCREMENT PRIMARY KEY, val TEXT"
            ")"
        )
        assert result is True
        assert adapter.table_exists("ddl_test") is True
        adapter.execute("DROP TABLE IF EXISTS ddl_test")
        adapter.commit()
        adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Health & stats
# ═════════════════════════════════════════════════════════════════════════


@needs_mysql
class TestHealthAndStats:
    def test_health_check_connected(self, mysql_db: DatabasePort) -> None:
        hc = mysql_db.health_check()
        assert hc["status"] == "healthy"
        assert hc["connected"] is True
        assert hc["backend"] == "MySQL"
        assert "latency_ms" in hc

    def test_health_check_disconnected(self) -> None:
        adapter: DatabasePort = MySQLDatabaseAdapter(
            host=MYSQL_HOST, port=MYSQL_PORT,
        )
        hc = adapter.health_check()
        assert hc["status"] == "disconnected"
        assert hc["connected"] is False

    def test_stats(self, mysql_db: DatabasePort) -> None:
        mysql_db.execute("SELECT 1")
        stats = mysql_db.stats()
        assert isinstance(stats, DatabaseStats)
        assert stats.is_connected is True
        assert stats.queries_executed >= 1
        assert stats.backend == "MySQL"

    def test_health_check_after_error(self, mysql_db: DatabasePort) -> None:
        with pytest.raises(Exception):
            mysql_db.execute("INVALID SQL")
        hc = mysql_db.health_check()
        assert hc["status"] in ("healthy", "unhealthy")


# ═════════════════════════════════════════════════════════════════════════
# Thread safety
# ═════════════════════════════════════════════════════════════════════════


@needs_mysql
class TestThreadSafety:
    def test_concurrent_reads(self) -> None:
        adapter = _mysql_connect()
        adapter.execute(
            "CREATE TABLE IF NOT EXISTS conc_test ("
            "  id INT AUTO_INCREMENT PRIMARY KEY, val INT"
            ")"
        )
        adapter.execute("DELETE FROM conc_test")
        for i in range(100):
            adapter.execute(
                "INSERT INTO conc_test (val) VALUES (%s)", (i,)
            )
        adapter.commit()

        results: list[int] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def reader() -> None:
            try:
                rows = adapter.fetchall(
                    "SELECT val FROM conc_test ORDER BY id"
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

        adapter.execute("DROP TABLE IF EXISTS conc_test")
        adapter.commit()
        adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# DSN parsing
# ═════════════════════════════════════════════════════════════════════════


class TestDsnParsing:
    """Unit tests for MySQL DSN parsing (no MySQL connection needed)."""

    def test_full_dsn(self) -> None:
        params = _parse_mysql_dsn("mysql://user:pass@host1:3306/mydb")
        assert params["host"] == "host1"
        assert params["port"] == 3306
        assert params["database"] == "mydb"
        assert params["user"] == "user"
        assert params["password"] == "pass"

    def test_dsn_no_password(self) -> None:
        params = _parse_mysql_dsn("mysql://user@host/mydb")
        assert params["host"] == "host"
        assert params["user"] == "user"
        assert "password" not in params or params.get("password") is None

    def test_dsn_simple_host(self) -> None:
        params = _parse_mysql_dsn("localhost")
        assert params["host"] == "localhost"

    def test_dsn_traditional_format(self) -> None:
        params = _parse_mysql_dsn("localhost:3306:mydb:user:pass")
        assert params["host"] == "localhost"
        assert params["port"] == 3306
        assert params["database"] == "mydb"
        assert params["user"] == "user"
        assert params["password"] == "pass"

    def test_dsn_url_no_prefix(self) -> None:
        params = _parse_mysql_dsn("user:pass@host:3306/mydb")
        assert params["host"] == "host"
        assert params["user"] == "user"
        assert params["password"] == "pass"
        assert params["database"] == "mydb"

    def test_dsn_minimal(self) -> None:
        params = _parse_mysql_dsn("mysql://host/mydb")
        assert params["host"] == "host"
        assert params["database"] == "mydb"
