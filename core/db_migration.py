"""DB migration governance - schema versioning via PRAGMA user_version + migration registry."""

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from core.db_utils import get_connection as _get_mig_conn

__all__ = [
    "Migration",
    "ensure_schema_version",
    "get_migration_log",
    "get_schema_version",
    "log",
    "migrate_to_latest",
    "register_schema",
    "set_schema_version",
]

log = logging.getLogger(__name__)


@dataclass
class Migration:
    version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]
    rollback: Callable[[sqlite3.Connection], None] | None = None


_SCHEMA_REGISTRY: list[Migration] = []
# Separate registry for rollback functions (avoids duplicate version collisions)
_ROLLBACK_REGISTRY: dict[int, Callable[[sqlite3.Connection], None]] = {}


def register_schema(version: int, description: str) -> Callable:
    """Decorator that registers a migration function at the given schema version."""
    def decorator(func: Callable[[sqlite3.Connection], None]) -> Callable:
        _SCHEMA_REGISTRY.append(Migration(version=version, description=description, apply=func))
        return func
    return decorator


def register_rollback(version: int, description: str = "") -> Callable:
    """
    Decorator that registers a rollback function for the given schema version.

    Rollback functions undo the changes made by the corresponding forward
    migration. They are stored in a separate registry to avoid version
    collisions with forward migrations in ``_SCHEMA_REGISTRY``.

    Args:
        version: The schema version whose changes this rollback undoes.
        description: Human-readable description of the rollback.

    Example::

        @register_rollback(2, "Drop SME stocks and positions tables")
        def _rollback_v2(conn):
            conn.execute("DROP TABLE IF EXISTS sme_positions")
            conn.execute("DROP TABLE IF EXISTS sme_stocks")
    """
    def decorator(func: Callable[[sqlite3.Connection], None]) -> Callable:
        _ROLLBACK_REGISTRY[version] = func
        return func
    return decorator


def _verify_migration_order() -> None:
    """Ensure migrations are registered in ascending version order (check at startup)."""
    versions = [m.version for m in _SCHEMA_REGISTRY]
    for i in range(1, len(versions)):
        if versions[i] <= versions[i - 1]:
            raise RuntimeError(
                f"Migration version order violation: v{versions[i - 1]} followed by v{versions[i]}. "
                "Migrations must be registered in ascending version order."
            )


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Read the current schema version from PRAGMA user_version."""
    return conn.execute("PRAGMA user_version").fetchone()[0]


def set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """Write schema version to PRAGMA user_version (int-safe formatting).
    Caller is responsible for managing the transaction/commit.
    """
    conn.execute(f"PRAGMA user_version = {int(version)}")


def migrate_to_latest(conn: sqlite3.Connection, target_version: int | None = None) -> int:
    """Migrate conn forward to target_version (or latest). Returns final schema version."""
    _verify_migration_order()
    current = get_schema_version(conn)
    if target_version is None:
        target_version = max(m.version for m in _SCHEMA_REGISTRY) if _SCHEMA_REGISTRY else current

    sorted_migrations = sorted(_SCHEMA_REGISTRY, key=lambda x: x.version)
    pending = [m for m in sorted_migrations if current < m.version <= target_version]

    if pending:
        log.info("Schema migration: %d -> %s (%d step(s))", current, target_version, len(pending))

    for migration in pending:
        try:
            conn.execute("BEGIN")
            migration.apply(conn)
            set_schema_version(conn, migration.version)
            conn.commit()
            log.info("Applied migration v%d: %s", migration.version, migration.description)
        except sqlite3.Error:
            conn.rollback()
            log.error("Migration v%d failed (%s): rolling back", migration.version, migration.description)
            raise

    return get_schema_version(conn)


def get_migration_log(conn_or_path: "str | sqlite3.Connection") -> list[dict]:
    """Return list of applied migration versions for reporting.
    Accepts a sqlite3.Connection or a file path str.
    """
    if isinstance(conn_or_path, str):
        conn = _get_mig_conn(conn_or_path, row_factory=False)
        try:
            return _get_migration_log_inner(conn)
        finally:
            conn.close()
    return _get_migration_log_inner(conn_or_path)


def _get_migration_log_inner(conn: sqlite3.Connection) -> list[dict]:
    current = get_schema_version(conn)
    return [
        {"version": m.version, "description": m.description, "applied": m.version <= current}
        for m in sorted(_SCHEMA_REGISTRY, key=lambda x: x.version)
    ]


# --- Built-in migrations ---

@register_schema(1, "Track schema versions via PRAGMA user_version; no structural changes")
def _migration_v1(conn: sqlite3.Connection) -> None:
    """Baseline migration: mark version 1 for all existing tables.
    No DDL needed - all tables use CREATE TABLE IF NOT EXISTS on startup."""


@register_rollback(1, "Reset user_version to 0")
def _rollback_v1(conn: sqlite3.Connection) -> None:
    """Rollback v1: reset user_version to 0 (no structural changes to undo)."""
    pass


@register_rollback(2, "Drop SME stocks and positions tables")
def _rollback_v2(conn: sqlite3.Connection) -> None:
    """Rollback v2: drop SME domain tables and indexes."""
    conn.execute("DROP INDEX IF EXISTS idx_sme_positions_symbol")
    conn.execute("DROP INDEX IF EXISTS idx_sme_positions_open")
    conn.execute("DROP INDEX IF EXISTS idx_sme_stocks_platform")
    conn.execute("DROP INDEX IF EXISTS idx_sme_stocks_active")
    conn.execute("DROP TABLE IF EXISTS sme_positions")
    conn.execute("DROP TABLE IF EXISTS sme_stocks")


@register_schema(2, "Create SME stocks and positions tables")
def _migration_v2(conn: sqlite3.Connection) -> None:
    """Create tables for SME (Small and Medium Enterprise) equity domain."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sme_stocks (
            symbol          TEXT PRIMARY KEY,
            name            TEXT NOT NULL DEFAULT '',
            isin            TEXT NOT NULL DEFAULT '',
            sector          TEXT NOT NULL DEFAULT 'OTHER',
            platform        TEXT NOT NULL DEFAULT 'nse_emerge',
            face_value      REAL NOT NULL DEFAULT 10.0,
            last_price      REAL NOT NULL DEFAULT 0.0,
            change_pct      REAL NOT NULL DEFAULT 0.0,
            week_52_high    REAL NOT NULL DEFAULT 0.0,
            week_52_low     REAL NOT NULL DEFAULT 0.0,
            avg_volume_10d  INTEGER NOT NULL DEFAULT 0,
            avg_delivery_pct REAL NOT NULL DEFAULT 0.0,
            market_cap      REAL NOT NULL DEFAULT 0.0,
            pe_ratio        REAL NOT NULL DEFAULT 0.0,
            promoter_holding REAL NOT NULL DEFAULT 0.0,
            circuit_limit   REAL NOT NULL DEFAULT 5.0,
            min_lot_size    INTEGER NOT NULL DEFAULT 0,
            t2t_settlement  INTEGER NOT NULL DEFAULT 0,
            issue_price     REAL NOT NULL DEFAULT 0.0,
            listed_date     TEXT,
            is_active       INTEGER NOT NULL DEFAULT 1,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sme_positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL,
            quantity        INTEGER NOT NULL,
            average_price   REAL NOT NULL,
            current_price   REAL NOT NULL,
            direction       TEXT NOT NULL DEFAULT 'LONG',
            unrealized_pnl  REAL NOT NULL DEFAULT 0.0,
            realized_pnl    REAL NOT NULL DEFAULT 0.0,
            is_t2t          INTEGER NOT NULL DEFAULT 0,
            min_lot_qty     INTEGER NOT NULL DEFAULT 0,
            entry_time      TEXT NOT NULL DEFAULT (datetime('now')),
            exit_time       TEXT,
            exit_reason     TEXT,
            is_open         INTEGER NOT NULL DEFAULT 1,
            notes           TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sme_positions_symbol
        ON sme_positions(symbol)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sme_positions_open
        ON sme_positions(is_open)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sme_stocks_platform
        ON sme_stocks(platform)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sme_stocks_active
        ON sme_stocks(is_active)
    """)


@register_rollback(3, "Drop fundamental_cache table")
def _rollback_v3(conn: sqlite3.Connection) -> None:
    """Rollback v3: drop fundamental_cache table and index."""
    conn.execute("DROP INDEX IF EXISTS idx_fundamental_cache_composite")
    conn.execute("DROP TABLE IF EXISTS fundamental_cache")


@register_schema(3, "Create fundamental_cache table for equity fundamental snapshots")
def _migration_v3(conn: sqlite3.Connection) -> None:
    """Create table for caching fundamental analysis snapshots."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fundamental_cache (
            symbol          TEXT PRIMARY KEY,
            data_json       TEXT NOT NULL,
            fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
            pe_ratio        REAL DEFAULT 0.0,
            pb_ratio        REAL DEFAULT 0.0,
            market_cap      REAL DEFAULT 0.0,
            eps_ttm         REAL DEFAULT 0.0,
            dividend_yield  REAL DEFAULT 0.0,
            debt_to_equity  REAL DEFAULT 0.0,
            roe_pct         REAL DEFAULT 0.0,
            composite_score REAL DEFAULT 0.0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fundamental_cache_composite
        ON fundamental_cache(composite_score DESC)
    """)


def ensure_schema_version(db_path: str) -> int:
    """Open or create a database, check integrity, and migrate to the latest schema version.
    Returns the final schema version.
    """
    conn = _get_mig_conn(db_path, row_factory=False)
    try:
        _check_integrity(conn, db_path)
        return migrate_to_latest(conn)
    finally:
        conn.close()


def rollback_to_version(conn: sqlite3.Connection, target_version: int) -> int:
    """Rollback conn to target_version by applying rollbacks in reverse order.

    Args:
        conn: Database connection to rollback.
        target_version: Target schema version to rollback to.

    Returns:
        Final schema version after rollback.

    Raises:
        RuntimeError: If a migration has no rollback function defined.
    """
    current = get_schema_version(conn)

    if current <= target_version:
        log.info("No rollback needed: current=%d <= target=%d", current, target_version)
        return current

    # Rollbacks in reverse version order (highest first, down to target+1)
    pending_versions = sorted(
        [v for v in _ROLLBACK_REGISTRY if target_version < v <= current],
        reverse=True,
    )

    if not pending_versions:
        log.info("No rollback steps found for %d -> %d", current, target_version)
        return current

    log.info(
        "Schema rollback: %d -> %s (%d step(s))",
        current, target_version, len(pending_versions),
    )

    for version in pending_versions:
        rollback_fn = _ROLLBACK_REGISTRY[version]
        try:
            conn.execute("BEGIN")
            rollback_fn(conn)
            set_schema_version(conn, version - 1)
            conn.commit()
            log.info("Rolled back migration v%d", version)
        except sqlite3.Error:
            conn.rollback()
            log.error("Rollback of v%d failed: rolling back", version)
            raise

    return get_schema_version(conn)


def _check_integrity(conn: sqlite3.Connection, label: str = "") -> None:
    """Run PRAGMA integrity_check and log warnings on corruption."""
    try:
        result = conn.execute("PRAGMA integrity_check").fetchall()
        issues = [row[0] for row in result if row[0] != "ok"]
        if issues:
            log.warning("DB integrity issues in %s: %s", label or conn, "; ".join(issues[:5]))
        else:
            log.debug("Integrity check OK for %s", label or conn)
    except (sqlite3.Error, OSError):
        log.warning("Integrity check failed for %s", label or conn, exc_info=True)
