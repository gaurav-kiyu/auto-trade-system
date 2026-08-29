"""Tests for core/adapters/database/connection_pool.py — PostgreSQL connection pool.

Uses ``patch.object`` on ``psycopg2.pool.ThreadedConnectionPool`` to test
pool logic without needing a real PostgreSQL server.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.adapters.database.connection_pool import (
    PoolStats,
    PostgresConnectionPool,
)
from core.adapters.database.dsn_utils import parse_pg_dsn

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_threaded_pool() -> MagicMock:
    """Patch psycopg2.pool.ThreadedConnectionPool with a mock.

    Returns the mocked pool instance (not the class) so tests can configure
    its behavior.
    """
    import psycopg2.pool

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_pool.getconn.return_value = mock_conn
    mock_pool._pool.qsize.return_value = 5  # Simulate 5 available connections

    with patch.object(
        psycopg2.pool,
        "ThreadedConnectionPool",
        return_value=mock_pool,
    ):
        yield mock_pool


@pytest.fixture
def pool(mock_threaded_pool: MagicMock) -> PostgresConnectionPool:
    """Create an initialized PostgresConnectionPool with mocked psycopg2."""
    p = PostgresConnectionPool(
        host="localhost",
        port=5432,
        dbname="testdb",
        user="testuser",
        password="testpass",
        min_conn=2,
        max_conn=10,
    )
    p.initialize()
    return p


# ── PoolStats ───────────────────────────────────────────────────────────────


class TestPoolStats:
    """Tests for PoolStats data class."""

    def test_to_dict(self) -> None:
        stats = PoolStats(
            min_connections=2,
            max_connections=10,
            current_connections=5,
            available_connections=3,
            used_connections=2,
            total_acquired=10,
            total_released=8,
            total_errors=1,
            is_healthy=True,
        )
        d = stats.to_dict()
        assert d["min_connections"] == 2
        assert d["max_connections"] == 10
        assert d["current_connections"] == 5
        assert d["available_connections"] == 3
        assert d["is_healthy"] is True
        assert d["backend"] == "PostgreSQL (pooled)"

    def test_defaults(self) -> None:
        stats = PoolStats()
        assert stats.min_connections == 0
        assert stats.is_healthy is False


# ── PostgresConnectionPool ──────────────────────────────────────────────────


class TestPoolInitialization:
    """Tests for pool initialization and lifecycle."""

    def test_initialize_creates_pool(self, mock_threaded_pool: MagicMock) -> None:
        pool = PostgresConnectionPool(
            host="localhost", min_conn=2, max_conn=10,
        )
        pool.initialize()
        assert pool._initialized is True
        # ThreadedConnectionPool should have been called with min/max + conn params
        import psycopg2.pool
        psycopg2.pool.ThreadedConnectionPool.assert_called_once()

    def test_initialize_idempotent(self, pool: PostgresConnectionPool) -> None:
        """Calling initialize() twice doesn't create a second pool."""
        original_pool = pool._pool
        pool.initialize()  # second call
        assert pool._pool is original_pool  # still the same pool

    def test_close_sets_closed_flag(self, pool: PostgresConnectionPool) -> None:
        pool.close()
        assert pool._closed is True
        assert pool._pool is None

    def test_close_idempotent(self, pool: PostgresConnectionPool) -> None:
        """Calling close() twice doesn't error."""
        pool.close()
        pool.close()  # should not raise
        assert pool._closed is True

    def test_connection_error_raises(self, mock_threaded_pool: MagicMock) -> None:
        import psycopg2.pool

        # Patch again to make the constructor raise
        with patch.object(
            psycopg2.pool,
            "ThreadedConnectionPool",
            side_effect=psycopg2.pool.PoolError("Connection refused"),
        ):
            pool = PostgresConnectionPool(host="localhost")
            with pytest.raises(ConnectionError, match="PostgreSQL connection pool failed"):
                pool.initialize()


class TestPoolAcquireRelease:
    """Tests for connection acquire/release."""

    def test_acquire_returns_connection(self, pool: PostgresConnectionPool) -> None:
        conn = pool.acquire()
        assert conn is not None
        assert pool._total_acquired == 1

    def test_release_returns_connection(self, pool: PostgresConnectionPool) -> None:
        conn = pool.acquire()
        pool.release(conn)
        assert pool._total_released == 1

    def test_acquire_before_initialize_raises(self) -> None:
        pool = PostgresConnectionPool(host="localhost")
        with pytest.raises(ConnectionError, match="not initialized"):
            pool.acquire()

    def test_acquire_after_close_raises(self, mock_threaded_pool: MagicMock) -> None:
        pool = PostgresConnectionPool(host="localhost")
        pool.initialize()
        pool.close()
        with pytest.raises(ConnectionError, match="closed"):
            pool.acquire()

    def test_context_manager_acquire_and_release(self, pool: PostgresConnectionPool) -> None:
        with pool.get_connection() as conn:
            assert conn is not None
            assert pool._total_acquired == 1
        assert pool._total_released == 1

    def test_context_manager_releases_on_error(self, pool: PostgresConnectionPool) -> None:
        with pytest.raises(ValueError, match="test error"):
            with pool.get_connection() as conn:
                assert conn is not None
                raise ValueError("test error")
        assert pool._total_released == 1  # Still released on error

    def test_acquire_increments_counter(self, pool: PostgresConnectionPool) -> None:
        pool.acquire()
        pool.acquire()
        pool.acquire()
        assert pool._total_acquired == 3

    def test_release_handles_pool_error(self, pool: PostgresConnectionPool) -> None:
        """putconn error increments error counter but doesn't propagate."""
        pool._pool.putconn.side_effect = RuntimeError("Connection lost")
        conn = pool.acquire()
        pool.release(conn)  # Should not raise
        assert pool._total_errors == 1

    def test_release_no_pool(self) -> None:
        """release() does nothing when pool is None."""
        pool = PostgresConnectionPool(host="localhost")
        pool.release(MagicMock())  # Should not raise

    def test_acquire_error_increments_errors(self, pool: PostgresConnectionPool) -> None:
        """getconn error increments error counter and raises ConnectionError."""
        pool._pool.getconn.side_effect = RuntimeError("Backend crash")
        with pytest.raises(ConnectionError, match="Failed to acquire"):
            pool.acquire()
        assert pool._total_errors == 1


class TestPoolDSN:
    """Tests for DSN parsing."""

    def test_dsn_full_url(self) -> None:
        params = parse_pg_dsn(
            "postgresql://user:pass@myhost:5432/mydb"
        )
        assert params["host"] == "myhost"
        assert params["port"] == 5432
        assert params["dbname"] == "mydb"
        assert params["user"] == "user"
        assert params["password"] == "pass"

    def test_dsn_simple_host(self) -> None:
        params = parse_pg_dsn("myhost")
        assert params["host"] == "myhost"
        # Default port should be set
        assert params.get("port") in (5432, None)


class TestPoolHealth:
    """Tests for pool health checks and statistics."""

    def test_is_healthy_returns_true(self, pool: PostgresConnectionPool) -> None:
        assert pool.is_healthy() is True

    def test_is_healthy_returns_false_when_not_initialized(self) -> None:
        pool = PostgresConnectionPool(host="localhost")
        assert pool.is_healthy() is False

    def test_is_healthy_returns_false_on_query_error(self, pool: PostgresConnectionPool) -> None:
        # Simulate query failure
        pool._pool.getconn.side_effect = RuntimeError("Connection reset")
        assert pool.is_healthy() is False

    def test_get_stats_returns_values(self, pool: PostgresConnectionPool) -> None:
        stats = pool.get_stats()
        assert isinstance(stats, PoolStats)
        assert stats.min_connections == 2
        assert stats.max_connections == 10
        assert stats.is_healthy is True

    def test_get_stats_no_pool(self) -> None:
        pool = PostgresConnectionPool(host="localhost")
        stats = pool.get_stats()
        assert stats.is_healthy is False
        assert stats.available_connections == 0

    def test_health_check_returns_dict(self, pool: PostgresConnectionPool) -> None:
        result = pool.health_check()
        assert result["status"] == "healthy"
        assert result["connected"] is True
        assert result["backend"] == "PostgreSQL (pooled)"
        assert "latency_ms" in result
        assert "pool" in result
        assert result["pool"]["min_connections"] == 2

    def test_health_check_not_initialized(self) -> None:
        pool = PostgresConnectionPool(host="localhost")
        result = pool.health_check()
        assert result["status"] == "unhealthy"
        assert result["connected"] is False

    def test_health_check_includes_latency(self, pool: PostgresConnectionPool) -> None:
        result = pool.health_check()
        assert result["latency_ms"] >= 0

    def test_health_check_on_query_error(self, pool: PostgresConnectionPool) -> None:
        """health_check returns unhealthy when is_healthy() fails."""
        pool._pool.getconn.side_effect = Exception("Unexpected error")
        result = pool.health_check()
        assert result["status"] == "unhealthy"
        assert result["connected"] is False


class TestPoolContextManager:
    """Tests for pool context manager usage."""

    def test_context_manager_initializes(self, mock_threaded_pool: MagicMock) -> None:
        with PostgresConnectionPool(host="localhost") as p:
            assert p._initialized is True
            assert p._closed is False

    def test_context_manager_closes(self, mock_threaded_pool: MagicMock) -> None:
        p = PostgresConnectionPool(host="localhost")
        with p:
            pass
        assert p._closed is True

    def test_context_manager_with_connection(self, mock_threaded_pool: MagicMock) -> None:
        with PostgresConnectionPool(host="localhost") as p:
            with p.get_connection() as conn:
                assert conn is not None
                assert p._total_acquired == 1
            assert p._total_released == 1
