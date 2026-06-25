"""
PostgreSQL Database Adapter — implements DatabasePort for PostgreSQL.

Wraps psycopg2 connections through the DatabasePort interface.
Uses lazy import so psycopg2 is only required when actually connecting to
a PostgreSQL database. This allows the adapter to coexist in codebases
that primarily use SQLite.

Usage:
    from core.adapters.database import PostgreSQLDatabaseAdapter

    db = PostgreSQLDatabaseAdapter(
        host="localhost",
        port=5432,
        dbname="trading",
        user="app",
        password="secret",
    )
    db.connect()
    rows = db.fetchall("SELECT * FROM trades LIMIT %s", (5,))
    db.disconnect()

    # Context manager:
    with PostgreSQLDatabaseAdapter("postgresql://user:pass@localhost/trading") as db:
        rows = db.fetchall("SELECT * FROM trades")
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from core.metrics_exporter import update_metrics
from core.ports.database import DatabasePort, DatabaseStats

_log = logging.getLogger(__name__)


# ── Connection string parsing ──────────────────────────────────────────────

_DEFAULT_DSN_RE = re.compile(
    r"^(?:postgresql(?:://)?)?"
    r"(?:(?P<user>[^:]+)(?::(?P<password>[^@]+))?@)?"
    r"(?P<host>[^:/]+)"
    r"(?::(?P<port>\d+))?"
    r"(?:/(?P<dbname>.+))?$"
)


def _parse_dsn(dsn: str) -> dict[str, Any]:
    """Parse a PostgreSQL DSN string into connection parameters.

    Supports formats:
      - postgresql://user:pass@host:5432/dbname
      - postgresql://user@host/dbname
      - host:port:dbname:user:password (traditional)
    """
    m = _DEFAULT_DSN_RE.match(dsn)
    if m:
        parts = m.groupdict(default=None)
        params: dict[str, Any] = {}
        if parts["host"]:
            params["host"] = parts["host"]
        if parts["port"]:
            params["port"] = int(parts["port"])
        if parts["dbname"]:
            params["dbname"] = parts["dbname"]
        if parts["user"]:
            params["user"] = parts["user"]
        if parts["password"]:
            params["password"] = parts["password"]
        return params

    # Traditional format: host:port:dbname:user:password
    parts = dsn.split(":")
    if len(parts) >= 3:
        return {
            "host": parts[0],
            "port": int(parts[1]) if parts[1].isdigit() else 5432,
            "dbname": parts[2],
            "user": parts[3] if len(parts) > 3 else "postgres",
            "password": parts[4] if len(parts) > 4 else "",
        }

    # Just a hostname
    return {"host": dsn, "port": 5432, "dbname": "postgres"}


class PostgreSQLDatabaseAdapter(DatabasePort):
    """DatabasePort implementation wrapping PostgreSQL via psycopg2.

    Thread-safe: uses an RLock for all connection access.

    Args:
        dsn: Connection string (``postgresql://user:pass@host:port/dbname``)
             or individual keyword arguments.
        **kwargs: Connection parameters (host, port, dbname, user, password,
                  sslmode, connect_timeout, etc.)

    Note:
        Requires ``psycopg2-binary`` to be installed. Uses lazy import so
        the ImportError only surfaces when ``connect()`` is called.
    """

    def __init__(
        self,
        dsn: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._dsn = dsn
        self._kwargs = kwargs
        self._conn: Any = None  # psycopg2 connection (lazy type)
        self._lock = threading.RLock()
        self._queries: int = 0
        self._errors: int = 0
        self._last_error: str = ""

        # Resolve connection params from DSN or kwargs
        self._conn_params: dict[str, Any] = {}
        if dsn:
            self._conn_params = _parse_dsn(dsn)
        # kwargs override DSN-derived values
        for key in ("host", "port", "dbname", "user", "password", "sslmode", "connect_timeout", "application_name"):
            if key in kwargs:
                self._conn_params[key] = kwargs[key]

    # ── Connection lifecycle ─────────────────────────────────────────────

    def connect(self) -> bool:
        """Establish a PostgreSQL connection.

        Returns True if the connection was established, False if already open.

        Raises:
            ImportError: If psycopg2 is not installed.
            ConnectionError: If connection parameters are missing.
        """
        if self._conn is not None:
            return False

        try:
            import psycopg2
        except ImportError as exc:
            raise ImportError(
                "psycopg2 is required for PostgreSQLDatabaseAdapter. "
                "Install it with: pip install psycopg2-binary"
            ) from exc

        if not self._conn_params:
            raise ConnectionError(
                "No connection parameters provided. "
                "Pass a DSN string or connection keyword arguments."
            )

        try:
            self._conn = psycopg2.connect(**self._conn_params)
            self._conn.autocommit = False
            _log.info(
                "[PG_DB] Connected to %s@%s:%s/%s",
                self._conn_params.get("user", "?"),
                self._conn_params.get("host", "?"),
                self._conn_params.get("port", "?"),
                self._conn_params.get("dbname", "?"),
            )
            return True
        except Exception as exc:
            _log.error("[PG_DB] Connection failed: %s", exc)
            raise ConnectionError(f"PostgreSQL connection failed: {exc}") from exc

    def disconnect(self) -> None:
        """Close the PostgreSQL connection. Safe to call multiple times."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as exc:
                    _log.warning("[PG_DB] Error closing connection: %s", exc)
                finally:
                    self._conn = None
                    _log.info("[PG_DB] Disconnected")

    def is_connected(self) -> bool:
        if self._conn is None:
            return False
        try:
            return not self._conn.closed
        except Exception:
            return False

    def reconnect(self) -> bool:
        self.disconnect()
        return self.connect()

    # ── Execution ────────────────────────────────────────────────────────

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> Any:
        """Execute a single SQL statement and return the cursor.

        For PostgreSQL, parameter placeholders use ``%s`` (not ``?``).
        """
        conn = self._require_conn()
        with self._lock:
            try:
                cur = conn.cursor()
                cur.execute(sql, params)
                self._queries += 1
                return cur
            except Exception as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[PG_DB] Execute error: %s — SQL: %.120s", exc, sql)
                raise

    def execute_many(
        self,
        sql: str,
        params_list: list[tuple[Any, ...] | dict[str, Any]],
    ) -> int:
        conn = self._require_conn()
        with self._lock:
            try:
                cur = conn.cursor()
                for params in params_list:
                    cur.execute(sql, params)
                self._queries += len(params_list)
                return len(params_list)
            except Exception as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[PG_DB] ExecuteMany error: %s — SQL: %.120s", exc, sql)
                raise

    def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> Any | None:
        cur = self.execute(sql, params)
        try:
            return cur.fetchone()
        except Exception as exc:
            _log.warning("[PG_DB] fetchone error: %s", exc)
            return None

    def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[Any]:
        cur = self.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception as exc:
            _log.warning("[PG_DB] fetchall error: %s", exc)
            return []

    # ── Transactions ─────────────────────────────────────────────────────

    def begin(self) -> None:
        conn = self._require_conn()
        with self._lock:
            # psycopg2 starts transactions implicitly, but explicit BEGIN
            # is safe and ensures we're in a transaction
            cur = conn.cursor()
            cur.execute("BEGIN")

    def commit(self) -> None:
        conn = self._require_conn()
        with self._lock:
            conn.commit()

    def rollback(self) -> None:
        conn = self._require_conn()
        with self._lock:
            conn.rollback()

    # ── DDL helpers ──────────────────────────────────────────────────────

    def table_exists(self, table_name: str, schema: str | None = None) -> bool:
        """
        Return True if a table exists in the database.

        Args:
            table_name: Name of the table to check.
            schema: Optional schema name. If None, searches all schemas
                    except system schemas.
        """
        if schema:
            row = self.fetchone(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s",
                (schema, table_name),
            )
        else:
            row = self.fetchone(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
                "AND table_name = %s",
                (table_name,),
            )
        return row is not None

    def create_table(self, sql: str) -> bool:
        self.execute(sql)
        self.commit()
        return True

    # ── Utilities ────────────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        start = time.monotonic()
        try:
            connected = self.is_connected()
            if connected:
                self.fetchone("SELECT 1")
            latency = time.monotonic() - start
            latency_ms = round(latency * 1000, 1)
            result = {
                "status": "healthy" if connected else "disconnected",
                "connected": connected,
                "backend": "PostgreSQL",
                "host": self._conn_params.get("host", "?"),
                "dbname": self._conn_params.get("dbname", "?"),
                "latency_ms": latency_ms,
                "queries": self._queries,
                "errors": self._errors,
            }
            # Report to Prometheus metrics if available
            self._report_metrics(connected, latency_ms)
            return result
        except Exception as exc:
            self._report_metrics(False, 0)
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": "PostgreSQL",
                "error": str(exc)[:200],
            }

    def _report_metrics(self, connected: bool, latency_ms: float) -> None:
        """Report adapter state to Prometheus metrics exporter.

        Safe to call even if prometheus_client is not installed —
        ``update_metrics`` is a no-op in that case.
        """
        try:
            host = self._conn_params.get("host", "default")
            dbname = self._conn_params.get("dbname", "default")
            update_metrics({
                "pg_connected": 1.0 if connected else 0.0,
                "pg_queries_total": {(host, dbname): float(self._queries)},
                "pg_errors_total": {(host, dbname): float(self._errors)},
                "pg_latency_ms": {(host, dbname): latency_ms},
            })
        except Exception as exc:
            _log.debug("[PG_DB] Metrics report skipped: %s", exc)

    def stats(self) -> DatabaseStats:
        return DatabaseStats(
            db_path=self._conn_params.get("dbname", "?"),
            is_connected=self.is_connected(),
            total_connections=1,
            queries_executed=self._queries,
            errors=self._errors,
            last_error=self._last_error,
            backend="PostgreSQL",
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    def _require_conn(self) -> Any:
        if self._conn is None:
            raise ConnectionError(
                "Database not connected. Call .connect() first."
            )
        if self._conn.closed:
            self._conn = None
            raise ConnectionError(
                "Database connection was closed. Call .connect() to re-establish."
            )
        return self._conn


__all__ = [
    "PostgreSQLDatabaseAdapter",
]

