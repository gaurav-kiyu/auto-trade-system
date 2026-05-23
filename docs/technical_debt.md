# Technical Debt Register

Last Updated: 2026-05-22

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
| **Status** | IN_PROGRESS |
| **Target** | v2.53 |
| **Notes** | `core/risk/authoritative_engine.py` removed (unnecessary wrapper); `core/risk_engine.py` deprecated; `RiskService` via `RiskPort` is canonical. Remaining legacy paths in `index_trader.py` need migration. |

### DEBT-002: No Exactly-Once Execution Guarantee (Legacy Code Paths)
| Field | Value |
|-------|-------|
| **Location** | `index_app/index_trader.py` (legacy execution paths) |
| **Description** | The new WAL journal and IdempotencyCertifier are in place, but legacy code paths in `index_trader.py` still call broker APIs directly without going through the idempotency layer. |
| **Impact** | CRITICAL — Duplicate order submissions |
| **Effort** | M |
| **Status** | IN_PROGRESS |
| **Target** | v2.53 |
| **Notes** | Migration of legacy paths is ongoing |

### DEBT-003: Strategy Orchestration Fragmentation
| Field | Value |
|-------|-------|
| **Location** | `core/strategy_engine.py`, `core/scoring_engine.py`, `core/tier_engine.py`, `core/signal_router.py` |
| **Description** | Signal generation spans ~8 modules with overlapping responsibilities and inconsistent scoring. |
| **Impact** | CRITICAL — Conflicting signals, missed trades |
| **Effort** | L |
| **Status** | IN_PROGRESS |
| **Target** | v2.53 |
| **Notes** | StrategyOrchestrator v2.0 is canonical and integrates SignalApprovalWorkflow. `core/signal_approval_workflow.py` and `core/strategy_engine.py` are deprecated. `core/signal_router.py` and `core/strategy_engine_v2.py` removed. Legacy references in `index_trader.py`, `backtest_engine.py`, `walkforward_engine.py` still import deprecated `strategy_engine`. |

---

## HIGH Items

### DEBT-004: No Formal Invariants Engine
| Field | Value |
|-------|-------|
| **Location** | Cross-cutting |
| **Description** | Runtime invariants (e.g., "only one risk engine active", "positions match broker") are not formally checked on heartbeat. |
| **Impact** | HIGH — Latent misconfiguration undetected |
| **Effort** | M |
| **Status** | PLANNED |
| **Target** | v2.53 |
| **Notes** | AD-KIYU Phase 1D |

### DEBT-005: Config Schema Not Automatically Validated at Startup
| Field | Value |
|-------|-------|
| **Location** | `core/config_bootstrap.py`, `schemas/` |
| **Description** | Config schemas exist but are not validated against actual config at startup; manual schema regeneration step is error-prone. |
| **Impact** | HIGH — Misconfiguration not caught until runtime |
| **Effort** | S |
| **Status** | IDENTIFIED |
| **Target** | v2.53 |
| **Notes** | Add `validate_config_on_startup` gating |

### DEBT-006: Test Artifacts in Repository Root
| Field | Value |
|-------|-------|
| **Location** | Repository root |
| **Description** | ~204 test artifact databases and runtime files leaked into repo root instead of `tests/` or `data/` directories. |
| **Impact** | HIGH — Cluttered repo, risk of accidental commit of test data |
| **Effort** | M |
| **Status** | PLANNED |
| **Target** | v2.53 |

### DEBT-007: No Dependency Version Pinning
| Field | Value |
|-------|-------|
| **Location** | `requirements.txt` |
| **Description** | Dependencies are not pinned to exact versions, risking inconsistent environments across deployments. |
| **Impact** | HIGH — Environment drift, untestable upgrades |
| **Effort** | S |
| **Status** | IDENTIFIED |
| **Target** | v2.53 |
| **Notes** | Generate `requirements-lock.txt` via `pip freeze` |

### DEBT-008: `index_trader.py` Monolith (~8,200 lines)
| Field | Value |
|-------|-------|
| **Location** | `index_app/index_trader.py` |
| **Description** | Main trading module is a god object with 26 sections and implicit global state. |
| **Impact** | HIGH — High cognitive load, hard to test, brittle |
| **Effort** | XL |
| **Status** | ACCEPTED |
| **Target** | Ongoing |
| **Notes** | Gradual extraction via strangler fig pattern |

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
| **Status** | PLANNED |
| **Target** | v2.54 |
| **Notes** | AD-KIYU Phase 5B |

### DEBT-011: Test Coverage Gaps in Edge Cases
| Field | Value |
|-------|-------|
| **Location** | Various test files |
| **Description** | Core modules have unit tests, but integration/chaos tests are incomplete. |
| **Impact** | MEDIUM — Regression risk in edge cases |
| **Effort** | L |
| **Status** | IN_PROGRESS |
| **Target** | v2.53 |
| **Notes** | Chaos test suite being built (Phase 6A) |

### DEBT-012: ML Performance Tracker Schema Migration Not Versioned
| Field | Value |
|-------|-------|
| **Location** | `core/ml_performance_tracker.py` |
| **Description** | `ALTER TABLE ADD COLUMN IF NOT EXISTS` approach works but lacks formal schema versioning. |
| **Impact** | MEDIUM — Schema drift over time |
| **Effort** | S |
| **Status** | IDENTIFIED |
| **Target** | v2.53 |

### DEBT-013: No Architecture Compliance CI Check
| Field | Value |
|-------|-------|
| **Location** | Cross-cutting |
| **Description** | ADR 0010 defines module boundary rules but no CI check enforces them. |
| **Impact** | MEDIUM — Architectural erosion over time |
| **Effort** | M |
| **Status** | IDENTIFIED |
| **Target** | v2.54 |

---

## LOW Items

### DEBT-014: Redundant Logging Configuration Files
| Field | Value |
|-------|-------|
| **Location** | `logging.conf`, `logging.json` |
| **Description** | Multiple logging config files exist with overlapping settings. |
| **Impact** | LOW — Maintenance overhead |
| **Effort** | XS |
| **Status** | IDENTIFIED |
| **Target** | v2.53 |

### DEBT-015: No Auto-Generated API Documentation
| Field | Value |
|-------|-------|
| **Location** | Web dashboard / API |
| **Description** | FastAPI endpoints exist but no OpenAPI/Swagger documentation is exposed. |
| **Impact** | LOW — Developer convenience |
| **Effort** | XS |
| **Status** | IDENTIFIED |
| **Target** | v2.54 |

### DEBT-016: Stale Benchmark Cache Data
| Field | Value |
|-------|-------|
| **Location** | `data/benchmark_cache.json` |
| **Description** | Benchmark cache contains orphaned test entries from test runs. |
| **Impact** | LOW — Slightly bloated cache file |
| **Effort** | XS |
| **Status** | IDENTIFIED |
| **Target** | v2.53 |

---

## Summary

| Severity | Count | Action Required |
|----------|-------|----------------|
| CRITICAL | 3 | Resolve before next minor release |
| HIGH | 5 | Remediation plan within one release |
| MEDIUM | 5 | Plan within two releases |
| LOW | 3 | Backlog grooming |
| **Total** | **16** | |

## Review Cycle
This register is reviewed during release planning and every month thereafter.
Items with changed status are annotated with the review date.
