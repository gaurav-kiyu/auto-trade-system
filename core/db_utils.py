"""
Shared SQLite connection utilities - centralized WAL + busy_timeout + async writer.

DEBT-009 mitigation: Provides a queue-based async writer for high-frequency
write operations, plus connection pooling with WAL mode and busy_timeout
for concurrent read/write safety during live trading.

Usage:
    from core.db_utils import get_connection, get_connection_cached

    conn = get_connection("trades.db")
    # ... use conn ...
    conn.close()

    # For async writes:
    from core.db_utils import AsyncDbWriter
    writer = AsyncDbWriter("trades.db")
    writer.submit("INSERT INTO trades VALUES (?, ?)", (1, "test"))
    writer.stop()  # flush + stop background thread

All connections produced by get_connection() have:
  - PRAGMA journal_mode=WAL   (concurrent readers don't block writers)
  - PRAGMA busy_timeout=5000  (wait up to 5s instead of failing immediately)
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_BUSY_TIMEOUT_MS",
    "get_connection",
    "get_connection_cached",
    "create_database_port",
    "AsyncDbWriter",
    "WriteOperation",
]

import logging
import queue
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

DEFAULT_BUSY_TIMEOUT_MS = 5000


# ═══════════════════════════════════════════════════════════════════════════
# Async Writer (DEBT-009)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class WriteOperation:
    """A queued database write operation."""
    sql: str
    params: tuple[Any, ...] | dict[str, Any] = field(default_factory=tuple)
    callback: Callable[[bool, str], None] | None = None
    submitted_at: float = field(default_factory=time.time)


class AsyncDbWriter:
    """Queue-based async SQLite writer with background thread.

    Submits write operations to a thread-safe queue; a background worker
    drains the queue sequentially on a single shared connection.
    Read operations remain synchronous on the caller's thread.

    Args:
        db_path: Path to the SQLite database file.
        max_queue_size: Maximum queued operations before ``submit()`` blocks.
        wal: Enable WAL mode on the connection.
        busy_timeout_ms: SQLite busy timeout in milliseconds.

    Example:
        writer = AsyncDbWriter("trades.db")
        writer.submit("INSERT INTO log VALUES (?)", ("hello",))
        # ... continue trading without waiting for DB write ...
        writer.stop()  # flush remaining writes and stop thread
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        max_queue_size: int = 256,
        wal: bool = True,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        init_sql: str | None = None,
    ) -> None:
        self._db_path = str(db_path)
        self._max_queue_size = max_queue_size
        self._wal = wal
        self._busy_timeout_ms = busy_timeout_ms
        self._init_sql = init_sql
        self._queue: queue.Queue[WriteOperation | None] = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

        # Track stats
        self._written: int = 0
        self._errors: int = 0
        self._last_error: str = ""

        # Auto-start the background worker
        self.start()

    # ── Public API ──────────────────────────────────────────────────────

    def submit(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
        callback: Callable[[bool, str], None] | None = None,
    ) -> bool:
        """Submit a write operation to the async queue.

        Args:
            sql: SQL statement to execute.
            params: Query parameters (tuple for positional, dict for named).
            callback: Optional ``(success, message)`` callback.

        Returns:
            ``True`` if queued, ``False`` if queue is full or writer stopped.
        """
        if self._stop_event.is_set():
            _log.warning("[ASYNC_DB] Writer stopped — rejecting write: %s", sql[:80])
            return False
        try:
            self._queue.put_nowait(
                WriteOperation(sql=sql, params=params, callback=callback)
            )
            return True
        except queue.Full:
            _log.warning("[ASYNC_DB] Queue full (%d) — dropping write: %s",
                         self._max_queue_size, sql[:80])
            return False

    def start(self) -> None:
        """Start the background worker thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker,
            name=f"async_db_{Path(self._db_path).stem}",
            daemon=True,
        )
        self._thread.start()
        _log.info("[ASYNC_DB] Writer started for %s", self._db_path)

    def stop(self, block: bool = True, timeout: float = 5.0) -> None:
        """Stop the background worker thread.

        Args:
            block: If True, waits for the queue to drain.
            timeout: Maximum seconds to wait for drain.
        """
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)  # sentinel to unblock worker
        except queue.Full:
            pass  # worker will see stop_event on next poll
        if block and self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None
        _log.info("[ASYNC_DB] Writer stopped for %s (written=%d, errors=%d)",
                  self._db_path, self._written, self._errors)

    def execute_sync(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        """Execute a synchronous read query on the writer's connection.

        Useful for read-back verification after async writes.
        Sets row_factory to sqlite3.Row so dict-style access (row["col"]) works.
        """
        conn = self._get_conn()
        try:
            conn.row_factory = sqlite3.Row
            return conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            _log.warning("[ASYNC_DB] Sync read error: %s", exc)
            return []

    @property
    def stats(self) -> dict[str, Any]:
        """Return async writer statistics."""
        return {
            "db_path": self._db_path,
            "queue_size": self._queue.qsize(),
            "max_queue_size": self._max_queue_size,
            "written": self._written,
            "errors": self._errors,
            "last_error": self._last_error,
            "is_running": self._thread is not None and self._thread.is_alive(),
        }

    # ── Internal ─────────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Lazy-init the writer's dedicated connection."""
        if self._conn is None:
            with self._lock:
                if self._conn is None:
                    self._conn = get_connection(
                        self._db_path,
                        wal=self._wal,
                        busy_timeout_ms=self._busy_timeout_ms,
                        check_same_thread=False,  # accessed from worker + execute_sync
                    )
                    # Run initialization SQL (e.g. CREATE TABLE IF NOT EXISTS)
                    # to propagate schema to this connection. This is essential
                    # for in-memory databases and ensures compatibility with
                    # existing file-based databases.
                    if self._init_sql:
                        try:
                            self._conn.executescript(self._init_sql)
                        except (sqlite3.Error, OSError, ValueError) as exc:
                            _log.warning(
                                "[ASYNC_DB] Init SQL failed: %s — SQL: %.80s",
                                exc, self._init_sql[:80],
                            )
        return self._conn

    def _worker(self) -> None:
        """Background worker: drain queue and execute writes.

        Always drains the queue before checking the stop event, so writes
        submitted just before ``stop()`` are never lost due to a race
        between the worker entering the loop and ``stop()`` setting the
        stop event.
        """
        conn = self._get_conn()
        while True:
            try:
                op: WriteOperation | None = self._queue.get(timeout=0.5)
            except queue.Empty:
                if self._stop_event.is_set():
                    break
                continue
            if op is None:
                break  # sentinel
            try:
                conn.execute(op.sql, op.params)
                conn.commit()
                self._written += 1
                if op.callback:
                    op.callback(True, "")
            except (sqlite3.Error, OSError, ValueError) as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[ASYNC_DB] Write error: %s", exc)
                if op.callback:
                    op.callback(False, str(exc))


def get_connection(
    db_path: str | Path,
    *,
    timeout: float = 3.0,
    check_same_thread: bool = False,
    row_factory: bool = True,
    wal: bool = True,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> sqlite3.Connection:
    """
    Open a SQLite connection with WAL mode and busy_timeout.

    Args:
        db_path: Path to the SQLite database file.
        timeout: Connection timeout in seconds (passed to sqlite3.connect).
        check_same_thread: Whether to allow cross-thread usage.
        row_factory: If True, sets conn.row_factory = sqlite3.Row.
        wal: If True, sets PRAGMA journal_mode=WAL (concurrent read/write).
        busy_timeout_ms: Busy timeout in milliseconds (default 5000).

    Returns:
        sqlite3.Connection configured with WAL and busy_timeout.

    Example:
        conn = get_connection("trades.db")
        rows = conn.execute("SELECT * FROM trades").fetchall()
        conn.close()
    """
    conn = sqlite3.connect(str(db_path), timeout=timeout, check_same_thread=check_same_thread)
    if row_factory:
        conn.row_factory = sqlite3.Row
    if wal:
        _enable_wal(conn)
    if busy_timeout_ms > 0:
        _set_busy_timeout(conn, busy_timeout_ms)
    return conn


def _enable_wal(conn: sqlite3.Connection) -> None:
    """Enable WAL journal mode (best-effort, logs warning on failure)."""
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except (sqlite3.Error, OSError) as exc:
        _log.warning("[DB_UTILS] Failed to enable WAL: %s", exc)


def _set_busy_timeout(conn: sqlite3.Connection, ms: int) -> None:
    """Set busy timeout (best-effort)."""
    try:
        conn.execute(f"PRAGMA busy_timeout={int(ms)}")
    except (sqlite3.Error, OSError) as exc:
        _log.warning("[DB_UTILS] Failed to set busy_timeout: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════
# Connection Pool — manages a pool of reusable SQLite connections
# ═══════════════════════════════════════════════════════════════════════════


class ConnectionPool:
    """Thread-safe pool of reusable SQLite connections.

    Manages a pool of connections to the same database, useful for
    multi-threaded access patterns where multiple workers need
    concurrent read access. Connections are configured with WAL mode
    and busy_timeout by default.

    Example:
        pool = ConnectionPool("trades.db", min_size=2, max_size=8)
        with pool.acquire() as conn:
            rows = conn.execute("SELECT * FROM trades").fetchall()
        pool.close()
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        min_size: int = 2,
        max_size: int = 8,
        wal: bool = True,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        timeout: float = 3.0,
        row_factory: bool = True,
    ) -> None:
        self._db_path = str(db_path)
        self._min_size = max(1, min_size)
        self._max_size = max(self._min_size, max_size)
        self._wal = wal
        self._busy_timeout_ms = busy_timeout_ms
        self._timeout = timeout
        self._row_factory = row_factory

        self._pool: list[sqlite3.Connection] = []
        self._in_use: set[sqlite3.Connection] = set()
        self._lock = threading.RLock()
        self._closed = False

        # Pre-allocate minimum connections
        for _ in range(self._min_size):
            conn = self._create_connection()
            self._pool.append(conn)

        _log.info(
            "[POOL] Created pool for %s (min=%d, max=%d)",
            self._db_path, self._min_size, self._max_size,
        )

    def acquire(self, timeout: float | None = None) -> sqlite3.Connection:
        """Acquire a connection from the pool.

        Args:
            timeout: Maximum time to wait for a connection. None = block indefinitely.

        Returns:
            A sqlite3.Connection from the pool.

        Raises:
            TimeoutError: If no connection becomes available within timeout.
            RuntimeError: If the pool is closed.
        """
        if self._closed:
            raise RuntimeError(f"Connection pool for {self._db_path} is closed")

        deadline = (time.monotonic() + timeout) if timeout is not None else None

        with self._lock:
            # Try to get an idle connection
            while self._pool:
                conn = self._pool.pop()
                if self._is_connection_valid(conn):
                    self._in_use.add(conn)
                    return conn
                # Connection is stale — discard and create a new one
                try:
                    conn.close()
                except (sqlite3.Error, OSError):
                    pass

            # If pool is not full, create a new connection
            if len(self._in_use) < self._max_size:
                conn = self._create_connection()
                self._in_use.add(conn)
                return conn

        # Pool is full — wait for a connection to be released
        while deadline is None or time.monotonic() < deadline:
            with self._lock:
                if self._pool:
                    conn = self._pool.pop()
                    if self._is_connection_valid(conn):
                        self._in_use.add(conn)
                        return conn
                    try:
                        conn.close()
                    except (sqlite3.Error, OSError):
                        pass

                # Check if we can grow the pool
                if len(self._in_use) < self._max_size:
                    conn = self._create_connection()
                    self._in_use.add(conn)
                    return conn

            # Brief sleep before retry
            time.sleep(0.01)

        raise TimeoutError(
            f"Pool exhausted: {len(self._in_use)}/{self._max_size} connections "
            f"in use for {self._db_path}"
        )

    def release(self, conn: sqlite3.Connection) -> None:
        """Return a connection to the pool."""
        with self._lock:
            self._in_use.discard(conn)
            if self._closed:
                # Pool is closed — close the connection to prevent leaks
                try:
                    conn.close()
                except (sqlite3.Error, OSError):
                    pass
                return
            if self._is_connection_valid(conn):
                # Rollback any pending transaction before returning
                try:
                    conn.rollback()
                except (sqlite3.Error, OSError):
                    pass
                self._pool.append(conn)

    def close(self) -> None:
        """Close the pool and all connections."""
        with self._lock:
            self._closed = True
            all_conns = list(self._pool) + list(self._in_use)
            self._pool.clear()
            self._in_use.clear()
        for conn in all_conns:
            try:
                conn.close()
            except (sqlite3.Error, OSError):
                pass
        _log.info("[POOL] Closed pool for %s", self._db_path)

    @property
    def stats(self) -> dict[str, Any]:
        """Return pool statistics."""
        with self._lock:
            return {
                "db_path": self._db_path,
                "min_size": self._min_size,
                "max_size": self._max_size,
                "idle": len(self._pool),
                "in_use": len(self._in_use),
                "total": len(self._pool) + len(self._in_use),
                "closed": self._closed,
            }

    def health_check(self) -> dict[str, Any]:
        """Check pool health."""
        with self._lock:
            idle_healthy = sum(
                1 for c in self._pool if self._is_connection_valid(c)
            )
            in_use_count = len(self._in_use)
        return {
            "status": "healthy" if not self._closed else "closed",
            "backend": "SQLite",
            "db_path": self._db_path,
            "idle_healthy": idle_healthy,
            "in_use": in_use_count,
        }

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new connection with standard settings."""
        return get_connection(
            self._db_path,
            timeout=self._timeout,
            wal=self._wal,
            busy_timeout_ms=self._busy_timeout_ms,
            row_factory=self._row_factory,
            check_same_thread=False,
        )

    @staticmethod
    def _is_connection_valid(conn: sqlite3.Connection) -> bool:
        """Check if a connection is still alive."""
        try:
            conn.execute("SELECT 1").fetchone()
            return True
        except (sqlite3.Error, OSError):
            return False


# ═══════════════════════════════════════════════════════════════════════════
# DatabasePort factory (Sprint 8 — Database Abstraction Layer)
# ═══════════════════════════════════════════════════════════════════════════


def create_database_port(
    db_path: str | Path,
    *,
    wal: bool = True,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    row_factory: bool = True,
) -> Any:
    """
    Factory: create a DatabasePort-compatible adapter for the given path.

    Currently returns a ``SQLiteDatabaseAdapter``. In the future this can
    return a PostgreSQL adapter (or other backend) based on a connection
    string scheme.

    Args:
        db_path: Path to the SQLite database file.
        wal: Enable WAL journal mode.
        busy_timeout_ms: SQLite busy timeout in milliseconds.
        row_factory: If True, results are dict-like rows.

    Returns:
        A DatabasePort implementation (currently SQLiteDatabaseAdapter).

    Example:
        from core.db_utils import create_database_port

        db = create_database_port("trades.db")
        db.connect()
        rows = db.fetchall("SELECT * FROM trades")
        db.disconnect()
    """
    from core.adapters.database import SQLiteDatabaseAdapter
    return SQLiteDatabaseAdapter(
        db_path,
        wal=wal,
        busy_timeout_ms=busy_timeout_ms,
        row_factory=row_factory,
    )


def get_connection_cached(
    db_path: str | Path,
    cache: dict[str, sqlite3.Connection],
    *,
    key: str | None = None,
    **kwargs: Any,
) -> sqlite3.Connection:
    """
    Return a cached connection if available, else create and cache one.

    Useful for modules that frequently access the same database in a
    long-running process (e.g. index_trader.py).

    Args:
        db_path: Path to the SQLite database file.
        cache: A dict to use as the connection cache (pass a module-level dict).
        key: Optional cache key (defaults to str(db_path)).
        **kwargs: Passed through to get_connection().

    Returns:
        sqlite3.Connection (cached or freshly created).

    Example:
        _conn_cache: dict[str, sqlite3.Connection] = {}
        conn = get_connection_cached("trades.db", _conn_cache)
    """
    cache_key = key or str(db_path)
    if cache_key not in cache or cache[cache_key] is None:
        cache[cache_key] = get_connection(db_path, **kwargs)
    return cache[cache_key]
