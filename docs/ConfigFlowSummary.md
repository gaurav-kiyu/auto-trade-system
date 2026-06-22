# Configuration Flow Summary

**Generated:** June 21, 2026  
**Status:** Complete

---

## Config Layer Architecture

```
index_config.defaults.json  (single source of truth — ~860 keys)
        ↓
config.json                 (user overrides — partial)
        ↓
config.local.json           (local overrides — gitignored)
        ↓
OPBUYING_* env vars         (runtime overrides — secrets)
        ↓
Merged Config (runtime dict)
```

## Merge Priority (highest wins)

1. `OPBUYING_*` environment variables (highest priority)
2. `config.local.json` (local overrides, gitignored)
3. `config.json` (shared user overrides)
4. `index_config.defaults.json` (lowest priority — provides safe defaults)

## Config Validation

- `core/config_bootstrap.py` — merges the 4 layers
- `core/config_validator.py` — validates merged config structure
- `core/config_schema_validate.py` — schema-level validation
- `scripts/generate_config_schemas.py` — regenerates JSON schemas from defaults

## Audit Trail

- All config changes are logged to `config_audit.jsonl`
- Three severity levels: CRITICAL / HIGH / NORMAL
- Config drift is detected via `scripts/sync_artifacts.py`

## Config Key Categories

| Category | Example Keys | Count |
|----------|-------------|-------|
| Trading | SL_PCT, TARGET_PCT, TRAIL_PCT | ~50 |
| Risk | MAX_DRAWDOWN, MAX_DAILY_LOSS, PORTFOLIO_MAX_SL_RISK_PCT | ~30 |
| Market Data | DATA_PROVIDER_PRIORITY, DATA_PROVIDER_ENABLED | ~20 |
| Web Dashboard | web_dashboard_enabled, web_dashboard_host, web_dashboard_port | ~30 |
| Governance | ENVIRONMENT, db_migration_enabled, data_retention_* | ~20 |
| ML | FEATURE_COLS, ml_retrain_frequency | ~15 |
| Other | ~695 additional keys | ~695 |

## Key Rule

**Every new config key MUST have a safe default in `index_config.defaults.json`.**  
After adding any key, run: `python scripts/generate_config_schemas.py`
