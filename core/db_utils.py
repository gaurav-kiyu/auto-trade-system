"""
Shared SQLite connection utilities — centralized WAL + busy_timeout.

DEBT-009 mitigation: Every SQLite connection across the codebase should
use WAL mode and a reasonable busy_timeout to prevent concurrent write
contention during live trading.

Usage:
    from core.db_utils import get_connection

    conn = get_connection("trades.db")
    # ... use conn ...
    conn.close()

All connections produced by get_connection() have:
  - PRAGMA journal_mode=WAL   (concurrent readers don't block writers)
  - PRAGMA busy_timeout=5000  (wait up to 5s instead of failing immediately)
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

DEFAULT_BUSY_TIMEOUT_MS = 5000


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
