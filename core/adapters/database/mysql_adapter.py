"""
MySQL Database Adapter — implements DatabasePort for MySQL/MariaDB.

Wraps pymysql connections through the DatabasePort interface.
Uses lazy import so pymysql is only required when actually connecting to
a MySQL database. This allows the adapter to coexist in codebases
that primarily use SQLite or PostgreSQL.

Usage:
    from core.adapters.database import MySQLDatabaseAdapter

    db = MySQLDatabaseAdapter(
        host="localhost",
        port=3306,
        database="trading",
        user="app",
        password="secret",
    )
    db.connect()
    rows = db.fetchall("SELECT * FROM trades LIMIT %s", (5,))
    db.disconnect()

    # Context manager:
    with MySQLDatabaseAdapter(host="localhost", user="root", password="secret", database="trading") as db:
        rows = db.fetchall("SELECT * FROM trades")
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from core.ports.database import DatabasePort, DatabaseStats

_log = logging.getLogger(__name__)


# ── Connection string parsing ──────────────────────────────────────────────

_MYSQL_DSN_RE = re.compile(
    r"^(?:mysql(?:://)?)?"
    r"(?:(?P<user>[^:]+)(?::(?P<password>[^@]+))?@)?"
    r"(?P<host>[^:/]+)"
    r"(?::(?P<port>\d+))?"
    r"(?:/(?P<database>.+))?$"
)


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    """Parse a MySQL DSN string into connection parameters.

    Supports formats:
      - mysql://user:pass@host:3306/database
      - mysql://user@host/database
      - user:pass@host:3306/database
    """
    m = _MYSQL_DSN_RE.match(dsn)
    if m:
        parts = m.groupdict(default=None)
        params: dict[str, Any] = {}
        if parts["host"]:
            params["host"] = parts["host"]
        if parts["port"]:
            params["port"] = int(parts["port"])
        if parts["database"]:
            params["database"] = parts["database"]
        if parts["user"]:
            params["user"] = parts["user"]
        if parts["password"]:
            params["password"] = parts["password"]
        return params

    # Traditional format: host:port:database:user:password
    parts = dsn.split(":")
    if len(parts) >= 3:
        result: dict[str, Any] = {
            "host": parts[0],
            "port": int(parts[1]) if parts[1].isdigit() else 3306,
            "database": parts[2],
        }
        if len(parts) > 3:
            result["user"] = parts[3]
        if len(parts) > 4:
            result["password"] = parts[4]
        return result

    # Just a hostname
    return {"host": dsn, "port": 3306}


class MySQLDatabaseAdapter(DatabasePort):
    """DatabasePort implementation wrapping MySQL/MariaDB via pymysql.

    Thread-safe: uses an RLock for all connection access.

    Args:
        dsn: Connection string (``mysql://user:pass@host:port/database``)
             or individual keyword arguments.
        **kwargs: Connection parameters (host, port, database, user, password,
                  charset, connect_timeout, etc.)

    Note:
        Requires ``pymysql`` to be installed. Uses lazy import so
        the ImportError only surfaces when ``connect()`` is called.
    """

    def __init__(
        self,
        dsn: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._dsn = dsn
        self._kwargs = kwargs
        self._conn: Any = None  # pymysql connection (lazy type)
        self._lock = threading.RLock()
        self._queries: int = 0
        self._errors: int = 0
        self._last_error: str = ""

        # Resolve connection params from DSN or kwargs
        self._conn_params: dict[str, Any] = {}
        if dsn:
            self._conn_params = _parse_mysql_dsn(dsn)
        # kwargs override DSN-derived values
        for key in ("host", "port", "database", "user", "password", "charset", "connect_timeout", "ssl", "read_timeout", "write_timeout", "autocommit"):
            if key in kwargs:
                self._conn_params[key] = kwargs[key]

    # ── Connection lifecycle ─────────────────────────────────────────────

    def connect(self) -> bool:
        """Establish a MySQL connection.

        Returns True if the connection was established, False if already open.

        Raises:
            ImportError: If pymysql is not installed.
            ConnectionError: If connection parameters are missing.
        """
        if self._conn is not None:
            return False

        try:
            import pymysql
        except ImportError as exc:
            raise ImportError(
                "pymysql is required for MySQLDatabaseAdapter. "
                "Install it with: pip install pymysql"
            ) from exc

        if not self._conn_params:
            raise ConnectionError(
                "No connection parameters provided. "
                "Pass a DSN string or connection keyword arguments."
            )

        try:
            self._conn = pymysql.connect(**self._conn_params)
            self._conn.autocommit = False
            _log.info(
                "[MYSQL_DB] Connected to %s@%s:%s/%s",
                self._conn_params.get("user", "?"),
                self._conn_params.get("host", "?"),
                self._conn_params.get("port", "?"),
                self._conn_params.get("database", "?"),
            )
            return True
        except Exception as exc:
            _log.error("[MYSQL_DB] Connection failed: %s", exc)
            raise ConnectionError(f"MySQL connection failed: {exc}") from exc

    def disconnect(self) -> None:
        """Close the MySQL connection. Safe to call multiple times."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as exc:
                    _log.warning("[MYSQL_DB] Error closing connection: %s", exc)
                finally:
                    self._conn = None
                    _log.info("[MYSQL_DB] Disconnected")

    def is_connected(self) -> bool:
        if self._conn is None:
            return False
        try:
            return self._conn.open
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

        For MySQL, parameter placeholders use ``%s`` (not ``?``).
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
                _log.warning("[MYSQL_DB] Execute error: %s — SQL: %.120s", exc, sql)
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
                _log.warning("[MYSQL_DB] ExecuteMany error: %s — SQL: %.120s", exc, sql)
                raise

    def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> Any | None:
        cur = self.execute(sql, params)
        try:
            return cur.fetchone()
        except Exception as exc:
            _log.warning("[MYSQL_DB] fetchone error: %s", exc)
            return None

    def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[Any]:
        cur = self.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception as exc:
            _log.warning("[MYSQL_DB] fetchall error: %s", exc)
            return []

    # ── Transactions ─────────────────────────────────────────────────────

    def begin(self) -> None:
        conn = self._require_conn()
        with self._lock:
            cur = conn.cursor()
            cur.execute("START TRANSACTION")

    def commit(self) -> None:
        conn = self._require_conn()
        with self._lock:
            conn.commit()

    def rollback(self) -> None:
        conn = self._require_conn()
        with self._lock:
            conn.rollback()

    # ── DDL helpers ──────────────────────────────────────────────────────

    def table_exists(self, table_name: str) -> bool:
        row = self.fetchone(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = %s",
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
            return {
                "status": "healthy" if connected else "disconnected",
                "connected": connected,
                "backend": "MySQL",
                "host": self._conn_params.get("host", "?"),
                "database": self._conn_params.get("database", "?"),
                "latency_ms": round(latency * 1000, 1),
                "queries": self._queries,
                "errors": self._errors,
                "mysql_version": self._get_version() if connected else None,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": "MySQL",
                "error": str(exc)[:200],
            }

    def _get_version(self) -> str | None:
        try:
            row = self.fetchone("SELECT VERSION() as version")
            if row:
                return row[0]
        except Exception:
            pass
        return None

    def stats(self) -> DatabaseStats:
        db_path = self._conn_params.get("database", "?")
        return DatabaseStats(
            db_path=f"{self._conn_params.get('host', '?')}/{db_path}",
            is_connected=self.is_connected(),
            total_connections=1,
            queries_executed=self._queries,
            errors=self._errors,
            last_error=self._last_error,
            backend="MySQL",
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    def _require_conn(self) -> Any:
        if self._conn is None:
            raise ConnectionError(
                "Database not connected. Call .connect() first."
            )
        if not self._conn.open:
            self._conn = None
            raise ConnectionError(
                "Database connection was closed. Call .connect() to re-establish."
            )
        return self._conn
