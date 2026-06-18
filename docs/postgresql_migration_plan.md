# PostgreSQL Migration Plan — Zero-Downtime Strategy

## Current State Analysis

### SQLite Databases in Use

| Database | Location | Purpose | Avg Size | Writes/day |
|----------|----------|---------|----------|------------|
| `trades.db` | Project root | Trade log, execution history | ~50 MB | 50-200 |
| `trade_journal.db` | Project root | Execution quality tracking | ~10 MB | 50-100 |
| `ml_tracker.db` | Project root | ML prediction calibration | ~5 MB | 20-50 |
| `oi_snapshots.db` | Project root | Point-in-time OI history | ~20 MB | 10-40 |
| `execution_state.db` | Project root | Durable execution state | ~1 MB | 100-500 |
| `auth.db` | `data/` | User authentication | ~0.1 MB | 1-5 |
| **Total** | | | **~86 MB** | **~500-1000** |

### SQLite Bottlenecks

| Limitation | Impact | Severity |
|------------|--------|----------|
| Single-writer (WAL allows reads during writes, but single concurrent write) | Blocks on high-frequency trade executions | **Critical** |
| No connection pooling per process | Each module opens separate conn | **High** |
| No user management/permissions | Any process can read all DBs | **Medium** |
| No replication | Single point of failure | **Critical** |
| Horizontal scaling impossible | Cannot split reads/writes across instances | **Critical** |
| Limited concurrent connections | Bottleneck for dashboard + bot + telemetry | **High** |
| No point-in-time recovery | Only latest backup | **Medium** |

---

## Target Architecture

```
┌─────────────────────────────────────────────────────┐
│                    PostgreSQL 16                      │
│                                                       │
│  opb_trades_db      opb_ml_db      opb_oi_db        │
│  ├─ trades          ├─ predictions  ├─ oi_snapshots │
│  ├─ trade_journal   ├─ drift_logs   └─ archive      │
│  ├─ execution_state └─ models                        │
│  └─ positions                                        │
│                                                       │
│  opb_auth_db       opb_telemetry_db                  │
│  ├─ users           ├─ audit_log                     │
│  ├─ sessions        ├─ metrics_history               │
│  └─ audit_log       └─ performance                   │
└─────────────────────────────────────────────────────┘
         ▲           ▲           ▲           ▲
         │           │           │           │
    ┌────┴────┐ ┌───┴───┐ ┌───┴───┐ ┌───┴────┐
    │  Bot    │ │Dashbd │ │ ML    │ │Telemetry│
    └─────────┘ └───────┘ └───────┘ └─────────┘
```

### Database Abstraction Layer

```
core/ports/database/
  __init__.py
  database_port.py         ← Abstract DatabasePort interface
  sqlite_adapter.py        ← SQLite implementation (for dev/backward compat)
  postgres_adapter.py      ← PostgreSQL implementation

core/services/persistence_service.py  ← Updated to use DatabasePort
```

---

## Phase 1: Database Abstraction Layer (Sprint 8 — 2 weeks)

### Step 1.1: Define DatabasePort Interface (1 day)

```python
# core/ports/database/database_port.py

from abc import ABC, abstractmethod
from typing import Any, Optional
from dataclasses import dataclass

@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    database: str = "opb_trades"
    user: str = "opb"
    password: str = ""
    pool_min: int = 2
    pool_max: int = 10
    timeout: int = 5

class DatabasePort(ABC):
    @abstractmethod
    def connect(self, config: DatabaseConfig) -> None: ...
    
    @abstractmethod
    def disconnect(self) -> None: ...
    
    @abstractmethod
    def execute(self, sql: str, params: tuple = ()) -> Any: ...
    
    @abstractmethod
    def execute_many(self, sql: str, params_list: list[tuple]) -> None: ...
    
    @abstractmethod
    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[dict]: ...
    
    @abstractmethod
    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]: ...
    
    @abstractmethod
    def transaction(self) -> "DatabasePort": ...
    
    @abstractmethod
    def commit(self) -> None: ...
    
    @abstractmethod
    def rollback(self) -> None: ...
    
    @abstractmethod
    def health_check(self) -> bool: ...
    
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
```

### Step 1.2: Implement SQLite Adapter (1 day)

```python
# core/ports/database/sqlite_adapter.py

class SQLiteDatabaseAdapter(DatabasePort):
    """Wraps existing core/db_utils.py functionality."""
    
    def __init__(self):
        self._conn: Optional[sqlite3.Connection] = None
        self._config: Optional[DatabaseConfig] = None
    
    def connect(self, config: DatabaseConfig) -> None:
        from core.db_utils import get_connection
        self._conn = get_connection(
            config.database + ".db",  # e.g. "opb_trades.db"
            timeout=config.timeout,
        )
    
    def execute(self, sql, params=()):
        return self._conn.execute(sql, params)
    
    def fetch_all(self, sql, params=()):
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]
    # ... etc.
```

### Step 1.3: Implement PostgreSQL Adapter (3 days)

```python
# core/ports/database/postgres_adapter.py

class PostgreSQLDatabaseAdapter(DatabasePort):
    """PostgreSQL implementation using psycopg2 connection pool."""
    
    def __init__(self):
        self._pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
        self._config: Optional[DatabaseConfig] = None
    
    def connect(self, config: DatabaseConfig) -> None:
        import psycopg2.pool
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=config.pool_min,
            maxconn=config.pool_max,
            host=config.host,
            port=config.port,
            dbname=config.database,
            user=config.user,
            password=config.password,
        )
    
    def execute(self, sql, params=()):
        conn = self._pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            return cur
        finally:
            self._pool.putconn(conn)
    
    def fetch_all(self, sql, params=()):
        cur = self.execute(sql, params)
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    # ... etc.
```

### Step 1.4: Refactor Top 10 Callers to Use Port (3 days)

Priority order (by write frequency):

| Priority | Caller | Current | Target |
|----------|--------|---------|--------|
| 1 | `core/performance_metrics.py` | Direct `sqlite3.connect()` | `DatabasePort` |
| 2 | `core/ml_performance_tracker.py` | `core/db_utils.get_connection()` | `DatabasePort` |
| 3 | `core/oi_snapshot_store.py` | `core/db_utils.get_connection()` | `DatabasePort` |
| 4 | `core/execution/durable_state.py` | Direct `sqlite3.connect()` | `DatabasePort` |
| 5 | `core/manual_signal.py` | `core/db_utils.get_connection()` | `DatabasePort` |
| 6 | `core/monte_carlo.py` | `core/db_utils.get_connection()` | `DatabasePort` |
| 7 | `core/concept_drift_detector.py` | `core/db_utils.get_connection()` | `DatabasePort` |
| 8 | `core/morning_checklist.py` | Direct `sqlite3.connect()` | `DatabasePort` |
| 9 | `core/health_checker.py` | `core/db_utils.get_connection()` | `DatabasePort` |
| 10 | `core/kelly_sizer.py` | `core/db_utils.get_connection()` | `DatabasePort` |

Refactoring pattern:
```python
# BEFORE
from core.db_utils import get_connection
conn = get_connection("trades.db")
rows = conn.execute("SELECT * FROM trades").fetchall()

# AFTER
from core.ports.database import DatabasePort, get_db
db = get_db()  # Returns the configured adapter
rows = db.fetch_all("SELECT * FROM trades")
```

### Step 1.5: Add DI Container Wiring (0.5 day)

```python
# In setup_di_container():
from core.ports.database import DatabasePort, SQLiteDatabaseAdapter, DatabaseConfig

db_config = DatabaseConfig(
    database=cfg.get("trades_db", "opb_trades"),
    host=cfg.get("postgres_host", "localhost"),
    user=cfg.get("postgres_user", "opb"),
    password=cfg.get("postgres_password", ""),
)

if cfg.get("database_adapter", "sqlite") == "postgres":
    db = PostgreSQLDatabaseAdapter()
else:
    db = SQLiteDatabaseAdapter()

db.connect(db_config)
container.register(DatabasePort, lambda: db)
```

---

## Phase 2: Migration Script (Sprint 9 — 2 weeks)

### Step 2.1: Create Schema Translation Map (1 day)

Map all SQLite schemas to PostgreSQL equivalents:

| SQLite | PostgreSQL | Notes |
|--------|------------|-------|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` | Auto-increment |
| `INTEGER` | `INTEGER` | Compatible |
| `REAL` | `DOUBLE PRECISION` | Floating point |
| `TEXT` | `TEXT` | Strings |
| `BLOB` | `BYTEA` | Binary |
| `BOOLEAN` (stored as INTEGER) | `BOOLEAN` | Native |
| `CREATE INDEX` | `CREATE INDEX` | Compatible |
| `PRAGMA journal_mode=WAL` | N/A | Built-in WAL |
| `PRAGMA busy_timeout=3000` | N/A | Configurable via `lock_timeout` |

### Step 2.2: Implement Migration Engine (2 days)

```python
# scripts/migrate_to_postgres.py

class MigrationEngine:
    """Zero-downtime SQLite → PostgreSQL migration."""
    
    def __init__(self, sqlite_paths: dict[str, str], pg_config: DatabaseConfig):
        self.sqlite_conns = {name: sqlite3.connect(p) for name, p in sqlite_paths.items()}
        self.pg = PostgreSQLDatabaseAdapter()
        self.pg.connect(pg_config)
    
    def dry_run(self) -> MigrationReport:
        """Estimate data volume and identify issues without migrating."""
        ...
    
    def migrate_schema(self) -> None:
        """Create PostgreSQL tables matching SQLite schemas."""
        for name, conn in self.sqlite_conns.items():
            schema_sql = self._extract_schema(conn)
            pg_schema = self._translate_schema(schema_sql)
            self.pg.execute(pg_schema)
    
    def migrate_data_batch(self, table: str, batch_size: int = 1000) -> int:
        """Batch-migrate data with progress tracking."""
        ...
    
    def verify_migration(self) -> VerificationReport:
        """Row-count compare + sample data verification."""
        ...
    
    def switchover(self) -> None:
        """Final switch — update config, restart services."""
        ...
```

### Step 2.3: Create Docker Compose Infrastructure (1 day)

```yaml
# docker-compose.yml additions
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: opb
      POSTGRES_PASSWORD: ${OPBUYING_PG_PASSWORD}
      POSTGRES_MULTIPLE_DATABASES: opb_trades,opb_ml,opb_oi,opb_auth
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-postgres.sql:/docker-entrypoint-initdb.d/init.sql
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U opb"]
      interval: 10s
      timeout: 5s
      retries: 5

  pgbouncer:
    image: bitnami/pgbouncer:latest
    environment:
      POSTGRESQL_HOST: postgres
      POSTGRESQL_PORT: 5432
      PGBOUNCER_DATABASES: "*"
    ports:
      - "6432:6432"
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  postgres_data:
```

### Step 2.4: Implement Zero-Downtime Strategy (3 days)

#### Strategy: Dual-Write + Cutover

```
┌────────────────────────────────────────────────────────┐
│                 Zero-Downtime Phase Plan                  │
├────────────────────────────────────────────────────────┤
│                                                          │
│  Phase 2a: Dual-Write Setup                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │  Bot App │───▶│  SQLite  │    │PostgreSQL│          │
│  │          │───▶│ (Primary)│    │ (Shadow) │          │
│  └──────────┘    └──────────┘    └──────────┘          │
│  All writes go to BOTH databases. Reads from SQLite.    │
│  PostgreSQL data validated via periodic comparison.     │
│                                                          │
│  Phase 2b: Validation                                    │
│  ┌──────────┐    ┌──────────────────┐    ┌──────────┐  │
│  │CompareJob│───▶│ Row counts match? │    │Alerts    │  │
│  └──────────┘    │ Sample data match?│    └──────────┘  │
│                  │ Performance ok?    │                  │
│                  └──────────────────┘                   │
│                                                          │
│  Phase 2c: Cutover                                       │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │  Bot App │───▶│PostgreSQL│    │  SQLite  │          │
│  │          │───▶│(Primary) │    │ (Backup) │          │
│  └──────────┘    └──────────┘    └──────────┘          │
│  Reads switch to PostgreSQL. SQLite kept as hot backup. │
│                                                          │
│  Phase 2d: Retirement                                    │
│  ┌──────────┐    ┌──────────┐                            │
│  │  Bot App │───▶│PostgreSQL│  (SQLite decommissioned)  │
│  └──────────┘    └──────────┘                            │
└────────────────────────────────────────────────────────┘
```

**Code changes for dual-write:**

```python
# core/ports/database/dual_write_adapter.py

class DualWriteDatabaseAdapter(DatabasePort):
    """Writes to both databases during migration window."""
    
    def __init__(self, primary: DatabasePort, shadow: DatabasePort):
        self._primary = primary  # SQLite during migration
        self._shadow = shadow    # PostgreSQL during migration
        self._migrated = False
    
    def execute(self, sql: str, params: tuple = ()) -> Any:
        result = self._primary.execute(sql, params)
        if self._is_write_operation(sql):
            try:
                self._shadow.execute(sql, params)
            except Exception as e:
                logger.warning(f"Shadow DB write failed (non-fatal): {e}")
        return result
    
    def switchover(self) -> None:
        """Atomically switch primary → PostgreSQL."""
        self._migrated = True
        self._primary, self._shadow = self._shadow, self._primary
    
    def _is_write_operation(self, sql: str) -> bool:
        return sql.strip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER")
        )
```

### Step 2.5: Data Verification Engine (1 day)

```python
# scripts/verify_migration.py

class MigrationVerifier:
    def verify(self, sqlite_conn, pg_adapter) -> VerificationReport:
        issues = []
        
        # 1. Table-level row count comparison
        for table in self._get_all_tables(sqlite_conn):
            sqlite_count = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            pg_count = pg_adapter.fetch_one(f"SELECT COUNT(*) FROM {table}")["count"]
            if sqlite_count != pg_count:
                issues.append(RowCountMismatch(table, sqlite_count, pg_count))
        
        # 2. Sample data hash comparison (sample 1000 rows per table)
        for table in self._get_all_tables(sqlite_conn):
            if not self._sample_verify(sqlite_conn, pg_adapter, table):
                issues.append(SampleMismatch(table))
        
        # 3. Schema equality check
        for table in self._get_all_tables(sqlite_conn):
            sqlite_schema = self._get_sqlite_schema(sqlite_conn, table)
            pg_schema = self._get_pg_schema(pg_adapter, table)
            if sqlite_schema != pg_schema:
                issues.append(SchemaMismatch(table, sqlite_schema, pg_schema))
        
        return VerificationReport(
            total_tables=len(self._get_all_tables(sqlite_conn)),
            row_count_matches=sum(1 for i in issues if not isinstance(i, RowCountMismatch)),
            issues=issues,
            passed=len(issues) == 0,
        )
```

---

## Phase 3: Connection Pooling & PgBouncer (Sprint 9 cont.)

### Step 3.1: Integrate PgBouncer (1 day)

```python
# core/ports/database/pgbouncer_adapter.py

class PgBouncerAdapter(DatabasePort):
    """Connection-pooled adapter via PgBouncer."""
    
    def __init__(self):
        self._pool = None
    
    def connect(self, config: DatabaseConfig) -> None:
        # Connect through PgBouncer port (6432)
        import psycopg2.pool
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=config.pool_min,
            maxconn=config.pool_max,
            host=config.host or "localhost",
            port=config.get("pgbouncer_port", 6432),
            dbname=config.database,
            user=config.user,
            password=config.password,
        )
```

### Step 3.2: Add Connection Health Monitoring (1 day)

```python
# core/services/database_health_service.py

class DatabaseHealthService:
    def __init__(self, db: DatabasePort):
        self._db = db
    
    def check_connection(self) -> HealthResult:
        """Test basic connectivity."""
        try:
            result = self._db.fetch_one("SELECT 1 AS ok")
            return HealthResult(healthy=True, latency_ms=result.get("latency", 0))
        except Exception as e:
            return HealthResult(healthy=False, error=str(e))
    
    def check_pool_stats(self) -> PoolStats:
        """Get connection pool utilization."""
        ...
```

---

## Phase 4: Rollback & Backup Integration (Sprint 9 cont.)

### Step 4.1: Backup Strategy

```bash
# Automated PostgreSQL backup via cron
0 */6 * * * pg_dump -U opb -h localhost opb_trades | gzip > /backups/opb_trades_$(date +\%Y\%m\%d_\%H\%M\%S).sql.gz
```

### Step 4.2: Config Backup Path

```python
# Config keys to add:
database:
  adapter: "postgres"  # or "sqlite"
  postgres:
    host: "localhost"
    port: 5432
    database: "opb_trades"
    user: "opb"
    password_env_var: "OPBUYING_PG_PASSWORD"
    pool_min: 2
    pool_max: 10
  sqlite:
    path: "trades.db"  # fallback
```

---

## Rollback Plan

### Scenario: Migration fails data verification

```python
# scripts/rollback_migration.py

class MigrationRollback:
    def rollback_to_sqlite(self) -> None:
        """Emergency rollback to SQLite."""
        # 1. Stop dual-write
        # 2. Point app back to SQLite primary
        # 3. Keep PostgreSQL data for future retry
        # 4. Notify ops team via Telegram
        config = load_config()
        config["database"]["adapter"] = "sqlite"
        save_config(config)
        send_alert("Database migration rolled back to SQLite. PostgreSQL data preserved.")
```

### Rollback Scenarios

| Scenario | Detection | Action | RTO |
|----------|-----------|--------|-----|
| Data mismatch > 0.1% | Verification report | Halt cutover, retry | 0 |
| Query performance degraded > 50% | P95 latency monitoring | Rollback to SQLite | 5 min |
| Connection pool exhaustion | Pool stats monitoring | Increase pool, or rollback | 5 min |
| Dual-write failures > 1% | Error rate monitoring | Fix adapter, retry | 15 min |

---

## Testing Strategy

| Test Type | Count | Scope |
|-----------|-------|-------|
| DatabasePort contract tests | 20 | All adapters conform to interface |
| SQLite adapter tests | 15 | Regression: existing behavior preserved |
| PostgreSQL adapter tests | 15 | PG-specific behavior |
| DualWrite adapter tests | 10 | Write propagation, error handling |
| Migration integration tests | 8 | End-to-end migration with sample data |
| Migration verification tests | 5 | Row count, sample hash, schema checks |
| Rollback tests | 5 | Emergency rollback scenarios |
| Health check tests | 5 | Connection health, pool stats |
| **Total** | **83** | |

---

## Timeline & Effort

| Phase | Tasks | Calendar Days | Engineering Days |
|-------|-------|---------------|------------------|
| 1: DB Abstraction | 1.1-1.5 | 10 | 8.5 |
| 2: Migration Script | 2.1-2.5 | 10 | 8 |
| 3: Connection Pooling | 3.1-3.2 | 3 | 2 |
| 4: Rollback & Backup | 4.1-4.2 | 2 | 1 |
| Testing | All phases | 5 | 5 |
| **Total** | | **~4 weeks** | **~24.5 engineering days** |

---

## Success Criteria

| Metric | Before (SQLite) | After (PostgreSQL) | Target |
|--------|-----------------|--------------------|--------|
| Concurrent connections | 1 | 100+ | ✅ |
| Write throughput | ~100 writes/sec | ~5,000 writes/sec | ✅ |
| Query latency (p95) | ~20ms | < 5ms (with indexes) | ✅ |
| Read latency (p95) | ~10ms | < 2ms | ✅ |
| Data loss on crash | Most recent transaction | WAL + point-in-time recovery | ✅ |
| Horizontal scaling | Impossible | Read replicas + sharding | ✅ |
| Migration verification | N/A | 100% row/sample/schema match | ✅ |
