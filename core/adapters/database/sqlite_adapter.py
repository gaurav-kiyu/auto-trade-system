"""
SQLite Database Adapter — implements DatabasePort for SQLite.

Wraps raw sqlite3 connections through the DatabasePort interface,
delegating connection management to core.db_utils for WAL mode and
busy_timeout configuration.

Usage:
    from core.adapters.database import SQLiteDatabaseAdapter

    db = SQLiteDatabaseAdapter("trades.db")
    db.connect()
    rows = db.fetchall("SELECT * FROM trades LIMIT ?", (5,))
    db.disconnect()

    # Context manager:
    with SQLiteDatabaseAdapter("trades.db") as db:
        rows = db.fetchall("SELECT * FROM trades")
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from core.db_utils import get_connection
from core.ports.database import DatabasePort, DatabaseStats

_log = logging.getLogger(__name__)


class SQLiteDatabaseAdapter(DatabasePort):
    """DatabasePort implementation wrapping SQLite via core.db_utils.

    Thread-safe: uses an RLock for all connection access.
    Connection management delegates to ``core.db_utils.get_connection``
    to ensure WAL mode and busy_timeout are always applied.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        wal: bool = True,
        busy_timeout_ms: int = 5000,
        row_factory: bool = True,
    ) -> None:
        self._db_path = str(db_path)
        self._wal = wal
        self._busy_timeout_ms = busy_timeout_ms
        self._use_row_factory = row_factory

        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._queries: int = 0
        self._errors: int = 0
        self._last_error: str = ""

    # ── Connection lifecycle ─────────────────────────────────────────────

    def connect(self) -> bool:
        """Open a connection via db_utils.get_connection.

        Returns True if the connection was established, False if already open.
        """
        if self._conn is not None:
            return False
        self._conn = get_connection(
            self._db_path,
            wal=self._wal,
            busy_timeout_ms=self._busy_timeout_ms,
            row_factory=self._use_row_factory,
            check_same_thread=False,
        )
        _log.info("[DB] Connected to %s", self._db_path)
        return True

    def disconnect(self) -> None:
        """Close the connection. Safe to call multiple times."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except (sqlite3.Error, OSError) as exc:
                    _log.warning("[DB] Error closing %s: %s", self._db_path, exc)
                finally:
                    self._conn = None
                    _log.info("[DB] Disconnected from %s", self._db_path)

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
    ) -> sqlite3.Cursor:
        conn = self._require_conn()
        with self._lock:
            try:
                cur = conn.execute(sql, params)
                self._queries += 1
                return cur
            except (sqlite3.Error, OSError, ValueError) as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[DB] Execute error: %s — SQL: %.120s", exc, sql)
                raise

    def execute_many(
        self,
        sql: str,
        params_list: list[tuple[Any, ...] | dict[str, Any]],
    ) -> int:
        conn = self._require_conn()
        with self._lock:
            try:
                cur = conn.executemany(sql, params_list)
                self._queries += len(params_list)
                return cur.rowcount
            except (sqlite3.Error, OSError, ValueError) as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[DB] ExecuteMany error: %s — SQL: %.120s", exc, sql)
                raise

    def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> sqlite3.Row | None:
        cur = self.execute(sql, params)
        return cur.fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        cur = self.execute(sql, params)
        return cur.fetchall()

    # ── Transactions ─────────────────────────────────────────────────────

    def begin(self) -> None:
        conn = self._require_conn()
        with self._lock:
            conn.execute("BEGIN")

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
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return row is not None

    def create_table(self, sql: str) -> bool:
        """Execute a CREATE TABLE IF NOT EXISTS statement.

        Returns True if the table exists afterwards (created or already present).
        """
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
                "backend": "SQLite",
                "db_path": self._db_path,
                "latency_ms": round(latency * 1000, 1),
                "queries": self._queries,
                "errors": self._errors,
                "sqlite_version": sqlite3.sqlite_version if connected else None,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": "SQLite",
                "db_path": self._db_path,
                "error": str(exc)[:200],
            }

    def stats(self) -> DatabaseStats:
        return DatabaseStats(
            db_path=self._db_path,
            is_connected=self.is_connected(),
            total_connections=1,
            queries_executed=self._queries,
            errors=self._errors,
            last_error=self._last_error,
            backend="SQLite",
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise ConnectionError(
                f"Database not connected: {self._db_path}. Call .connect() first."
            )
        return self._conn


__all__ = [
    "SQLiteDatabaseAdapter",
]

