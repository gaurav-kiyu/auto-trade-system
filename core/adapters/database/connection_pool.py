"""PostgreSQL Connection Pool — Thread-safe connection pooling for PostgreSQL.

Wraps ``psycopg2.pool.ThreadedConnectionPool`` with lazy import so the
dependency is only required when PostgreSQL is actually used. Provides
connection lifecycle management, health checks, context manager support,
and Prometheus metrics reporting.

Usage:
    from core.adapters.database.connection_pool import PostgresConnectionPool

    pool = PostgresConnectionPool(
        host="localhost",
        port=5432,
        dbname="trading",
        user="app",
        password=os.getenv("DB_PASSWORD", ""),
        min_conn=2,
        max_conn=10,
    )
    pool.initialize()

    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM trades LIMIT %s", (5,))
            rows = cur.fetchall()

    pool.close()

    # Or use the async context manager:
    async with pool:
        conn = await pool.acquire()
        ...

Thread-safety:
    All public methods use a reentrant lock (RLock) to protect the internal
    pool. The pool itself is *not* async-safe — use an async executor or
    thread pool for async contexts.

Metrics:
    Connection pool state is reported to the Prometheus metrics exporter
    via ``core.metrics_exporter.update_metrics`` on each health check.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from core.adapters.database.dsn_utils import parse_pg_dsn

_log = logging.getLogger(__name__)


# ── Data Models ─────────────────────────────────────────────────────────────


@dataclass
class PoolStats:
    """Snapshot of connection pool statistics."""

    min_connections: int = 0
    max_connections: int = 0
    current_connections: int = 0
    available_connections: int = 0
    used_connections: int = 0
    total_acquired: int = 0
    total_released: int = 0
    total_errors: int = 0
    is_healthy: bool = False
    backend: str = "PostgreSQL (pooled)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_connections": self.min_connections,
            "max_connections": self.max_connections,
            "current_connections": self.current_connections,
            "available_connections": self.available_connections,
            "used_connections": self.used_connections,
            "total_acquired": self.total_acquired,
            "total_released": self.total_released,
            "total_errors": self.total_errors,
            "is_healthy": self.is_healthy,
            "backend": self.backend,
        }


# ── Connection Pool ─────────────────────────────────────────────────────────


class PostgresConnectionPool:
    """Thread-safe connection pool for PostgreSQL.

    Wraps ``psycopg2.pool.ThreadedConnectionPool`` with:
    - Lazy import (psycopg2 only required when ``initialize()`` is called)
    - Thread-safe acquire/release via RLock
    - Health checks with Prometheus metrics reporting
    - Context manager support
    - Configurable min/max connections, timeout, retry

    Args:
        host: PostgreSQL host address.
        port: PostgreSQL port (default 5432).
        dbname: Database name.
        user: Database user.
        password: Database password.
        min_conn: Minimum connections kept in pool (default 2).
        max_conn: Maximum connections in pool (default 10).
        connect_timeout: Connection timeout in seconds (default 10).
        application_name: Application name for pg_stat_activity.
        sslmode: SSL mode for connection.
        dsn: Alternative: full DSN string instead of individual params.

    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        dbname: str = "postgres",
        user: str = "postgres",
        password: str = "",
        min_conn: int = 2,
        max_conn: int = 10,
        connect_timeout: int = 10,
        application_name: str = "opb_pool",
        sslmode: str | None = None,
        dsn: str | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._pool: Any = None  # psycopg2.pool.ThreadedConnectionPool (lazy)
        self._initialized = False
        self._closed = False

        # Connection params
        self._conn_params: dict[str, Any] = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
            "connect_timeout": connect_timeout,
            "application_name": application_name,
        }
        if sslmode:
            self._conn_params["sslmode"] = sslmode
        if dsn:
            self._conn_params = parse_pg_dsn(dsn)

        self._min_conn = max(1, min_conn)
        self._max_conn = max(self._min_conn, max_conn)
        self._timeout = connect_timeout

        # Statistics
        self._total_acquired = 0
        self._total_released = 0
        self._total_errors = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Create the connection pool.

        This lazy-imports psycopg2 and establishes the minimum number of
        connections. Safe to call multiple times — subsequent calls are no-ops.

        Raises:
            ImportError: If psycopg2 is not installed.
            ConnectionError: If initial connections cannot be established.

        """
        with self._lock:
            if self._initialized:
                _log.debug("[PG_POOL] Already initialized")
                return

            try:
                from psycopg2 import pool as pg_pool
            except ImportError as exc:
                raise ImportError(
                    "psycopg2 is required for PostgresConnectionPool. "
                    "Install it with: pip install psycopg2-binary",
                ) from exc

            try:
                self._pool = pg_pool.ThreadedConnectionPool(
                    self._min_conn,
                    self._max_conn,
                    **self._conn_params,
                )
                self._initialized = True
                self._closed = False
                _log.info(
                    "[PG_POOL] Initialized pool: min=%d max=%d %s@%s:%d/%s",
                    self._min_conn,
                    self._max_conn,
                    self._conn_params.get("user", "?"),
                    self._conn_params.get("host", "?"),
                    self._conn_params.get("port", "?"),
                    self._conn_params.get("dbname", "?"),
                )
            except Exception as exc:
                self._total_errors += 1
                _log.error("[PG_POOL] Pool initialization failed: %s", exc)
                raise ConnectionError(
                    f"PostgreSQL connection pool failed: {exc}",
                ) from exc

    def close(self) -> None:
        """Close all connections in the pool. Safe to call multiple times."""
        with self._lock:
            if self._pool is None:
                return
            try:
                self._pool.closeall()
            except Exception as exc:
                _log.warning("[PG_POOL] Error closing pool: %s", exc)
            finally:
                self._pool = None
                self._initialized = False
                self._closed = True
                _log.info("[PG_POOL] Connection pool closed")

    # ── Connection Management ─────────────────────────────────────────────

    @contextmanager
    def get_connection(self) -> Generator[Any, None, None]:
        """Acquire a connection from the pool and auto-release on exit.

        Usage:
            with pool.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                result = cur.fetchone()

        Yields:
            psycopg2 connection object.

        Raises:
            ConnectionError: If pool is not initialized or connection fails.

        """
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)

    def acquire(self) -> Any:
        """Get a connection from the pool.

        Returns:
            A psycopg2 connection object.

        Raises:
            ConnectionError: If the pool is not initialized or closed.

        """
        if self._closed:
            raise ConnectionError(
                "Connection pool is closed. Call .initialize() to re-open.",
            )
        if not self._initialized or self._pool is None:
            raise ConnectionError(
                "Connection pool not initialized. Call .initialize() first.",
            )
        try:
            conn = self._pool.getconn()
            with self._lock:
                self._total_acquired += 1
            return conn
        except Exception as exc:
            with self._lock:
                self._total_errors += 1
            _log.error("[PG_POOL] Connection acquire failed: %s", exc)
            raise ConnectionError(f"Failed to acquire connection: {exc}") from exc

    def release(self, conn: Any) -> None:
        """Return a connection to the pool.

        Args:
            conn: A psycopg2 connection previously acquired from this pool.

        """
        if self._pool is None:
            return
        try:
            self._pool.putconn(conn)
            with self._lock:
                self._total_released += 1
        except Exception as exc:
            with self._lock:
                self._total_errors += 1
            _log.warning("[PG_POOL] Connection release error: %s", exc)

    # ── Health / Stats ────────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Return True if the pool is initialized and has available connections."""
        if not self._initialized or self._pool is None:
            return False
        try:
            conn = self._pool.getconn()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            self._pool.putconn(conn)
            return True
        except Exception:
            return False

    def get_stats(self) -> PoolStats:
        """Return current pool statistics."""
        with self._lock:
            available = 0
            used = 0
            if self._pool is not None:
                try:
                    # NOTE: accesses psycopg2's internal _pool (Queue) for qsize;
                    # wrapped in try/except as this is an implementation detail
                    available = self._pool._pool.qsize()  # type: ignore[attr-defined]
                    used = self._max_conn - available
                except Exception:
                    pass

            return PoolStats(
                min_connections=self._min_conn,
                max_connections=self._max_conn,
                current_connections=self._min_conn,
                available_connections=available,
                used_connections=max(0, used),
                total_acquired=self._total_acquired,
                total_released=self._total_released,
                total_errors=self._total_errors,
                is_healthy=self._initialized and not self._closed,
            )

    def health_check(self) -> dict[str, Any]:
        """Run a health check against the pool.

        Returns:
            A dict with health status, latency, and pool statistics.

        """
        start = time.monotonic()
        try:
            healthy = self.is_healthy()
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            stats = self.get_stats()
            result = {
                "status": "healthy" if healthy else "unhealthy",
                "connected": healthy,
                "backend": "PostgreSQL (pooled)",
                "host": self._conn_params.get("host", "?"),
                "dbname": self._conn_params.get("dbname", "?"),
                "latency_ms": latency_ms,
                "pool": stats.to_dict(),
            }
            self._report_metrics(healthy, latency_ms, stats)
            return result
        except Exception as exc:  # pragma: no cover — safety net for unexpected errors
            self._report_metrics(False, 0, None)
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": "PostgreSQL (pooled)",
                "error": str(exc)[:200],
            }

    def _report_metrics(
        self,
        healthy: bool,
        latency_ms: float,
        stats: PoolStats | None,
    ) -> None:
        """Report pool state to Prometheus metrics exporter."""
        try:
            host = self._conn_params.get("host", "default")
            dbname = self._conn_params.get("dbname", "default")
            metrics: dict[str, Any] = {
                "pg_pool_healthy": 1.0 if healthy else 0.0,
                "pg_pool_connections": {  # tags
                    (host, dbname): float(stats.current_connections if stats else 0)
                },
                "pg_pool_available": {  # tags
                    (host, dbname): float(stats.available_connections if stats else 0)
                },
                "pg_pool_errors_total": {  # tags
                    (host, dbname): float(stats.total_errors if stats else 0)
                },
                "pg_pool_latency_ms": {  # tags
                    (host, dbname): latency_ms
                },
            }
            from core.metrics_exporter import update_metrics
            update_metrics(metrics)
        except Exception as exc:
            _log.debug("[PG_POOL] Metrics report skipped: %s", exc)

    # ── Context Manager ───────────────────────────────────────────────────

    def __enter__(self) -> PostgresConnectionPool:
        self.initialize()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        self.close()


__all__ = [
    "PoolStats",
    "PostgresConnectionPool",
]
