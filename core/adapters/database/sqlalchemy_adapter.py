"""
SQLAlchemy Database Adapter — implements DatabasePort for dialect-agnostic SQL.

Wraps SQLAlchemy Engine + connections through the DatabasePort interface.
Uses lazy import so sqlalchemy is only required when actually connecting.

Unlike the other adapters which target a specific database engine, this
adapter works with any SQLAlchemy-supported dialect (SQLite, PostgreSQL,
MySQL, Oracle, MSSQL, etc.) by accepting a full connection URL.

Uses ``exec_driver_sql()`` for raw SQL execution — this bypasses
SQLAlchemy's parameter processing and sends ``?``-style parameters
directly to the DB-API driver, making it compatible with all existing
``DatabasePort`` usage patterns.

Usage:
    from core.adapters.database import SQLAlchemyDatabaseAdapter

    # SQLite (in-memory)
    db = SQLAlchemyDatabaseAdapter("sqlite:///:memory:")
    db.connect()
    rows = db.fetchall("SELECT 1 AS x")

    # PostgreSQL
    db = SQLAlchemyDatabaseAdapter(
        "postgresql://user:pass@localhost:5432/trading"
    )
    db.connect()

    # MySQL
    db = SQLAlchemyDatabaseAdapter("mysql+pymysql://user:pass@localhost/trading")
    db.connect()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from core.ports.database import DatabasePort, DatabaseStats

_log = logging.getLogger(__name__)

# ── Connection string parsing ──────────────────────────────────────────────


def _parse_sqlalchemy_url(url: str) -> str:
    """Validate and return the SQLAlchemy connection URL.

    Supports any SQLAlchemy-supported dialect scheme:
      - sqlite:///:memory:
      - sqlite:///path/to/db.sqlite
      - postgresql://user:pass@host:5432/db
      - mysql+pymysql://user:pass@host:3306/db
      - mssql+pyodbc://...
      - oracle+cx_oracle://...

    Returns the URL unchanged (SQLAlchemy's create_engine handles parsing).
    Raises ValueError if the URL appears invalid.
    """
    if not url or "://" not in url:
        raise ValueError(
            f"Invalid SQLAlchemy URL: {url!r}. "
            "Must include a dialect scheme (e.g. sqlite:///..., postgresql://...)"
        )
    return url


class SQLAlchemyDatabaseAdapter(DatabasePort):
    """DatabasePort implementation wrapping SQLAlchemy Engine.

    Thread-safe: uses an RLock for all connection access.

    Args:
        url: SQLAlchemy connection URL (e.g. ``sqlite:///:memory:``,
             ``postgresql://user:pass@host/db``).
        **kwargs: Additional kwargs passed to ``sqlalchemy.create_engine()``
                  (e.g. pool_size, echo, connect_args).

    Note:
        Requires ``sqlalchemy`` to be installed. Uses lazy import so
        the ImportError only surfaces when ``connect()`` is called.
        The appropriate DB driver for the target dialect must also be
        installed (e.g. psycopg2-binary for PostgreSQL, pymysql for MySQL).
    """

    def __init__(
        self,
        url: str,
        **kwargs: Any,
    ) -> None:
        self._url = url
        self._kwargs = kwargs
        self._engine: Any = None  # sqlalchemy.Engine (lazy type)
        self._conn: Any = None    # sqlalchemy.Connection
        self._lock = threading.RLock()
        self._queries: int = 0
        self._errors: int = 0
        self._last_error: str = ""

        # Extract dialect name for display
        self._dialect: str = "unknown"
        if "://" in url:
            self._dialect = url.split("://")[0].split("+")[0]

    # ── Connection lifecycle ─────────────────────────────────────────────

    def connect(self) -> bool:
        """Establish a SQLAlchemy engine and connection.

        Returns True if the connection was established, False if already open.

        Raises:
            ImportError: If sqlalchemy is not installed.
            ConnectionError: If connection URL is invalid or connection fails.
        """
        if self._conn is not None:
            return False

        try:
            import sqlalchemy as sa
        except ImportError as exc:
            raise ImportError(
                "sqlalchemy is required for SQLAlchemyDatabaseAdapter. "
                "Install it with: pip install sqlalchemy"
            ) from exc

        try:
            self._url = _parse_sqlalchemy_url(self._url)
        except ValueError as exc:
            raise ConnectionError(str(exc)) from exc

        try:
            # SQLite requires check_same_thread=False for multi-threaded access.
            # For SQLite URLs, inject this automatically.
            if self._dialect == "sqlite":
                connect_args = self._kwargs.pop("connect_args", {})
                connect_args.setdefault("check_same_thread", False)
                self._engine = sa.create_engine(
                    self._url, connect_args=connect_args, **self._kwargs
                )
            else:
                self._engine = sa.create_engine(self._url, **self._kwargs)
            self._conn = self._engine.connect()
            _log.info(
                "[SA_DB] Connected to %s at %s",
                self._dialect,
                self._url[:60] + "..." if len(self._url) > 60 else self._url,
            )
            return True
        except Exception as exc:
            self._engine = None
            self._conn = None
            _log.error("[SA_DB] Connection failed: %s", exc)
            raise ConnectionError(f"SQLAlchemy connection failed: {exc}") from exc

    def disconnect(self) -> None:
        """Close the SQLAlchemy connection. Safe to call multiple times."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as exc:
                    _log.warning("[SA_DB] Error closing connection: %s", exc)
                finally:
                    self._conn = None
            if self._engine is not None:
                try:
                    self._engine.dispose()
                except Exception as exc:
                    _log.warning("[SA_DB] Error disposing engine: %s", exc)
                finally:
                    self._engine = None
                    _log.info("[SA_DB] Disconnected from %s", self._dialect)

    def is_connected(self) -> bool:
        if self._conn is None:
            return False
        try:
            import sqlalchemy as sa
            result = self._conn.exec_driver_sql("SELECT 1")
            result.close()
            return True
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
        """Execute a SQL statement and return a SQLAlchemy Result.

        Uses ``exec_driver_sql()`` to pass ``?``-style parameters directly
        to the DB-API driver, ensuring compatibility with existing adapters.

        Args:
            sql: SQL statement (``?`` style placeholders for positional params).
            params: Query parameters (tuple for positional, dict for named).

        Returns:
            SQLAlchemy ``CursorResult`` object.
        """
        conn = self._require_conn()
        with self._lock:
            try:
                if params:
                    result = conn.exec_driver_sql(sql, params)
                else:
                    result = conn.exec_driver_sql(sql)
                self._queries += 1
                return result
            except Exception as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[SA_DB] Execute error: %s — SQL: %.120s", exc, sql)
                raise

    def execute_many(
        self,
        sql: str,
        params_list: list[tuple[Any, ...] | dict[str, Any]],
    ) -> int:
        """Execute the same SQL with multiple parameter sets.

        Uses ``exec_driver_sql()`` for each param set to maintain
        compatibility with ``?``-style placeholders.

        Args:
            sql: SQL statement template.
            params_list: List of parameter tuples/dicts.

        Returns:
            Number of parameter sets executed.
        """
        conn = self._require_conn()
        with self._lock:
            try:
                count = 0
                for params in params_list:
                    if params:
                        conn.exec_driver_sql(sql, params)
                    else:
                        conn.exec_driver_sql(sql)
                    count += 1
                self._queries += count
                return count
            except Exception as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[SA_DB] ExecuteMany error: %s — SQL: %.120s", exc, sql)
                raise

    def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> Any | None:
        """Execute SQL and return the first row as a tuple, or None."""
        result = self.execute(sql, params)
        try:
            row = result.fetchone()
            if row is None:
                return None
            return tuple(row)
        except Exception:
            return None

    def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[Any]:
        """Execute SQL and return all rows as a list of tuples."""
        result = self.execute(sql, params)
        try:
            rows = result.fetchall()
            return [tuple(r) for r in rows] if rows else []
        except Exception:
            return []

    # ── Transactions ─────────────────────────────────────────────────────

    def begin(self) -> None:
        """Begin a transaction.

        SQLAlchemy manages transactions via autobegin — the first
        ``exec_driver_sql()`` call starts a transaction implicitly.
        No explicit ``BEGIN`` is needed.
        """
        pass  # SQLAlchemy's autobegin handles this

    def commit(self) -> None:
        """Commit the current transaction."""
        conn = self._require_conn()
        with self._lock:
            conn.commit()

    def rollback(self) -> None:
        """Rollback the current transaction."""
        conn = self._require_conn()
        with self._lock:
            conn.rollback()

    # ── DDL helpers ──────────────────────────────────────────────────────

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists using SQLAlchemy Inspector."""
        import sqlalchemy as sa
        try:
            from sqlalchemy import inspect
            inspector = inspect(self._engine)
            return table_name in inspector.get_table_names()
        except Exception:
            return False

    def create_table(self, sql: str) -> bool:
        """Execute a CREATE TABLE statement. Returns True on success."""
        self.execute(sql)
        self.commit()
        return True

    # ── Utilities ────────────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        start = time.monotonic()
        try:
            connected = self.is_connected()
            version = ""
            if connected:
                row = self.fetchone("SELECT sqlite_version()")
                if row:
                    version = str(row[0])
            latency = time.monotonic() - start
            return {
                "status": "healthy" if connected else "disconnected",
                "connected": connected,
                "backend": f"SQLAlchemy ({self._dialect})",
                "dialect": self._dialect,
                "latency_ms": round(latency * 1000, 1),
                "queries": self._queries,
                "errors": self._errors,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": f"SQLAlchemy ({self._dialect})",
                "error": str(exc)[:200],
            }

    def stats(self) -> DatabaseStats:
        return DatabaseStats(
            db_path=self._url[:60] + "..." if len(self._url) > 60 else self._url,
            is_connected=self.is_connected(),
            total_connections=1,
            queries_executed=self._queries,
            errors=self._errors,
            last_error=self._last_error,
            backend=f"SQLAlchemy ({self._dialect})",
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    def _require_conn(self) -> Any:
        if self._conn is None:
            raise ConnectionError(
                "Database not connected. Call .connect() first."
            )
        if self._engine is None:
            raise ConnectionError(
                "Engine not initialized. Call .connect() first."
            )
        return self._conn
