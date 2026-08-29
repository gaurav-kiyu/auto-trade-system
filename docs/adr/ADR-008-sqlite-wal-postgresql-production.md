# ADR-008: SQLite with WAL Mode for Single-Node, PostgreSQL for Production

## Status
ACCEPTED — July 2026

## Context
The trading system needs persistent storage for execution state, event sourcing, idempotency keys, and trade journal. The storage strategy must balance:
- Development simplicity (zero-config for local development)
- Production durability (crash recovery, concurrent access)
- Scalability path (single-node → multi-node)

## Decision
**Default: SQLite with WAL mode** for single-node deployments
- All execution-layer connections use `PRAGMA journal_mode=WAL` for concurrent read/write
- `PRAGMA busy_timeout=5000` prevents `SQLITE_BUSY` errors under contention
- Connection pooling via `core/adapters/database/connection_pool.py`
- Backup via `scripts/backup_databases.py`
- Restore via `scripts/restore.py`

**Production: PostgreSQL** for multi-node deployments
- Full adapter implementation at `core/adapters/database/postgres_adapter.py`
- Docker Compose setup at `deploy/docker-compose.postgres.yml`
- Kubernetes ConfigMap at `k8s/postgres-config.yaml`
- Connection pooling with psycopg2 `ThreadedConnectionPool`
- Migration script at `scripts/migrate_to_postgresql.py`

## Consequences
- **Positive:** Zero-config local development. SQLite with WAL provides ACID compliance for single-node. PostgreSQL migration path is documented and tooled.
- **Negative:** SQLite limits to single-node write scaling. PostgreSQL migration is manual (not automated). Multi-process deployments require PostgreSQL.
- **Trade-off:** Simplicity for development (SQLite) vs. production durability (PostgreSQL). Acceptable because the migration path exists and is tested.

## Related
- `core/adapters/database/sqlite_adapter.py`
- `core/adapters/database/postgres_adapter.py`
- `core/adapters/database/connection_pool.py`
- `deploy/docker-compose.postgres.yml`
- `scripts/migrate_to_postgresql.py`
- `scripts/backup_databases.py`
