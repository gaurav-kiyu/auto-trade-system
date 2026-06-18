# Sprint-by-Sprint Implementation Roadmap

## Target: OPB v3.0 — Institutional-Grade Capital Market Super-Application

**Current Version:** 2.53.0  
**Target Version:** 3.0.0  
**Estimated Duration:** 12-14 sprints (4-5 months)  
**Current Score:** 7.6/10 — **Target:** 9.9/10

---

## Phase 0: Foundation & Quick Wins (Sprint 1-2)

### Sprint 1 — Critical Technical Debt (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Fix Unicode em-dash characters across all source files | C3 | 0.5 day | Dev |
| Fix `CONFIG_VERSION` type mismatch (int → string) | C4 | 0.5 day | Dev |
| Remove duplicate header block in `index_trader.py` | DEBT-001 | 0.5 day | Dev |
| Replace bare `except Exception` with typed exceptions in `order_manager.py` | C2 | 1 day | Dev |
| Remove deprecated `signal_engine.py` and `telegram_engine.py` | L1 | 0.5 day | Dev |
| Add `.env` and `config.local.json` to `.gitignore` | Hygiene | 0.5 day | DevOps |
| Archive stale audit logs (v0.0.0-test, v1.0.0) | DEBT-011 | 0.5 day | DevOps |
| **Total** | | **4 days** | |

**Validation:** `pytest tests/ -q — 100% pass` | `ruff check .` | `scripts/hygiene_check.py`

### Sprint 2 — Dead Code Triage + Monolith Prep (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Triage top 500 dead code findings from 17,128 — remove obvious dead code | H1 | 3 days | Dev |
| Consolidate duplicate `docs/operations/` → `docs/runbooks/` | DEBT-012 | 1 day | Dev |
| Replace all SQLite connections not using `core/db_utils.py` | DEBT-009 | 1 day | Dev |
| Consolidate legacy risk engines into RiskService | DEBT-013 | 2 days | Dev |
| Consolidate `validate_config_schema.py` → merge | DEBT-020 | 0.5 day | Dev |
| Create module dependency graph for index_trader.py decomposition | Prep | 1 day | Architect |
| **Total** | | **8.5 days** | |

**Validation:** `pytest tests/ -q` | `python scripts/scan_dead_code.py` (verify reduction)

---

## Phase 1: Architecture Decomposition (Sprint 3-5)

### Sprint 3 — Extract Signal Domain Service (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Identify and catalog all signal-related code in index_trader.py (~1,200 lines) | M1 | 1 day | Architect |
| Create `core/signal/` package with `__init__.py`, `generator.py`, `scorer.py`, `validator.py` | M2 | 2 days | Dev |
| Extract `_generate_trading_signal()` → `SignalService.generate()` | M3 | 1 day | Dev |
| Extract signal quality reporting → `SignalService` | M4 | 0.5 day | Dev |
| Wire new SignalService via DI container | M5 | 0.5 day | Dev |
| Write unit tests for SignalService | M6 | 2 days | QA |
| **Total** | | **7 days** | |

**Validation:** `pytest tests/test_signal*.py -q` | Verify index_trader.py reduced by ~1,000 lines

### Sprint 4 — Extract Risk Domain Service (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Identify risk-related code in index_trader.py (~800 lines) | M7 | 0.5 day | Architect |
| Create `core/risk/` consolidated package | M8 | 1 day | Dev |
| Extract `get_position_size()`, `_check_hard_stops_via_risk()` → RiskService | M9 | 2 days | Dev |
| Consolidate legacy mandate enforcer | M10 | 1 day | Dev |
| Wire RiskService via DI container | M11 | 0.5 day | Dev |
| Write integration tests | M12 | 1 day | QA |
| **Total** | | **6 days** | |

**Validation:** `pytest tests/test_risk*.py tests/test_mandate*.py -q`

### Sprint 5 — Extract Execution Domain Service (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Identify execution-related code in index_trader.py (~1,500 lines) | M13 | 1 day | Architect |
| Create `core/execution/` unified package entry points | M14 | 1 day | Dev |
| Extract `enter_trade()`, `_exit_position()`, `_monitor_positions()` | M15 | 3 days | Dev |
| Wire via DI container + remove direct broker calls | M16 | 1 day | Dev |
| Write integration tests | M17 | 2 days | QA |
| **Total** | | **8 days** | |

**Validation:** `pytest tests/test_execution*.py tests/test_exit_*.py -q`

---

## Phase 2: Asset Class Expansion (Sprint 6-7)

### Sprint 6 — ETF + REIT + InvIT Domains (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Add ETF domain model based on FO pattern | H2a | 1 day | Dev |
| Add REIT domain model | H2b | 1 day | Dev |
| Add InvIT domain model | H2c | 1 day | Dev |
| Add SME stock domain model | H2d | 1 day | Dev |
| Add corresponding DB schemas + migrations | H2e | 1 day | Dev |
| Integrate into MultiAssetPortfolioAggregator | H2f | 1 day | Dev |
| Write domain tests (12 test files × 10 tests each) | H2g | 2 days | QA |
| **Total** | | **8 days** | |

**Validation:** `pytest tests/test_domain*.py -q` (confirm 50+ new tests pass)

### Sprint 7 — Fundamental Analysis Engine (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Research data sources for Indian fundamental data | H6a | 1 day | Research |
| Implement `core/fundamental_analyzer.py` — P/E, P/B, EPS, D/Y | H6b | 3 days | Dev |
| Add screener API integration (Screener.in / Tijori Finance) | H6c | 2 days | Dev |
| Add company financials data model + DB schema | H6d | 1 day | Dev |
| Integrate into dashboard as new card | H6e | 1 day | Dev |
| Write tests for fundamental engine | H6f | 2 days | QA |
| **Total** | | **10 days** | |

**Validation:** `pytest tests/test_fundamental*.py -q` | Manual dashboard verification

---

## Phase 3: Scalability & Infrastructure (Sprint 8-10)

### Sprint 8 — Database Abstraction Layer (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Create abstract `DatabasePort` in `core/ports/database/` | H3a | 2 days | Architect |
| Implement `SQLiteDatabaseAdapter` wrapping existing `db_utils.py` | H3b | 1 day | Dev |
| Refactor top 10 callers to use `DatabasePort` interface | H3c | 3 days | Dev |
| Add connection pooling support to `DatabasePort` | H3d | 2 days | Dev |
| Migrate all `sqlite3` imports to use adapter | H3e | 2 days | Dev |
| Write port contract tests (8 test files) | H3f | 2 days | QA |
| **Total** | | **12 days** | |

**Validation:** `pytest tests/ -q` | Verify zero direct `sqlite3.connect()` calls remain

### Sprint 9 — PostgreSQL Migration (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Implement `PostgreSQLDatabaseAdapter` | H3g | 3 days | Dev |
| Create migration script (`scripts/migrate_sqlite_to_postgres.py`) | H3h | 2 days | Dev |
| Add Docker Compose `db` service (PostgreSQL 16) | H3i | 1 day | DevOps |
| Add connection pooling (pgbouncer) | H3j | 1 day | DevOps |
| Implement zero-downtime migration strategy | H3k | 3 days | Dev |
| Add health checks for PostgreSQL | H3l | 1 day | Dev |
| Write adapter tests | H3m | 2 days | QA |
| **Total** | | **13 days** | |

**Validation:** `pytest tests/test_database*.py -q` | End-to-end migration dry run

### Sprint 10 — CQRS + Event Sourcing (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Design event schema for trade lifecycle events | M4a | 2 days | Architect |
| Implement `core/events/` event bus with pub/sub | M4b | 3 days | Dev |
| Implement read model projections (async DB sync) | M4c | 2 days | Dev |
| Add event store table (SQLite + PostgreSQL) | M4d | 1 day | Dev |
| Wire CQRS for trades (write: events → event store, read: projections) | M4e | 3 days | Dev |
| Write CQRS tests | M4f | 2 days | QA |
| **Total** | | **13 days** | |

**Validation:** `pytest tests/test_event_system*.py -q` | Verify read/write path separation

---

## Phase 4: Analytics & Intelligence (Sprint 11-12)

### Sprint 11 — Factor Models + Charting (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Implement Fama-French 3-factor model | M3a | 2 days | Quant |
| Implement momentum factor analysis | M3b | 1 day | Quant |
| Add risk factor attribution to P&L reports | M3c | 1 day | Dev |
| Integrate lightweight charting library (Lightweight Charts) | M3d | 2 days | FE |
| Add dashboard chart widgets | M3e | 2 days | FE |
| Write factor model tests | M3f | 1 day | QA |
| **Total** | | **9 days** | |

**Validation:** `pytest tests/test_factor*.py -q` | Dashboard chart rendering verified

### Sprint 12 — IPO/Corporate Actions + Final Integration (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Implement IPO data module (NSE/BSE IPO API) | H5a | 2 days | Dev |
| Implement FPO/OFS/QIP tracking | H5b | 2 days | Dev |
| Add IPO calendar dashboard widget | H5c | 1 day | FE |
| Final end-to-end integration testing | M5a | 3 days | QA |
| Performance benchmarking (load test, throughput) | M1a | 2 days | QA |
| Security penetration testing | M1b | 2 days | Security |
| **Total** | | **12 days** | |

**Validation:** Full regression suite | Performance benchmarks meet SLAs | Security scan clean

---

## Phase 5: Polish & Release (Sprint 13-14)

### Sprint 13 — Performance Optimization + Load Testing (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Profile critical paths (signal generation, execution, reconciliation) | P1 | 2 days | Architect |
| Optimize hot loops and DB queries | P2 | 3 days | Dev |
| Add connection pooling for all DB operations | P3 | 2 days | Dev |
| Implement response caching for dashboard APIs | P4 | 1 day | Dev |
| Load test: 100 concurrent sessions, 10K trades/hour | P5 | 2 days | QA |
| Tune PostgreSQL (indexes, query plans, vacuum) | P6 | 2 days | DBA |
| **Total** | | **12 days** | |

### Sprint 14 — Final Release + Documentation (2 weeks)

| Task | ID | Effort | Owner |
|------|----|--------|-------|
| Update all documentation to reflect changes | D1 | 3 days | Tech Writer |
| Generate architecture diagrams (updated) | D2 | 2 days | Architect |
| Update RELEASE_NOTES.md + CHANGELOG.md | D3 | 1 day | Dev |
| Run full certification suite (15 certification reports) | D4 | 2 days | QA |
| Final governance score validation | D5 | 1 day | Governance |
| Create v3.0 release artifacts | D6 | 1 day | DevOps |
| **Total** | | **10 days** | |

---

## Effort Summary

| Phase | Sprints | Calendar Days | Engineering Days |
|-------|---------|---------------|------------------|
| Phase 0: Foundation | 1-2 | 4 weeks | 12.5 |
| Phase 1: Architecture | 3-5 | 6 weeks | 21 |
| Phase 2: Asset Expansion | 6-7 | 4 weeks | 18 |
| Phase 3: Scalability | 8-10 | 6 weeks | 38 |
| Phase 4: Analytics | 11-12 | 4 weeks | 21 |
| Phase 5: Polish | 13-14 | 4 weeks | 22 |
| **Total** | **14 sprints** | **~28 weeks** | **~132.5 engineering days** |

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| PostgreSQL migration data loss | Low | Critical | Rollback script, dual-write during migration window |
| Domain decomposition breaks existing behavior | Medium | High | Feature flags for each extraction, A/B comparison mode |
| Dead code triage removes something still referenced | Medium | Medium | CI pipeline catches missing imports; remove only if test suite passes |
| Third-party API changes (NSE, broker) | Medium | High | Adapter pattern already in place; add integration tests with mocks |
| Team capacity insufficient for parallel tracks | High | Medium | Phase dependencies allow sequential execution; critical path is ~16 weeks |

---

## Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| index_trader.py lines | ~8,200 | < 500 |
| Test count | ~2,670 | > 3,500 |
| Test pass rate | ~99% | 100% |
| Asset classes covered | 6 of 13 | 13 of 13 |
| API response time (p95) | ~200ms | < 50ms |
| Concurrent sessions | 1 (SQLite) | 100+ (PostgreSQL) |
| Dead code findings | 17,128 | < 1,000 |
| Governance score | ~7.6/10 | ≥ 9.9/10 |
