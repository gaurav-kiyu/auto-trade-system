"""DB migration governance — schema versioning via PRAGMA user_version + migration registry."""

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from core.db_utils import get_connection as _get_mig_conn

log = logging.getLogger(__name__)


@dataclass
class Migration:
    version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


_SCHEMA_REGISTRY: list[Migration] = []


def register_schema(version: int, description: str) -> Callable:
    """Decorator that registers a migration function at the given schema version."""
    def decorator(func: Callable[[sqlite3.Connection], None]) -> Callable:
        _SCHEMA_REGISTRY.append(Migration(version=version, description=description, apply=func))
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
        conn = _get_mig_conn(conn_or_path, row_factory=False)  # noqa: F811
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
    No DDL needed — all tables use CREATE TABLE IF NOT EXISTS on startup."""


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
