"""Tests for PostgreSQLDatabaseAdapter in pool mode.

Uses mocked psycopg2.pool.ThreadedConnectionPool to test pool mode
wiring without needing a real PostgreSQL server.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.adapters.database import PostgreSQLDatabaseAdapter
from core.adapters.database.connection_pool import PostgresConnectionPool


@pytest.fixture
def mock_pool() -> MagicMock:
    """Create a mock PostgresConnectionPool."""
    import psycopg2.pool

    mock_pool_inst = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_pool_inst.acquire.return_value = mock_conn
    mock_pool_inst.is_healthy.return_value = True

    with patch.object(
        psycopg2.pool,
        "ThreadedConnectionPool",
        return_value=mock_pool_inst,
    ):
        pool = PostgresConnectionPool(host="localhost", min_conn=1, max_conn=5)
        pool._initialized = True
        pool._pool = mock_pool_inst
        yield pool


class TestPostgresAdapterPoolMode:
    """Tests for PostgreSQLDatabaseAdapter with pool."""

    def test_connect_with_pool(self, mock_pool: PostgresConnectionPool) -> None:
        """connect() initializes pool and acquires initial connection."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        result = adapter.connect()
        assert result is True
        assert adapter._pool_mode is True
        assert adapter._data_conn is not None
        assert adapter._conn is not None

    def test_disconnect_with_pool(self, mock_pool: PostgresConnectionPool) -> None:
        """disconnect() releases connection and closes pool."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        adapter.connect()
        adapter.disconnect()
        assert adapter._data_conn is None
        assert adapter._conn is None

    def test_is_connected_pool_mode(self, mock_pool: PostgresConnectionPool) -> None:
        """is_connected() delegates to pool.is_healthy()."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        adapter.connect()
        assert adapter.is_connected() is True

    def test_is_connected_pool_false(self) -> None:
        """is_connected() returns False when pool is not initialized."""
        pool = PostgresConnectionPool(host="localhost", min_conn=1, max_conn=5)
        adapter = PostgreSQLDatabaseAdapter(pool=pool)
        assert adapter.is_connected() is False

    def test_require_conn_pool_mode(self, mock_pool: PostgresConnectionPool) -> None:
        """_require_conn() returns pool-acquired connection."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        adapter.connect()
        conn = adapter._require_conn()
        assert conn is not None

    def test_require_conn_not_connected(self) -> None:
        """_require_conn() raises when pool not connected."""
        pool = PostgresConnectionPool(host="localhost", min_conn=1, max_conn=5)
        adapter = PostgreSQLDatabaseAdapter(pool=pool)
        with pytest.raises(ConnectionError, match="not connected"):
            adapter._require_conn()

    def test_execute_via_pool(self, mock_pool: PostgresConnectionPool) -> None:
        """execute() works through pool-acquired connection."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        adapter.connect()
        cursor = adapter.execute("SELECT 1")
        assert cursor is not None
        assert adapter._queries == 1

    def test_fetchone_via_pool(self, mock_pool: PostgresConnectionPool) -> None:
        """fetchone() works through pool-acquired connection."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        adapter.connect()
        result = adapter.fetchone("SELECT 1")
        assert result is not None

    def test_fetchall_via_pool(self, mock_pool: PostgresConnectionPool) -> None:
        """fetchall() works through pool-acquired connection."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        adapter.connect()
        result = adapter.fetchall("SELECT * FROM test")
        assert result is not None

    def test_commit_rollback_via_pool(self, mock_pool: PostgresConnectionPool) -> None:
        """commit() and rollback() work through pool-acquired connection."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        adapter.connect()
        adapter.begin()
        adapter.commit()
        adapter.begin()
        adapter.rollback()
        # Should not raise

    def test_table_exists_via_pool(self, mock_pool: PostgresConnectionPool) -> None:
        """table_exists() works through pool-acquired connection."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        adapter.connect()
        result = adapter.table_exists("test_table")
        assert result is not None

    def test_health_check_pool_mode(self, mock_pool: PostgresConnectionPool) -> None:
        """health_check() returns healthy status for pool mode."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        adapter.connect()
        result = adapter.health_check()
        assert result["status"] == "healthy"
        assert result["backend"] == "PostgreSQL"

    def test_stats_pool_mode(self, mock_pool: PostgresConnectionPool) -> None:
        """stats() returns stats object for pool mode."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        adapter.connect()
        adapter.execute("SELECT 1")
        stats = adapter.stats()
        assert stats.is_connected is True
        assert stats.queries_executed >= 1
        assert stats.backend == "PostgreSQL"

    def test_reconnect_pool_mode(self, mock_pool: PostgresConnectionPool) -> None:
        """reconnect() tears down and re-establishes pool connection."""
        adapter = PostgreSQLDatabaseAdapter(pool=mock_pool)
        adapter.connect()
        result = adapter.reconnect()
        assert result is True
        assert adapter.is_connected() is True
