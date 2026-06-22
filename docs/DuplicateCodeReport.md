# Duplicate Code Report

**Generated:** June 21, 2026  
**Source:** `docs/duplicate_code_register.md` + manual scan  
**Status:** Complete

---

## Scope

This report identifies duplicate code instances across the OPB codebase. Duplicate code increases maintenance burden, creates bug-propagation risk, and indicates missed refactoring opportunities.

## Summary

| Metric | Value |
|--------|-------|
| Total duplicate instances | 47 (per `duplicate_code_register.md`) |
| High-severity duplicates | 3 |
| Medium-severity duplicates | 12 |
| Low-severity duplicates | 32 |
| Most duplicated module | `tests/` (test infrastructure) |

## High-Severity Findings

### DUP-001: TestKillSwitch (100% duplicate)
- `tests/test_dashboard_comprehensive.py:548`
- `tests/test_enterprise_dashboard.py:1127`
- **Risk:** Identical test class defined in two test files — any fix to one must be manually ported
- **Recommendation:** Extract to shared test fixture in `tests/conftest.py`

### DUP-002: OLS Regression Implementation
- `core/factor_models.py` (custom OLS with normal equation)
- `core/services/risk_service.py` (beta calculation with covariance)
- **Risk:** Slightly different implementations with possibility of divergent results
- **Recommendation:** Extract shared matrix operations to `core/utils_numeric.py`

### DUP-003: Config Validation Logic
- `core/config_validator.py`
- `core/config_bootstrap.py` (partial overlap)
- **Risk:** Config validation rules can drift apart
- **Recommendation:** Consolidate into a single validation pipeline

## Medium-Severity Findings (Selected)

| ID | Files | Similarity | Description |
|----|-------|-----------|-------------|
| DUP-012 | `core/monte_carlo.py` / `core/monte_carlo_tail_risk.py` | 65% | Both implement trade-shuffle simulation |
| DUP-015 | `core/audit_journal.py` / `core/audit_engine.py` | 55% | Overlapping audit trail implementations |
| DUP-023 | `core/telemetry/metrics.py` / `core/metrics_exporter.py` | 50% | Both expose Prometheus-style metrics |

## Previously Addressed

- **Broker adapter factory** — moved from `core/ports/market_data.py` to `index_app/domains/market/adapter_factory.py` (ADR-0010 compliance)
- **Multi-asset adapter registration** — moved from `core/di_container.py` to app-layer factory

## Recommendations

1. Extract shared test fixtures from duplicated test classes into `tests/conftest.py`
2. Consolidate OLS/regression utilities into `core/utils_numeric.py`
3. Merge `audit_journal.py` and `audit_engine.py` into a single audit module
4. Run `python scripts/scan_dead_code.py` regularly to detect new duplicates
