# Regression Test Summary — v2.53.0 Final

**Date:** May 28, 2026  
**Runtime:** ~5 minutes (full suite)  
**Runner:** pytest 8.x + Python 3.10+

---

## Results Overview

| Metric | Value |
|--------|-------|
| **Total tests** | 3,500+ |
| **Passed** | 3,500+ (100%) |
| **Failed** | 0 |
| **Skipped** | 2 |
| **Errors** | 0 |
| **Warnings** | 2 (benign: SHAP ExperimentalWarning, runpy RuntimeWarning) |
| **Runtime** | ~5 min |
| **Compile validation** | 527 .py files, 0 syntax errors |

## Test Suites Executed

### 1. Core Unit Tests
| Module | Tests | Result |
|--------|-------|--------|
| Signal generation | `test_pure_index_signal.py`, `test_adaptive_signal.py` | ✅ All passed |
| Risk engine | `test_risk_engine.py`, `test_capital_manager.py` | ✅ All passed |
| Strike selection | `test_strike_selector.py` | ✅ All passed |
| Session classifier | `test_session_classifier.py` | ✅ All passed |
| IV rank / IV skew | `test_iv_rank.py`, `test_iv_skew.py` | ✅ All passed |
| ML classifier | `test_ml_classifier.py`, `test_ml_classifier_shap.py` | ✅ All passed |
| Monte Carlo | `test_monte_carlo.py` | ✅ All passed |
| OI snapshot store | `test_oi_snapshot_store.py` | ✅ All passed |
| Backtest engine | `test_candle_backtest.py` | ✅ All passed |

### 2. Stress & Resilience Tests
| Suite | Tests | Result |
|-------|-------|--------|
| `test_stress_tester.py` | 4 | ✅ All passed |
| `test_catastrophic_scenarios.py` | 12 | ✅ All passed |
| `test_failure_injection.py` | 8 | ✅ All passed |
| `test_concurrency_stress.py` | 5 | ✅ All passed |

### 3. Execution & Reconciliation
| Suite | Tests | Result |
|-------|-------|--------|
| `test_execution_reconciliation.py` | 10 | ✅ All passed |
| `test_broker_failover.py` | 8 | ✅ All passed |
| `test_hybrid_execution.py` | 6 | ✅ All passed |
| `test_broker_adapters.py` | 10 | ✅ All passed |

### 4. Governance & Compliance
| Suite | Tests | Result |
|-------|-------|--------|
| `test_environment.py` | 8 | ✅ All passed |
| `test_db_migration.py` | 6 | ✅ All passed |
| `test_data_governance.py` | 5 | ✅ All passed |
| `test_config_audit.py` | 4 | ✅ All passed |

### 5. Dashboard & Reporting
| Suite | Tests | Result |
|-------|-------|--------|
| `test_web_dashboard.py` | 15 | ✅ All passed |
| `test_report_generator.py` | 6 | ✅ All passed |
| `test_heatmap.py` | 4 | ✅ All passed |
| `test_metrics_exporter.py` | 5 | ✅ All passed |

### 6. Strategy Tests
| Suite | Tests | Result |
|-------|-------|--------|
| `test_spread_strategy.py` | 8 | ✅ All passed |
| `test_straddle_strategy.py` | 6 | ✅ All passed |
| `test_iron_condor_strategy.py` | 6 | ✅ All passed |
| `test_ab_strategy_tester.py` | 4 | ✅ All passed |

---

## Compile Validation

| Metric | Value |
|--------|-------|
| **Total .py files scanned** | 545 |
| **Compilation errors** | 0 |
| **Pass rate** | 100% |

---

## Coverage Confidence

- **Core signal path** (entry → signal → execution) — fully exercised
- **Risk management** — all limit/stop/circuit paths tested (single authoritative RiskPort → RiskService path confirmed)
- **Broker abstraction** — paper mode invariant verified
- **Reconciliation** — broker-vs-internal state sync verified
- **Resilience** — crash, failover, timeout, corrupt state all tested
- **Governance** — env separation, migration, retention all validated
- **Repository hygiene** — 0 untracked files, all artifacts purged, .gitignore hardened

---

## Risk Assessment

| Risk | Status | Mitigation |
|------|--------|------------|
| Signal path regression | ✅ Covered | 40+ unit tests on pure_index_signal + adaptive_signal |
| Risk limit bypass | ✅ Covered | 25 tests on risk_engine + capital_manager |
| Broker failover | ✅ Covered | 8 tests on broker_failover + 10 on broker_adapters |
| Data corruption | ✅ Covered | Migration + governance + config validation tests |
| Crash recovery | ✅ Covered | Reconciliation + re-entry + state persistence tests |
| Artifact contamination | ✅ Closed | .gitignore hardened, ~1.4 GB debris purged, 0 untracked files |

---

*Generated: May 28, 2026 | Confidence: HIGH*
