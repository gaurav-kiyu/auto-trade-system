# DB Migration Governance

**Module:** `core/db_migration.py`

Schema versioning and migration management for SQLite databases. Uses `PRAGMA
user_version` for version tracking with a decorator-based migration registry.

## Architecture

```
ensure_schema_version(db_path)
    │
    ├─► _check_integrity(conn)     — PRAGMA integrity_check
    │
    └─► migrate_to_latest(conn)
           │
           └─► sorted(_SCHEMA_REGISTRY)
                  │
                  ├─► pending = [m for m if current < version <= target]
                  │
                  └─► for each migration:
                         BEGIN → apply(conn) → set_version(conn) → COMMIT
                         On error: ROLLBACK
```

## Usage

```python
from core.db_migration import ensure_schema_version, register_schema

# Apply all pending migrations to a database
version = ensure_schema_version("trades.db")

# Register a new migration
@register_schema(2, "Add expiry_date column to trades table")
def migration_v2(conn):
    conn.execute("ALTER TABLE trades ADD COLUMN expiry_date TEXT")
```

## Key Functions

| Function | Purpose |
|----------|---------|
| `register_schema(version, description)` | Decorator to register migration functions |
| `migrate_to_latest(conn)` | Apply pending migrations forward |
| `ensure_schema_version(db_path)` | Open DB, check integrity, migrate to latest |
| `get_schema_version(conn)` | Read current version from PRAGMA |
| `get_migration_log(conn_or_path)` | List all migrations with applied status |

## Safety Features

- **Order enforcement**: Migrations must be registered in ascending version order
- **Transactional**: Each migration runs in its own transaction
- **Rollback on failure**: Failed migrations are rolled back fully
- **Integrity checks**: `PRAGMA integrity_check` before migration
- **Idempotent**: Uses `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern

## Migration Patterns

```python
@register_schema(3, "Add OI snapshot columns")
def migration_v3(conn):
    try:
        conn.execute("ALTER TABLE trades ADD COLUMN oi_at_entry REAL")
    except sqlite3.OperationalError:
        pass  # Column already exists
```
