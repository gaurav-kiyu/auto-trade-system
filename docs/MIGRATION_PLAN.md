# Migration Plan — OPB Institutional Platform v2.53.0

**Generated:** 2026-06-20  
**Classification:** INTERNAL — Operations

---

## 1. Scope

This migration plan covers:

| Migration Type | Scope | Risk Level |
|---------------|-------|------------|
| **v2.52 → v2.53** | Config schema, governance modules, DI container | MEDIUM |
| **Paper → Live** | Broker adapter switch, capital deployment | HIGH |
| **Monolith → Domain Services** | Architecture decomposition (DEBT-008) | HIGH |
| **SQLite → PostgreSQL** | Database migration for >₹25L scale | HIGH |
| **Single-user → Multi-tenant** | Authentication, session management | MEDIUM |
| **On-premise → Cloud** | Infrastructure migration | MEDIUM |
| **Config schema upgrade** | Adding/removing config keys | LOW |

---

## 2. Migration Principles

1. **Data preservation** — No data loss in any migration step
2. **Rollback ready** — Every migration has a tested rollback path
3. **Staged rollout** — Migrate in phases, validate at each phase
4. **Minimal downtime** — Target <5 min for config/version migrations
5. **Audit trail** — Every migration is logged to the audit engine

---

## 3. v2.52 → v2.53 Migration

### 3.1 Pre-requisites
- [ ] All ~2,670 tests passing
- [ ] Paper trading running for minimum 7 days
- [ ] Configuration schema validated (`python scripts/validate_config_schema.py`)
- [ ] Backup of all databases: `trades.db`, `trader_state.json`

### 3.2 Migration Steps

| Step | Action | Duration | Validation |
|------|--------|----------|------------|
| 1 | Pull latest code from `release/v2.53.0` | 1 min | `git log --oneline -1` |
| 2 | Install updated dependencies | 2 min | `pip install -r requirements.txt -r requirements-dev.txt` |
| 3 | Run config schema migration | 1 min | `python scripts/generate_config_schemas.py` |
| 4 | Validate config against new schema | 1 min | `python scripts/validate_config_schema.py` |
| 5 | Run test suite | 5 min | `python -m pytest tests/ -q` (all pass) |
| 6 | Start in paper mode | 2 min | `python index_app/index_trader.py --paper` |
| 7 | Verify signal generation | 1 cycle | Signals appear in log/Telegram |
| 8 | Confirm no collection errors | 1 min | `python -m pytest tests/ --collect-only -q` |
| 9 | **Deploy to live** | 1 min | `python index_app/index_trader.py` |

### 3.3 Rollback (v2.53 → v2.52)
```bash
git stash  # save any local changes
git checkout release/v2.52.0
pip install -r requirements.txt
python index_app/index_trader.py --paper  # verify first
```

### 3.4 Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Config schema mismatch | LOW | HIGH | Run schema validation pre-deploy |
| New config keys missing | LOW | MEDIUM | Defaults in `index_config.defaults.json` |
| Test regression | MEDIUM | MEDIUM | Full test suite pass required |
| Paper mode invariant broken | LOW | CRITICAL | Verify `PAPER_MODE=True` never reaches broker |

---

## 4. Paper → Live Migration

### 4.1 Qualification Gates

The Live Readiness Checker certifies this transition:

| Gate | Criteria | Evidence |
|------|----------|----------|
| Paper trading duration | ≥30 days of continuous paper trading | `live_readiness_checker.py` output |
| Trade count | ≥100 paper trades executed | `trades.db` |
| Win rate | ≥45% | Performance metrics |
| Configuration | No placeholder secrets | `SECRETS_MIGRATION_GUIDE.md` |
| Risk controls | No risk bypass incidents | Audit log |
| Test suite | 100% pass rate | `python -m pytest tests/ -q` |

### 4.2 Migration Steps

| Step | Action | Validation |
|------|--------|------------|
| 1 | Run `python -m core.live_readiness_checker` | Returns `ready: true` |
| 2 | Update config: set `EXECUTION_MODE: PAPER` → `LIVE` | Config validated |
| 3 | Configure broker API credentials as environment variables | `OPBUYING_*` vars set |
| 4 | Start with `--paper` initially to verify data flow | 1-day verification |
| 5 | Remove `--paper` flag | Monitor first 10 trades |
| 6 | Run reconciliation after first trade | `_broker_truth_reconciler` runs |
| 7 | Enable Telegram alerts | `BOT_TOKEN` and `CHAT_ID` configured |
| 8 | Monitor for 1 week at reduced position size (50%) | — |

### 4.3 Rollback
```bash
# Immediate fallback: restart with --paper flag
python index_app/index_trader.py --paper --debug
# All open live positions should be squared off manually
```

### 4.4 Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Broker API auth failure | MEDIUM | HIGH | Pre-open token validation (v2.53) |
| Order placement failure | MEDIUM | MEDIUM | Circuit breaker + retry policy |
| Slippage higher than paper | HIGH | MEDIUM | Slippage auto-calibration active |
| Duplicate order on restart | LOW | CRITICAL | Idempotency manager + WAL journal |

---

## 5. Monolith → Domain Services Migration (DEBT-008)

### 5.1 Target Architecture
```
index_app/
├── domains/
│   ├── config/        ← ConfigLoader, ConfigManager (✅ extracted)
│   ├── broker/        ← BrokerFactory (✅ extracted)
│   ├── market/        ← Data fetching, holidays (✅ extracted)
│   ├── trading/       ← TradingLoopService, PositionService interface (✅ extracted)
│   └── admin/         ← Control plane (✅ extracted)
```

### 5.2 Remaining Extraction Candidates (v3.0)

| Module | Current Location | Extraction Priority | Dependencies |
|--------|-----------------|---------------------|--------------|
| Signal generation | `index_trader.py` | HIGH | `SignalService`, `adaptive_signal.py` |
| Position monitoring | `index_trader.py` | HIGH | `PositionService` |
| Telegram formatting | `index_trader.py` | MEDIUM | No external deps |
| Dashboard rendering | `index_trader.py` | MEDIUM | `TraderDesk` |
| Config application | `index_trader.py` | LOW | `ConfigManager` |

### 5.3 Migration Pattern
```python
# Before (monolith):
def some_function():
    global S, positions, _state_lock
    do_work(S, positions)
    return result

# After (domain service):
from index_app.domains.trading.service import TradingService

def some_function(service: TradingService):
    return service.do_work()
```

---

## 6. SQLite → PostgreSQL Migration (₹25L+ Scale)

### 6.1 Pre-requisites
- [ ] PostgreSQL 14+ server running
- [ ] `asyncpg` or `psycopg2` installed
- [ ] Database `opb_trading` created
- [ ] Schema migration script ready

### 6.2 Migration Steps

| Step | Action | Downtime |
|------|--------|----------|
| 1 | Export SQLite data | 0 (read-only) |
| 2 | Create PostgreSQL schema | 0 |
| 3 | Import data to PostgreSQL | 0 |
| 4 | Validate data integrity (row count, checksums) | 0 |
| 5 | Switch config to PostgreSQL adapter | ~1 min |
| 6 | Verify writes | ~1 min |
| 7 | Keep SQLite as read-only fallback | 0 |

### 6.3 Schema Mapping
```sql
-- trades.db → PostgreSQL
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    exit_price DOUBLE PRECISION,
    quantity INTEGER NOT NULL,
    pnl DOUBLE PRECISION,
    entry_time TIMESTAMP NOT NULL,
    exit_time TIMESTAMP,
    strategy VARCHAR(50),
    regime_at_entry VARCHAR(20),
    session_at_entry VARCHAR(20),
    tags TEXT[]
);
```

---

## 7. Config Schema Upgrade

### 7.1 Adding a New Config Key
```python
# 1. Add default to index_config.defaults.json
{"NEW_FEATURE_ENABLED": false}

# 2. Regenerate schema
python scripts/generate_config_schemas.py

# 3. Use in code with safe default
enabled = cfg.get("NEW_FEATURE_ENABLED", False)
```

### 7.2 Removing a Config Key
```python
# 1. Add deprecation warning (2 versions before removal)
if "OLD_KEY" in cfg:
    log.warning("OLD_KEY is deprecated and will be removed in v2.55")

# 2. After 2 versions, remove from defaults + schema
# 3. Remove from code
```

---

## 8. Environment Migration

### 8.1 On-Premise → Cloud

| Phase | Action | Duration |
|-------|--------|----------|
| 1 | Containerize with Docker | 1 day |
| 2 | Set up CI/CD pipeline (Bitbucket Pipelines) | 1 day |
| 3 | Deploy to staging (Docker Compose) | 0.5 day |
| 4 | Run paper trading on cloud for 7 days | 7 days |
| 5 | Switch production traffic | 1 hour |

### 8.2 Docker Migration
```bash
# Build and verify locally
docker compose build
docker compose up -d
docker compose logs -f opb

# Deploy to production
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## 9. Migration Validation Checklist

| Phase | Check | Command/Evidence |
|-------|-------|------------------|
| **Pre-migration** | All tests pass | `python -m pytest tests/ -q` |
| | Config schema valid | `python scripts/validate_config_schema.py` |
| | Databases backed up | `copy trades.db trades.db.bak` |
| | Paper mode verified | `python index_app/index_trader.py --paper` |
| **Post-migration** | Signal generation OK | Log shows signals |
| | Trade entry works | Test trade in paper mode |
| | Telegram notifications OK | Message received |
| | Risk controls active | `python -m core.live_readiness_checker` |
| | Reconciliation OK | `python -m pytest tests/test_reconciliation_engine.py` |
| **Rollback ready** | Previous version tagged | `git tag v2.52.0-pre-migration` |
| | Database backup exists | `trades.db.bak` |

---

## 10. Appendix: Migration-Specific Config Keys

| Key | Migration | Purpose |
|-----|-----------|---------|
| `DB_MIGRATION_ENABLED` | v2.52→v2.53 | Enable schema auto-migration |
| `ENVIRONMENT` | All | Block production startup with placeholder config |
| `EXECUTION_MODE` | Paper→Live | Switch between PAPER/LIVE/SHADOW |
| `CONFIG_STRICT_SCHEMA_ENFORCEMENT` | v2.52→v2.53 | Fail fast on config schema violation |
| `POSTGRES_DSN` | SQLite→PostgreSQL | PostgreSQL connection string |

---

*Review this migration plan before every environment transition. All migrations must be tested in paper/staging before live deployment.*
