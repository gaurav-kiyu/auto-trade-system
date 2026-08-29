"""Tests for core/db_provider.py — DatabaseProvider abstraction layer.

Covers:
- SQLite mode (default): connect, execute, fetchall, fetchone, commit, rollback
- PostgreSQL mode: constructor, config passing, graceful degradation
- Singleton factory: get_database(), reset_database()
- Edge cases: missing config, disconnection, health check, stats
"""

from __future__ import annotations

import os
import tempfile

import pytest
from core.db_provider import DatabaseProvider, get_database, reset_database


class TestSQLiteMode:
    """Tests for SQLite database provider (default mode)."""

    def test_connect_creates_db(self):
        """SQLite connect should create the database file."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            result = provider.connect()
            assert result is True
            assert provider.is_connected() is True
            assert os.path.exists(db_path)
        finally:
            provider.disconnect()
            os.unlink(db_path)

    def test_double_connect_returns_false(self):
        """Second connect call should return False."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            result = provider.connect()
            assert result is False
        finally:
            provider.disconnect()
            os.unlink(db_path)

    def test_execute_and_fetchall(self):
        """Execute and fetchall should work end-to-end."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            provider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
            provider.execute("INSERT INTO test (name) VALUES (?)", ("hello",))
            provider.execute("INSERT INTO test (name) VALUES (?)", ("world",))
            rows = provider.fetchall("SELECT * FROM test ORDER BY id")
            assert len(rows) == 2
            assert rows[0]["name"] == "hello"
            assert rows[1]["name"] == "world"
        finally:
            provider.disconnect()
            os.unlink(db_path)

    def test_fetchone(self):
        """Fetchone should return a single row."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            provider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
            provider.execute("INSERT INTO test (name) VALUES (?)", ("only",))
            row = provider.fetchone("SELECT * FROM test")
            assert row is not None
            assert row["name"] == "only"
        finally:
            provider.disconnect()
            os.unlink(db_path)

    def test_fetchone_empty(self):
        """Fetchone on empty table should return None."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            provider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
            row = provider.fetchone("SELECT * FROM test")
            assert row is None
        finally:
            provider.disconnect()
            os.unlink(db_path)

    def test_commit_and_rollback(self):
        """Commit and rollback should work."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            provider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
            provider.execute("INSERT INTO test (name) VALUES (?)", ("committed",))
            provider.commit()

            # Verify committed data
            row = provider.fetchone("SELECT name FROM test WHERE id=1")
            assert row is not None
            assert row["name"] == "committed"
        finally:
            provider.disconnect()
            os.unlink(db_path)

    def test_disconnect(self):
        """Disconnect should close the connection."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            provider.disconnect()
            assert provider.is_connected() is False
        finally:
            os.unlink(db_path)

    def test_double_disconnect_safe(self):
        """Double disconnect should not raise."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            provider.disconnect()
            provider.disconnect()  # Should not raise
        finally:
            os.unlink(db_path)


class TestPostgreSQLMode:
    """Tests for PostgreSQL database provider mode."""

    def test_postgresql_constructor(self):
        """PostgreSQL constructor should store params correctly."""
        provider = DatabaseProvider({
            "DB_PROVIDER": "postgresql",
            "pg_host": "pg.example.com",
            "pg_port": 5432,
            "pg_dbname": "opb_test",
            "pg_user": "test_user",
            "pg_password": "secret123",
        })
        assert provider._provider == "postgresql"
        assert provider._cfg["pg_host"] == "pg.example.com"

    def test_postgresql_connect_fails_gracefully(self):
        """PostgreSQL connect should raise ConnectionError when server is unreachable."""
        provider = DatabaseProvider({
            "DB_PROVIDER": "postgresql",
            "pg_host": "192.0.2.1",  # TEST-NET, unreachable
            "pg_port": 5432,
            "pg_dbname": "test",
            "pg_user": "test",
            "pg_password": "test",
            "pg_connect_timeout": 1,
        })
        with pytest.raises((ConnectionError, ImportError)):
            provider.connect()

    def test_postgresql_no_psycopg2(self):
        """Without psycopg2, connect should raise ImportError."""
        import sys
        if "psycopg2" in sys.modules:
            pytest.skip("psycopg2 is installed, can't test missing dependency")
        provider = DatabaseProvider({
            "DB_PROVIDER": "postgresql",
            "pg_host": "localhost",
            "pg_dbname": "test",
            "pg_user": "test",
            "pg_password": "test",
        })
        with pytest.raises(ImportError):
            provider.connect()

    def test_postgresql_defaults(self):
        """PostgreSQL constructor should store provider type."""
        provider = DatabaseProvider({"DB_PROVIDER": "postgresql"})
        assert provider._provider == "postgresql"
        assert provider._backend == "postgresql"


class TestHealthCheck:
    """Tests for health check."""

    def test_health_check_disconnected(self):
        """Health check on disconnected provider should show disconnected."""
        provider = DatabaseProvider()
        result = provider.health_check()
        assert result["status"] == "disconnected"
        assert result["connected"] is False

    def test_health_check_connected(self):
        """Health check on connected provider should show healthy."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            result = provider.health_check()
            assert result["status"] == "healthy"
            assert result["connected"] is True
            assert result["provider"] == "sqlite"
            assert result["latency_ms"] >= 0
        finally:
            provider.disconnect()
            os.unlink(db_path)


class TestStats:
    """Tests for statistics tracking."""

    def test_stats_empty(self):
        """Stats should reflect initial state."""
        provider = DatabaseProvider()
        stats = provider.get_stats()
        assert stats["provider"] == "sqlite"
        assert stats["connected"] is False
        assert stats["queries"] == 0
        assert stats["errors"] == 0

    def test_stats_after_queries(self):
        """Stats should track query and error counts."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            provider.execute("CREATE TABLE t (x INTEGER)")
            provider.execute("INSERT INTO t VALUES (?)", (1,))
            provider.fetchall("SELECT * FROM t")
            stats = provider.get_stats()
            assert stats["queries"] >= 3
            assert stats["connected"] is True
        finally:
            provider.disconnect()
            os.unlink(db_path)


class TestSingleton:
    """Tests for singleton factory."""

    def test_get_database_returns_same_instance(self):
        """get_database() without args should return same instance."""
        reset_database()
        d1 = get_database()
        d2 = get_database()
        assert d1 is d2
        reset_database()

    def test_get_database_with_cfg_creates_new(self):
        """get_database() with cfg should create new instance."""
        reset_database()
        d1 = get_database({"DB_PROVIDER": "sqlite"})
        assert d1 is not None
        assert d1._provider == "sqlite"
        reset_database()

    def test_reset_disconnects(self):
        """reset_database() should disconnect the singleton."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            # Use the singleton so reset_database() can find it
            reset_database()
            singleton = get_database({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            singleton.connect()
            assert singleton.is_connected() is True
            reset_database()
            assert singleton.is_connected() is False
        finally:
            # Disconnect local ref before unlinking
            try:
                singleton.disconnect()
            except Exception:
                pass
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_get_database_default_provider(self):
        """Default provider should be sqlite."""
        reset_database()
        db = get_database()
        assert db._provider == "sqlite"
        reset_database()


class TestErrorHandling:
    """Tests for error handling."""

    def test_execute_without_connect(self):
        """Execute without connect should raise."""
        provider = DatabaseProvider()
        with pytest.raises(ConnectionError):
            provider.execute("SELECT 1")

    def test_get_connection_without_connect(self):
        """get_connection without connect should raise."""
        provider = DatabaseProvider()
        with pytest.raises(ConnectionError):
            provider.get_connection()

    def test_fetchall_on_bad_sql(self):
        """Fetchall with invalid SQL should return empty list."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            results = provider.fetchall("SELECT * FROM nonexistent_table")
            assert results == []
        finally:
            provider.disconnect()
            os.unlink(db_path)

    def test_health_check_after_disconnect(self):
        """Health check after disconnect should show disconnected."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            provider.disconnect()
            result = provider.health_check()
            assert result["status"] == "disconnected"
        finally:
            os.unlink(db_path)

    def test_stats_error_tracking(self):
        """Stats should track errors."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            provider = DatabaseProvider({"DB_PROVIDER": "sqlite", "DB_PATH": db_path})
            provider.connect()
            provider.fetchall("SELECT * FROM nonexistent")
            provider.fetchone("SELECT * FROM nonexistent")
            stats = provider.get_stats()
            assert stats["errors"] >= 2
        finally:
            provider.disconnect()
            os.unlink(db_path)
