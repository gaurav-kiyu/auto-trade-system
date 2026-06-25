"""
Database Port Interface

Defines the contract for low-level database connection management.
Provides connection lifecycle, raw SQL execution, and transaction control
independent of any specific database engine (SQLite, PostgreSQL, etc.).

This is separate from PersistencePort (high-level CRUD) — DatabasePort
is the connection/execution layer that PersistencePort implementations
can use internally, or that callers can use directly for raw SQL.

Usage:
    from core.ports.database import DatabasePort

    class MyPostgresAdapter(DatabasePort):
        ...

    db: DatabasePort = SQLiteDatabaseAdapter("trades.db")
    db.connect()
    rows = db.execute("SELECT * FROM trades").fetchall()
    db.disconnect()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class DatabaseStats:
    """Statistics snapshot from a DatabasePort implementation."""
    db_path: str
    is_connected: bool
    total_connections: int = 0
    queries_executed: int = 0
    errors: int = 0
    last_error: str = ""
    backend: str = "unknown"


class DatabasePort(ABC):
    """
    Abstract interface for low-level database connection management.

    Implementations wrap a single database backend (SQLite, PostgreSQL, etc.)
    and provide connection lifecycle, raw SQL execution, and transaction control.

    Thread-safety is the implementation's responsibility — use RLock internally
    when shared between threads.
    """

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish a connection to the database.

        Returns:
            True if connection was established, False if already connected.
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Close the database connection. Safe to call multiple times."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the underlying connection is open and usable."""
        ...

    @abstractmethod
    def reconnect(self) -> bool:
        """
        Force-close and re-establish the connection.

        Returns:
            True if reconnection succeeded.
        """
        ...

    # ── Execution ────────────────────────────────────────────────────

    @abstractmethod
    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> Any:
        """
        Execute a single SQL statement and return a cursor/result.

        Args:
            sql: SQL statement to execute.
            params: Query parameters (tuple for positional, dict for named).

        Returns:
            Implementation-specific cursor / result object.
        """
        ...

    @abstractmethod
    def execute_many(
        self,
        sql: str,
        params_list: list[tuple[Any, ...] | dict[str, Any]],
    ) -> int:
        """
        Execute the same SQL with multiple parameter sets.

        Args:
            sql: SQL statement template.
            params_list: List of parameter tuples/dicts.

        Returns:
            Number of rows affected.
        """
        ...

    @abstractmethod
    def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> Any | None:
        """
        Execute SQL and return the first row, or None.

        Args:
            sql: SQL statement.
            params: Query parameters.

        Returns:
            Single row (dict-like) or None.
        """
        ...

    @abstractmethod
    def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[Any]:
        """
        Execute SQL and return all result rows.

        Args:
            sql: SQL statement.
            params: Query parameters.

        Returns:
            List of rows (each dict-like).
        """
        ...

    # ── Transactions ──────────────────────────────────────────────────

    @abstractmethod
    def begin(self) -> None:
        """Begin a transaction."""
        ...

    @abstractmethod
    def commit(self) -> None:
        """Commit the current transaction."""
        ...

    @abstractmethod
    def rollback(self) -> None:
        """Rollback the current transaction."""
        ...

    # ── DDL helpers ───────────────────────────────────────────────────

    @abstractmethod
    def table_exists(self, table_name: str) -> bool:
        """Return True if a table exists in the database."""
        ...

    @abstractmethod
    def create_table(self, sql: str) -> bool:
        """
        Execute a CREATE TABLE statement.

        Args:
            sql: Full CREATE TABLE DDL.

        Returns:
            True if table was created (did not already exist).
        """
        ...

    # ── Utilities ─────────────────────────────────────────────────────

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """
        Return a health-check dictionary with status, latency, backend info.
        """
        ...

    @abstractmethod
    def stats(self) -> DatabaseStats:
        """Return a snapshot of usage statistics."""
        ...

    def __enter__(self):
        """Context manager entry — auto-connect."""
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit — auto-disconnect."""
        self.disconnect()


__all__ = [
    "DatabasePort",
    "DatabaseStats",
]

