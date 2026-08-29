"""Database Provider — Abstraction layer for SQLite/PostgreSQL switching.

Allows the application to use either SQLite (default, single-writer) or
PostgreSQL (production, concurrent access) based on a single config key.

The provider is a simple factory that returns the appropriate database
adapter based on the ``DB_PROVIDER`` config value:
- ``"sqlite"`` (default) — returns a SQLite connection via ``core.db_utils``
- ``"postgresql"`` — returns a ``PostgreSQLDatabaseAdapter`` via ``core.adapters.database``

Usage:
    from core.db_provider import get_database

    # At startup, configure once:
    db = get_database(cfg={
        "DB_PROVIDER": "postgresql",
        "pg_host": "localhost",
        "pg_port": 5432,
        "pg_dbname": "opb_trades",
        "pg_user": "opb_app",
        "pg_password": "secret",
    })
    db.connect()
    rows = db.fetchall("SELECT * FROM trades LIMIT %s", (5,))
    db.disconnect()

    # Or with SQLite (default, no PostgreSQL dependency):
    db = get_database(cfg={})
    conn = db.get_connection()  # Returns sqlite3.Connection
"""

from __future__ import annotations

import logging
import threading
from typing import Any

_log = logging.getLogger(__name__)

# ── Config defaults ─────────────────────────────────────────────────────────

DEFAULT_DB_PROVIDER = "sqlite"
DEFAULT_SQLITE_PATH = "db/trades.db"

# ── Database Provider ───────────────────────────────────────────────────────


class DatabaseProvider:
    """Abstracts database access behind a unified interface.

    Wraps either SQLite (simple, single-writer) or PostgreSQL (production,
    concurrent access) behind the same API.

    Thread-safe: uses an RLock for connection management.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg = cfg or {}
        self._lock = threading.RLock()
        self._provider: str = self._cfg.get("DB_PROVIDER", DEFAULT_DB_PROVIDER).lower()
        self._backend: str = self._provider  # "sqlite" or "postgresql"
        self._connection: Any = None
        self._adapter: Any = None  # PostgreSQLDatabaseAdapter (lazy)
        self._connected: bool = False
        self._queries: int = 0
        self._errors: int = 0

    # ── Connection Management ─────────────────────────────────────────────

    def connect(self) -> bool:
        """Establish a database connection based on the configured provider.

        Returns True if connection was established, False if already connected.

        For SQLite: creates/opens the SQLite database file.
        For PostgreSQL: delegates to PostgreSQLDatabaseAdapter.

        Raises:
            ConnectionError: If connection parameters are invalid.
            ImportError: If PostgreSQL is selected but psycopg2 not installed.
        """
        with self._lock:
            if self._connected:
                return False

            if self._provider == "postgresql":
                self._connect_postgresql()
            else:
                self._connect_sqlite()

            self._connected = True
            _log.info("[DB_PROVIDER] Connected: %s", self._backend)
            return True

    def _connect_sqlite(self) -> None:
        """Connect to SQLite database."""
        db_path = self._cfg.get("DB_PATH", DEFAULT_SQLITE_PATH)
        try:
            import sqlite3
            self._connection = sqlite3.connect(db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA busy_timeout=5000")
            self._backend = f"sqlite:{db_path}"
        except Exception as exc:
            raise ConnectionError(f"SQLite connection failed: {exc}") from exc

    def _connect_postgresql(self) -> None:
        """Connect to PostgreSQL via PostgreSQLDatabaseAdapter."""
        try:
            from core.adapters.database.postgres_adapter import (
                PostgreSQLDatabaseAdapter,
            )

            connect_timeout = int(self._cfg.get("pg_connect_timeout", 10))
            pg_params = {
                "host": self._cfg.get("pg_host", "localhost"),
                "port": int(self._cfg.get("pg_port", 5432)),
                "dbname": self._cfg.get("pg_dbname", "opb_trades"),
                "user": self._cfg.get("pg_user", "opb_app"),
                "password": self._cfg.get("pg_password", ""),
                "connect_timeout": connect_timeout,
            }
            dsn = self._cfg.get("pg_dsn", "")
            if dsn:
                self._adapter = PostgreSQLDatabaseAdapter(dsn=dsn)
            else:
                self._adapter = PostgreSQLDatabaseAdapter(**pg_params)

            self._adapter.connect()
            self._backend = (
                f"postgresql:{pg_params['host']}:{pg_params['port']}/{pg_params['dbname']}"
            )
        except ImportError as exc:
            raise ImportError(
                "psycopg2 is required for PostgreSQL mode. "
                "Install it with: pip install psycopg2-binary"
            ) from exc
        except Exception as exc:
            raise ConnectionError(f"PostgreSQL connection failed: {exc}") from exc

    def disconnect(self) -> None:
        """Close the database connection. Safe to call multiple times."""
        with self._lock:
            if not self._connected:
                return
            try:
                if self._provider == "postgresql" and self._adapter is not None:
                    self._adapter.disconnect()
                elif self._connection is not None:
                    self._connection.close()
            except Exception as exc:
                _log.warning("[DB_PROVIDER] Disconnect error: %s", exc)
            finally:
                self._connection = None
                self._adapter = None
                self._connected = False
                _log.info("[DB_PROVIDER] Disconnected")

    def is_connected(self) -> bool:
        """Check if the database connection is active."""
        with self._lock:
            if not self._connected:
                return False
            if self._provider == "postgresql" and self._adapter is not None:
                return self._adapter.is_connected()  # type: ignore[no-any-return]
            return self._connection is not None

    # ── Query Execution ───────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple | dict | None = None) -> Any:
        """Execute a single SQL statement.

        Args:
            sql: SQL statement (use %s placeholders for PostgreSQL, ? for SQLite).
            params: Query parameters.

        Returns:
            Cursor for SQLite, cursor for PostgreSQL.

        Raises:
            ConnectionError: If not connected.
        """
        if self._provider == "postgresql":
            return self._execute_pg(sql, params or ())
        return self._execute_sqlite(sql, params or ())

    def _execute_sqlite(self, sql: str, params: tuple | dict) -> Any:
        """Execute on SQLite."""
        conn = self._require_conn()
        with self._lock:
            try:
                cur = conn.execute(sql, params)
                self._queries += 1
                return cur
            except Exception as exc:
                self._errors += 1
                _log.warning("[DB_PROVIDER] SQLite execute error: %s", exc)
                raise

    def _execute_pg(self, sql: str, params: tuple | dict) -> Any:
        """Execute on PostgreSQL."""
        adapter = self._require_adapter()
        return adapter.execute(sql, params)

    def fetchall(self, sql: str, params: tuple | dict | None = None) -> list[Any]:
        """Fetch all rows.

        Args:
            sql: SQL query.
            params: Query parameters.

        Returns:
            List of rows (Row objects for SQLite, tuples for PostgreSQL).
            Returns empty list on SQL errors. Re-raises ConnectionError.
        """
        try:
            cur = self.execute(sql, params)
            return cur.fetchall()  # type: ignore[no-any-return]
        except ConnectionError:
            raise
        except Exception as exc:
            self._errors += 1
            _log.warning("[DB_PROVIDER] fetchall error: %s", exc)
            return []

    def fetchone(self, sql: str, params: tuple | dict | None = None) -> Any | None:
        """Fetch one row.

        Args:
            sql: SQL query.
            params: Query parameters.

        Returns:
            A row or None. Returns None on SQL errors. Re-raises ConnectionError.
        """
        try:
            cur = self.execute(sql, params)
            return cur.fetchone()
        except ConnectionError:
            raise
        except Exception as exc:
            self._errors += 1
            _log.warning("[DB_PROVIDER] fetchone error: %s", exc)
            return None

    # ── Transaction Management ────────────────────────────────────────────

    def commit(self) -> None:
        """Commit the current transaction."""
        if self._provider == "postgresql":
            adapter = self._require_adapter()
            adapter.commit()
        else:
            conn = self._require_conn()
            conn.commit()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        if self._provider == "postgresql":
            adapter = self._require_adapter()
            adapter.rollback()
        else:
            conn = self._require_conn()
            conn.rollback()

    # ── Utilities ─────────────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        """Run a health check against the database.

        Returns:
            Dict with status, backend, latency, and query/error counts.
        """
        import time
        start = time.monotonic()
        try:
            connected = self.is_connected()
            if connected:
                self.fetchone("SELECT 1")
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            return {
                "status": "healthy" if connected else "disconnected",
                "connected": connected,
                "backend": self._backend,
                "provider": self._provider,
                "latency_ms": latency_ms,
                "queries": self._queries,
                "errors": self._errors,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": self._backend,
                "error": str(exc)[:200],
            }

    def get_connection(self) -> Any:
        """Get the raw connection object.

        For SQLite: returns the sqlite3.Connection.
        For PostgreSQL: returns the psycopg2 connection.

        Raises:
            ConnectionError: If not connected.
        """
        if self._provider == "postgresql":
            return self._require_adapter()
        return self._require_conn()

    # ── Internal Helpers ──────────────────────────────────────────────────

    def _require_conn(self) -> Any:
        """Get the SQLite connection, raising if not available."""
        if self._connection is None:
            raise ConnectionError("Database not connected. Call .connect() first.")
        return self._connection

    def _require_adapter(self) -> Any:
        """Get the PostgreSQL adapter, raising if not available."""
        if self._adapter is None:
            raise ConnectionError(
                "PostgreSQL adapter not available. Call .connect() first."
            )
        return self._adapter

    # ── Stats ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get database provider statistics."""
        with self._lock:
            return {
                "provider": self._provider,
                "backend": self._backend,
                "connected": self._connected,
                "queries": self._queries,
                "errors": self._errors,
            }


# ── Singleton Factory ───────────────────────────────────────────────────────

_provider_instance: DatabaseProvider | None = None
_provider_lock = threading.RLock()


def get_database(cfg: dict[str, Any] | None = None) -> DatabaseProvider:
    """Get the singleton DatabaseProvider instance.

    If called without cfg and an instance already exists, returns the
    existing instance. If called with cfg, creates a new instance
    (disconnecting any previous singleton first).

    Args:
        cfg: Config dict with DB_PROVIDER, DB_PATH, pg_* keys.

    Returns:
        A DatabaseProvider instance.
    """
    global _provider_instance
    if cfg is not None:
        with _provider_lock:
            if _provider_instance is not None:
                _provider_instance.disconnect()
            _provider_instance = DatabaseProvider(cfg)
            return _provider_instance
    with _provider_lock:
        if _provider_instance is None:
            _provider_instance = DatabaseProvider()
        return _provider_instance


def reset_database() -> None:
    """Force-reset the singleton (for testing)."""
    global _provider_instance
    with _provider_lock:
        if _provider_instance is not None:
            _provider_instance.disconnect()
        _provider_instance = None


__all__ = [
    "DatabaseProvider",
    "get_database",
    "reset_database",
]
