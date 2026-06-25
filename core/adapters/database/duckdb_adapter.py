"""
DuckDB Database Adapter — implements DatabasePort for DuckDB columnar store.

Wraps duckdb through the DatabasePort interface.
Uses lazy import so duckdb is only required when actually connecting.

DuckDB is an embedded columnar OLAP database, ideal for analytical queries
and large-scale data aggregation. It supports a PostgreSQL-like SQL dialect
and can query CSV, Parquet, and JSON files directly.

Note: DuckDB has no built-in client-server mode by default, so DSN parsing
supports local file paths and in-memory databases.

Usage:
    from core.adapters.database import DuckDBDatabaseAdapter

    db = DuckDBDatabaseAdapter("analytics.db")
    db.connect()
    db.execute("CREATE TABLE metrics (symbol TEXT, score FLOAT, ts TIMESTAMP)")
    db.execute("INSERT INTO metrics VALUES (?, ?, ?)", ("NIFTY", 8.5, "2026-06-17"))
    rows = db.fetchall("SELECT * FROM metrics")
    db.disconnect()

    # In-memory:
    with DuckDBDatabaseAdapter(":memory:") as db:
        rows = db.fetchall("SELECT 1 AS x")
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from core.ports.database import DatabasePort, DatabaseStats

_log = logging.getLogger(__name__)


def _parse_duckdb_dsn(dsn: str) -> tuple[str, dict[str, Any]]:
    """Parse a DuckDB connection string.

    Supports:
      - ``:memory:`` — in-memory database
      - ``/path/to/db.duckdb`` — file-based database
      - ``/path/to/db.duckdb?read_only=true`` — with configuration options
      - Environment variable references: ``my_db`` (created in current directory)

    Returns:
        Tuple of (database path, config dict).
    """
    config: dict[str, Any] = {}
    if "?" in dsn:
        path_part, query = dsn.split("?", 1)
        for pair in query.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                config[k] = v.lower() == "true" if v.lower() in ("true", "false") else v
        return path_part, config
    return dsn, config


class DuckDBDatabaseAdapter(DatabasePort):
    """DatabasePort implementation wrapping DuckDB.

    Thread-safe: uses an RLock for all connection access.

    Args:
        dsn: Database path (``:memory:`` for in-memory, or file path).
        **kwargs: Additional connection configuration passed to duckdb.connect().

    Note:
        Requires ``duckdb`` to be installed. Uses lazy import so
        the ImportError only surfaces when ``connect()`` is called.
    """

    def __init__(
        self,
        dsn: str = ":memory:",
        **kwargs: Any,
    ) -> None:
        self._dsn = dsn
        self._kwargs = kwargs
        self._conn: Any = None  # duckdb.DuckDBPyConnection (lazy type)
        self._lock = threading.RLock()
        self._queries: int = 0
        self._errors: int = 0
        self._last_error: str = ""

        # Parse DSN for config overrides
        self._db_path, self._dsn_config = _parse_duckdb_dsn(dsn)
        self._conn_params: dict[str, Any] = {**self._dsn_config, **kwargs}

    # ── Connection lifecycle ─────────────────────────────────────────────

    def connect(self) -> bool:
        """Establish a DuckDB connection.

        Returns True if the connection was established, False if already open.

        Raises:
            ImportError: If duckdb is not installed.
            ConnectionError: If connection fails.
        """
        if self._conn is not None:
            return False

        try:
            import duckdb
        except ImportError as exc:
            raise ImportError(
                "duckdb is required for DuckDBDatabaseAdapter. "
                "Install it with: pip install duckdb"
            ) from exc

        try:
            self._conn = duckdb.connect(self._db_path, **self._conn_params)
            _log.info(
                "[DUCKDB] Connected to %s",
                self._db_path if self._db_path != ":memory:" else "in-memory",
            )
            return True
        except Exception as exc:
            self._conn = None
            _log.error("[DUCKDB] Connection failed: %s", exc)
            raise ConnectionError(f"DuckDB connection failed: {exc}") from exc

    def disconnect(self) -> None:
        """Close the DuckDB connection. Safe to call multiple times."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as exc:
                    _log.warning("[DUCKDB] Error closing connection: %s", exc)
                finally:
                    self._conn = None
                    _log.info("[DUCKDB] Disconnected")

    def is_connected(self) -> bool:
        return self._conn is not None

    def reconnect(self) -> bool:
        self.disconnect()
        return self.connect()

    # ── Execution ────────────────────────────────────────────────────────

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> Any:
        """Execute a SQL statement and return a DuckDB result.

        Args:
            sql: SQL statement.
            params: Query parameters (tuple for positional, dict for named).

        Returns:
            DuckDB result object.
        """
        conn = self._require_conn()
        with self._lock:
            try:
                if params:
                    result = conn.execute(sql, params)
                else:
                    result = conn.execute(sql)
                self._queries += 1
                return result
            except Exception as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[DUCKDB] Execute error: %s — SQL: %.120s", exc, sql)
                raise

    def execute_many(
        self,
        sql: str,
        params_list: list[tuple[Any, ...] | dict[str, Any]],
    ) -> int:
        """Execute the same SQL with multiple parameter sets.

        Args:
            sql: SQL statement template.
            params_list: List of parameter tuples.

        Returns:
            Number of rows affected.
        """
        conn = self._require_conn()
        with self._lock:
            try:
                # DuckDB's executemany returns the connection, not rowcount
                conn.executemany(sql, params_list)
                affected = len(params_list)
                self._queries += affected
                return affected
            except Exception as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[DUCKDB] ExecuteMany error: %s — SQL: %.120s", exc, sql)
                raise

    def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> Any | None:
        """Execute SQL and return the first row, or None.

        Returns a duckdb result or None.
        """
        result = self.execute(sql, params)
        try:
            return result.fetchone()
        except Exception:
            return None

    def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[Any]:
        """Execute SQL and return all result rows.

        Returns:
            List of rows (each a duckdb Row or tuple).
        """
        result = self.execute(sql, params)
        try:
            rows = result.fetchall()
            return list(rows) if rows else []
        except Exception:
            return []

    # ── Transactions ─────────────────────────────────────────────────────

    def begin(self) -> None:
        """Begin a transaction."""
        self.execute("BEGIN")

    def commit(self) -> None:
        """Commit the current transaction."""
        self.execute("COMMIT")

    def rollback(self) -> None:
        """Rollback the current transaction."""
        self.execute("ROLLBACK")

    # ── DDL helpers ──────────────────────────────────────────────────────

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists using DuckDB's information_schema."""
        row = self.fetchone(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = ? AND table_schema = 'main'",
            (table_name,),
        )
        return row is not None

    def create_table(self, sql: str) -> bool:
        """Execute a CREATE TABLE IF NOT EXISTS statement.

        DuckDB auto-commits DDL statements, so no explicit commit is needed.
        Returns True if the table exists afterwards (created or already present).
        """
        self.execute(sql)
        return True

    # ── Utilities ────────────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        start = time.monotonic()
        try:
            connected = self.is_connected()
            duckdb_version = ""
            if connected:
                row = self.fetchone("SELECT version()")
                if row:
                    duckdb_version = str(row[0])
            latency = time.monotonic() - start
            return {
                "status": "healthy" if connected else "disconnected",
                "connected": connected,
                "backend": "DuckDB",
                "db_path": self._db_path if self._db_path != ":memory:" else "in-memory",
                "latency_ms": round(latency * 1000, 1),
                "queries": self._queries,
                "errors": self._errors,
                "duckdb_version": duckdb_version if duckdb_version else None,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": "DuckDB",
                "db_path": self._db_path if self._db_path != ":memory:" else "in-memory",
                "error": str(exc)[:200],
            }

    def stats(self) -> DatabaseStats:
        return DatabaseStats(
            db_path=self._db_path if self._db_path != ":memory:" else "in-memory",
            is_connected=self.is_connected(),
            total_connections=1,
            queries_executed=self._queries,
            errors=self._errors,
            last_error=self._last_error,
            backend="DuckDB",
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    def _require_conn(self) -> Any:
        if self._conn is None:
            raise ConnectionError(
                f"DuckDB not connected ({self._db_path}). Call .connect() first."
            )
        return self._conn


__all__ = [
    "DuckDBDatabaseAdapter",
]

