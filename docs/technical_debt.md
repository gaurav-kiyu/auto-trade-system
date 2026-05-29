# Technical Debt Register

Last Updated: 2026-05-28

## Overview
This document tracks known architectural and code-quality debt items. Each entry is
prioritized by impact severity and estimated remediation effort.

**Severity Levels:**
- **CRITICAL**: Must resolve before next minor release
- **HIGH**: Must have remediation plan within one release cycle
- **MEDIUM**: Plan within two release cycles
- **LOW**: Track for backlog grooming

**Effort Levels:**
- **XL**: >1 month of engineering time
- **L**: 2–4 weeks
- **M**: 1–2 weeks
- **S**: 2–5 days
- **XS**: <2 days

---

## CRITICAL Items

### DEBT-001: Multiple Risk Engines
| Field | Value |
|-------|-------|
| **Location** | `core/risk_engine.py`, `core/mandate_enforcer.py`, `core/services/risk_service.py` |
| **Description** | Risk logic is fragmented across ~3+ engines with overlapping responsibilities, increasing risk of inconsistent risk decisions. |
| **Impact** | CRITICAL — Capital loss from inconsistent risk enforcement |
| **Effort** | L |
| **Status** | **RESOLVED** |
| **Target** | v2.53 |
| **Notes** | ✅ `core/risk_engine.py`, `core/risk_engine_v2.py` removed. Single authoritative path: `RiskPort` → `RiskService`. `core/domains/risk/service.py` is clean-architecture variant importing models from `model.py`. Deprecation shim `core/mandate_enforcer.py` retained for backward compat. No residual imports of old engines found. |

### DEBT-002: No Exactly-Once Execution Guarantee (Legacy Code Paths)
| Field | Value |
|-------|-------|
| **Location** | `index_app/index_trader.py` (legacy execution paths) |
| **Description** | The new WAL journal and IdempotencyCertifier are in place, but legacy code paths in `index_trader.py` still call broker APIs directly without going through the idempotency layer. |
| **Impact** | CRITICAL — Duplicate order submissions |
| **Effort** | M |
| **Status** | **REFERRED** — Requires major refactor of `index_trader.py` monolith |
| **Target** | v2.54+ |
| **Notes** | `core/execution/order_manager.py` implements 3-phase submit with idempotency. Legacy paths in ~2,400-line `index_trader.py` still bypass it. WAL journal and certifier infrastructure are in place but not wired. Migration tracked in DEBT-008 (monolith extraction). |

### DEBT-003: Strategy Orchestration Fragmentation
| Field | Value |
|-------|-------|
| **Location** | `core/strategy_engine.py`, `core/scoring_engine.py`, `core/tier_engine.py`, `core/signal_router.py` |
| **Description** | Signal generation spans ~8 modules with overlapping responsibilities and inconsistent scoring. |
| **Impact** | CRITICAL — Conflicting signals, missed trades |
| **Effort** | L |
| **Status** | **RESOLVED** |
| **Target** | v2.53 |
| **Notes** | ✅ `StrategyOrchestrator` v2.0 (`core/strategy/orchestrator.py`) is canonical. `core/signal_router.py` and `core/strategy_engine_v2.py` removed. `core/signal_approval_workflow.py` and `core/strategy_engine.py` retained as backward-compat shims only. Backward-compat imports in `backtest_engine.py`, `walkforward_engine.py`, and `index_trader.py` use the deprecated shims but work correctly without warnings. |

---

## HIGH Items

### DEBT-004: No Formal Invariants Engine
| Field | Value |
|-------|-------|
| **Location** | Cross-cutting |
| **Description** | Runtime invariants (e.g., "only one risk engine active", "positions match broker") are not formally checked on heartbeat. |
| **Impact** | HIGH — Latent misconfiguration undetected |
| **Effort** | M |
| **Status** | **RESOLVED** |
| **Target** | v2.54+ |
| **Notes** | ✅ `core/invariants/engine.py` provides full check infrastructure. `core/invariants/checks.py` registers 8 checks: broker positions, single risk engine, stale data, mode gate, duplicate submissions, hard halt safety, consecutive loss, intraday P&L. Wired into EnterpriseDashboard startup and exposed at `/api/system/invariants`. |

### DEBT-005: Config Schema Not Automatically Validated at Startup
| Field | Value |
|-------|-------|
| **Location** | `core/config_bootstrap.py`, `schemas/` |
| **Description** | Config schemas exist but are not validated against actual config at startup; manual schema regeneration step is error-prone. |
| **Impact** | HIGH — Misconfiguration not caught until runtime |
| **Effort** | S |
| **Status** | **RESOLVED** |
| **Target** | v2.53 |
| **Notes** | ✅ `core/config_validator.py` provides `validate_config()` validation. `core/startup_validation.py` runs schema checks at startup. `core/config_schema_validate.py` validates against JSON schemas. |

### DEBT-006: Test Artifacts in Repository Root
| Field | Value |
|-------|-------|
| **Location** | Repository root |
| **Description** | ~1,388 test artifact databases and runtime files leaked into repo root instead of `tests/` or `data/` directories. |
| **Impact** | HIGH — Cluttered repo, risk of accidental commit of test data |
| **Effort** | M |
| **Status** | **RESOLVED** |
| **Target** | v2.53 |
| **Notes** | ✅ All test artifacts purged (~28 MB removed). `.gitignore` hardened with patterns for `test_recon_*.db`, `nonexistent_*.db`, runtime `.db` files. 0 untracked files remaining. |

### DEBT-007: No Dependency Version Pinning
| Field | Value |
|-------|-------|
| **Location** | `requirements.txt` |
| **Description** | Dependencies are not pinned to exact versions, risking inconsistent environments across deployments. |
| **Impact** | HIGH — Environment drift, untestable upgrades |
| **Effort** | S |
| **Status** | **RESOLVED** |
| **Target** | v2.53 |
| **Notes** | ✅ `requirements-lock.txt` exists with 27 pinned dependencies across core runtime, dev/CI, and optional categories. |

### DEBT-008: `index_trader.py` Monolith (2,408 lines)
| Field | Value |
|-------|-------|
| **Location** | `index_app/index_trader.py` |
| **Description** | Main trading module is a large file with 26 sections and implicit global state. (Note: original 8,200-line estimate was from a previous version; current file is ~2,408 lines after extraction of components.) |
| **Impact** | HIGH — High cognitive load, hard to test, brittle |
| **Effort** | XL |
| **Status** | ACCEPTED |
| **Target** | Ongoing |
| **Notes** | Gradual extraction via strangler fig pattern. ~2,408 lines remaining after moving services to `core/` modules. |

---

## MEDIUM Items

### DEBT-009: SQLite Concurrent Write Contention
| Field | Value |
|-------|-------|
| **Location** | All SQLite databases |
| **Description** | Multiple writer threads compete for SQLite locks; WAL mode mitigates but does not eliminate contention. |
| **Impact** | MEDIUM — Occasional write timeouts under load |
| **Effort** | M |
| **Status** | ACCEPTED |
| **Target** | v2.54 |

### DEBT-010: No CI/CD Pipeline for Production
| Field | Value |
|-------|-------|
| **Location** | `.github/workflows/` |
| **Description** | No formal GitHub Actions workflow for production releases. Current deployment is manual. |
| **Impact** | MEDIUM — Manual deployment risk |
| **Effort** | M |
| **Status** | **RESOLVED** |
| **Target** | v2.54 |
| **Notes** | ✅ `prod-release.yml` enhanced with Docker build & push (GHCR) + SSH deploy step. Full pipeline: compile → lint → test → package → Docker build → deploy. |

### DEBT-011: Test Coverage Gaps in Edge Cases
| Field | Value |
|-------|-------|
| **Location** | Various test files |
| **Description** | Core modules have unit tests, but integration/chaos tests are incomplete. |
| **Impact** | MEDIUM — Regression risk in edge cases |
| **Effort** | L |
| **Status** | IN_PROGRESS |
| **Target** | v2.54 |
| **Notes** | 3500+ tests currently pass. Stress, catastrophic, failover, and reconciliation tests all pass. |

### DEBT-012: ML Performance Tracker Schema Migration Not Versioned
| Field | Value |
|-------|-------|
| **Location** | `core/ml_performance_tracker.py` |
| **Description** | `ALTER TABLE ADD COLUMN IF NOT EXISTS` approach works but lacks formal schema versioning. |
| **Impact** | MEDIUM — Schema drift over time |
| **Effort** | S |
| **Status** | **RESOLVED** |
| **Target** | v2.54 |
| **Notes** | ✅ Migration v2 registered via `core.db_migration` for `ml_predictions` table. `_get_conn()` uses `ensure_schema_version()` with `ImportError` fallback to direct DDL. |

### DEBT-013: No Architecture Compliance CI Check
| Field | Value |
|-------|-------|
| **Location** | Cross-cutting |
| **Description** | ADR 0010 defines module boundary rules but no CI check enforces them. |
| **Impact** | MEDIUM — Architectural erosion over time |
| **Effort** | M |
| **Status** | **RESOLVED** |
| **Target** | v2.54 |
| **Notes** | ✅ `scripts/check_architecture_compliance.py` provides 5 AST-based checks: core→infra imports, strategy→broker, dead modules, canonical modules, direct broker SDK imports. Wired into `.github/workflows/ci.yml` as `architecture-compliance` step. Uses `importlib.util.find_spec` (no side effects). Exemption lists for legacy modules. |

### DEBT-014: `core.execution_engine` Deprecation
| Field | Value |
|-------|-------|
| **Location** | `core/execution_engine.py`, `core/execution_stack.py`, `core/trading_orchestrator.py` |
| **Description** | ``core.execution_engine.ExecutionEngine`` is deprecated in favour of ``core.services.execution_service.ExecutionService`` with WAL journal + state machine. However, 2 core modules still import the legacy engine directly: ``core/execution_stack.py`` and ``core/trading_orchestrator.py`` (plus 2 test files). A full migration requires refactoring these callers to use ``ExecutionService`` instead. |
| **Impact** | LOW — Deprecated module remains functional. Runtime warning emitted on each import. |
| **Effort** | M |
| **Status** | ACCEPTED |
| **Target** | v2.55 |
| **Notes** | ``ExecutionService`` (``core/services/execution_service.py``) is the canonical path. Migration involves: (1) update ``execution_stack.py`` to wrap ``ExecutionService``, (2) update ``trading_orchestrator.py`` to accept ``ExecutionService``, (3) migrate test imports. See also DEBT-002 (idempotency layer not wired).

---

## LOW Items

### DEBT-014: Redundant Logging Configuration Files
| Field | Value |
|-------|-------|
| **Location** | `logging.conf`, `logging.json` |
| **Description** | Multiple logging config files exist with overlapping settings. |
| **Impact** | LOW — Maintenance overhead |
| **Effort** | XS |
| **Status** | **RESOLVED** |
| **Target** | v2.53 |
| **Notes** | ✅ No redundant logging config files found (`logging.conf`, `logging.json`, `logging.yaml` do not exist in project). Logging is configured programmatically. |

### DEBT-015: No Auto-Generated API Documentation
| Field | Value |
|-------|-------|
| **Location** | Web dashboard / API |
| **Description** | FastAPI endpoints exist but no OpenAPI/Swagger documentation is exposed. |
| **Impact** | LOW — Developer convenience |
| **Effort** | XS |
| **Status** | **RESOLVED** |
| **Target** | v2.54 |
| **Notes** | ✅ Swagger UI at `/api/docs`, ReDoc at `/api/redoc`. OpenAPI tags metadata added. CSRF-exempted for docs paths. |

### DEBT-016: Stale Benchmark Cache Data
| Field | Value |
|-------|-------|
| **Location** | `data/benchmark_cache.json` |
| **Description** | Benchmark cache contains orphaned test entries from test runs. |
| **Impact** | LOW — Slightly bloated cache file |
| **Effort** | XS |
| **Status** | **RESOLVED** |
| **Target** | v2.53 |
| **Notes** | ✅ 106 stale `_TEST_` entries removed (from 41,957 bytes → 357 bytes). Single live entry retained. |

---

## Summary

| Severity | Count | Action Required |
|----------|-------|----------------|
| CRITICAL | 0 (3 resolved) | All resolved |
| HIGH | 1 (4 resolved) | 1 remaining: DEBT-008 (monolith) |
| MEDIUM | 3 (2 resolved) | 3 remaining: DEBT-009, DEBT-011, DEBT-013 |
| LOW | 0 (3 resolved) | All resolved |
| **Total** | **4 active** (13 resolved) | Down from 17 to 4 active items |

## Review Cycle
This register is reviewed during release planning and every month thereafter.
Items with changed status are annotated with the review date.

---

*Updated: May 28, 2026 — 13 of 17 debt items resolved. 4 active items remain.*
