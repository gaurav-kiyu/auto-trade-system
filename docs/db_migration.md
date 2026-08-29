# `core/db_migration.py` — Database Migration Governance

## What it does

Schema versioning for SQLite databases via `PRAGMA user_version`, plus a
forward-migration and rollback registry. This is the mechanism CLAUDE.md's
module convention refers to when it says new SQLite tables should use
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` with `OperationalError` catch —
`db_migration.py` is for structural, versioned schema changes beyond that
(new tables, indexes) that need ordered, idempotent, rollback-capable
application.

## Core flow

1. Migrations are registered with `@register_schema(version, description)`
   as a decorator on a function `(conn: sqlite3.Connection) -> None`.
   Registration is idempotent — re-registering the same version replaces it
   in place, so repeated module imports/reloads (e.g. in tests) don't trip
   the ascending-order check.
2. `migrate_to_latest(conn, target_version=None)` verifies migrations are
   registered in strictly ascending version order, then applies each
   pending migration (`current_version < m.version <= target_version`) in
   its own transaction — on any `sqlite3.Error`, that migration's
   transaction rolls back and the exception propagates (fail loud, not
   silent).
3. `ensure_schema_version(db_path)` is the typical entry point: opens/creates
   the DB, runs `PRAGMA integrity_check` (logs, doesn't raise, on corruption),
   then calls `migrate_to_latest()`.

## Rollback

`@register_rollback(version, description)` registers a separate function
that undoes a specific version's changes. `rollback_to_version(conn, target)`
applies registered rollbacks in reverse version order down to `target`,
each in its own transaction. Raises if a version in the rollback range has
no registered rollback function.

## Built-in migrations (as of this doc)

| Version | Description |
|---|---|
| 1 | Baseline — mark version 1, no structural changes (all tables already use `CREATE TABLE IF NOT EXISTS`) |
| 2 | Create `sme_stocks`/`sme_positions` tables + indexes (SME equity domain) |
| 3 | Create `fundamental_cache` table + index |

## Public API

`Migration`, `register_schema()`, `get_schema_version()`,
`set_schema_version()`, `migrate_to_latest()`, `get_migration_log()`,
`ensure_schema_version()` — see `__all__`. (`register_rollback()` and
`rollback_to_version()` are real and used internally but not currently
re-exported in `__all__`.)

## Config keys

`db_migration_enabled` — gates whether automatic schema migration runs on
startup (see CLAUDE.md's "Governance Config Keys" section).

## Tests

`tests/test_db_migration.py`.
