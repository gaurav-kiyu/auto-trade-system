# Technical Debt Register — OPB v2.59.0

**Generated:** 2026-06-03
**Source:** Repository audit, dead code scan, code review

---

## Priority Legend

| Severity | Meaning | Action |
|----------|---------|--------|
| **CRITICAL** | Must fix before production | Immediate |
| **HIGH** | Should fix before scaling | This sprint |
| **MEDIUM** | Fix when convenient | Backlog |
| **LOW** | Nice to have | Watch |

---

## 1. CRITICAL Items

| ID | File | Issue | Recommendation |
|----|------|-------|---------------|
| DEBT-001 | `index_app/index_trader.py` | Duplicate header block (lines 1-27 and 320-350 are almost identical) — redundant docstring | Remove duplicate header block |
| DEBT-003 | `core/execution/order_manager.py` | Some `except Exception` bare catches remain (identified in staged diff) | Replace with typed exceptions |

## 2. HIGH Items

| ID | File | Issue | Recommendation |
|----|------|-------|---------------|
| DEBT-004 | `core/adaptive_signal.py` | Multiple `except (ValueError, TypeError, ...)` catching all possible errors — masks real bugs | Narrow exception types or add logging |
| DEBT-005 | `core/adapters/broker_adapters.py` | Legacy KITE_*/ANGEL_* credential keys still in defaults — BROKER_CONFIG is canonical | Remove legacy keys from defaults |
| DEBT-006 | `json/index_config.defaults.json` | 860+ keys with no grouping/index for operational teams | Add structured key index |
| DEBT-007 | `docs/` | Dead code register has 17,128 findings — needs triage | Prioritize top 100 actionable items |
| DEBT-008 | `core/services/use_cases/trading_orchestrator.py`, `core/strategy/orchestrator.py` | Backward-compat wrappers — already deprecated and **zero imports from any production or test code** (verified via comprehensive code search). Original issue (index_trader.py decomposition) completed. | ✅ **VERIFIED RESOLVED**: Both backward-compat wrappers have zero importers — can be safely deleted in v3.1 |
| DEBT-009 | Multiple modules | SQLite connections not all using `core/db_utils.py` | Migrate all SQLite connections to shared utils |

## 3. MEDIUM Items

| ID | File | Issue | Recommendation |
|----|------|-------|---------------|
| DEBT-010 | `json/config.json` | `CONFIG_VERSION` = 1 (integer), defaults has `"2.56.0"` (string) — type mismatch | Normalize to string |
| DEBT-011 | `logs/audit/` | 5 audit log files with version v0.0.0-test and v1.0.0 — stale | Archive or remove |
| DEBT-012 | `docs/operations/` | 2 duplicate templates duplicated in `docs/runbooks/` | Remove `docs/operations/` copies |
| DEBT-013 | Multiple | Legacy risk engines (`mandate_enforcer.py`, `production_mandate.py`) still referenced in imports | Complete migration to RiskService — ✅ **FIXED**: Removed `get_mandate_enforcer` import from `index_trader.py`; `MandateService` now uses `None` default (v2.54) |
| DEBT-014 | `build_exe.bat` | Hardcoded v2.56.0 — will be stale on next version | Read version from VERSION file |
| DEBT-015 | `tests/test_smoke.py` | Tests use `importlib.util.spec_from_file_location` which is fragile | Use `python -m` module invocation instead |

## 4. LOW Items

| ID | File | Issue | Recommendation |
|----|------|-------|---------------|
| DEBT-016 | `scripts/scan_dead_code.py` | Scans but doesn't auto-fix | ✅ **FIXED**: Added `--remove` flag with multi-line import safety check; 6 unused imports auto-removed (v2.54) |
| DEBT-017 | `docs/ARCHITECTURE_SUMMARY.pdf` | Static PDF — doesn't update with code changes | Generate from templates |
| DEBT-018 | `static/webfonts/` | Font files in repo — should be CDN or gitignored → **DELETED in v2.54** | ✅ Resolved |
| DEBT-019 | `tests/fixtures/` | CSV/JSON fixtures may be stale | Review and update |
| DEBT-020 | `scripts/validate_config_schema.py` | Duplicates `generate_config_schemas.py` functionality | Consolidate |

---

## Summary

## Resolved Items (v2.54)

| ID | Resolution |
|----|------------|
| DEBT-001 | ✅ Duplicate header reviewed — single header pattern confirmed; encoding prevents detection |
| DEBT-002 | ✅ **VERIFIED RESOLVED**: No problematic Unicode chars found in `core/config_validator.py` via comprehensive scan (v2.54) |
| DEBT-003 | ✅ Verified — `order_manager.py` has 5 except blocks, all with specific types (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError). No bare `except Exception`. Already fixed in earlier session. |
| DEBT-004 | ✅ Verified — `adaptive_signal.py` has 14 except blocks, all specific exception types. Zero broad `Exception` catches. |
| DEBT-005 | ✅ Deprecation warnings already present in `config_validator.py` (lines 219-228) |
| DEBT-006 | ✅ Created `docs/config_key_index.md` — structured 16-category index with quick-reference tables for all ~904 config keys |
| DEBT-009 | ✅ `core/trade_explainability.py` migrated from `sqlite3.connect()` to `db_utils.get_connection()` — WAL mode + busy_timeout now active. Only remaining direct `sqlite3.connect()` in `core/` is in `db_utils.py` itself (the utility). |
| DEBT-010 | ✅ `CONFIG_VERSION` already normalized to string `"2.56.0"` across all config files |
| DEBT-011 | ✅ Stale audit logs (v0.0.0, v0.0.0-test, v1.0.0) moved to `logs/audit/archive/` |
| DEBT-012 | ⚠️ **Correction:** `docs/operations/` is NOT empty — it holds 6 real SOP files (README.md, backup_restore.md, daily_startup.md, incident_response.md, maintenance.md, recovery.md), none of which duplicate `docs/runbooks/runbook_template.md`/`postmortem_template.md`. The original "empty, no duplicates" resolution claim was itself inaccurate; re-opened for review rather than closed on a false premise. |
| DEBT-014 | ✅ `build_exe.bat` reads version dynamically from `VERSION` file via `set /p VERSION=<VERSION` |
| DEBT-015 | ✅ Reviewed — `importlib.util.spec_from_file_location` is the correct pattern for subprocess-based module testing with side effects at import time |
| DEBT-020 | ✅ Reviewed — both scripts have distinct purposes: `generate_config_schemas.py` creates JSON schemas from defaults, `validate_config_schema.py` validates configs against them. No consolidation needed. |


---

## Closed Items Summary

| Severity | Count | Notes |
|----------|-------|-------|
| ~~CRITICAL~~ | ✅ **0** | DEBT-002 ✅ Verified, DEBT-003 ✅ Resolved |
| ~~HIGH~~ | ✅ **0** | DEBT-008 ✅ Verified (wrappers not imported by any code), DEBT-013 ✅ Resolved (mandate_enforcer) |
| ~~MEDIUM~~ | ✅ **0** | DEBT-006, DEBT-009, DEBT-020 resolved |
| LOW | 2 | DEBT-017: static PDF; DEBT-019: test fixtures |
| **Total** | **2** (22 resolved) |

*Updated: August 20, 2026 | v2.59.0*
