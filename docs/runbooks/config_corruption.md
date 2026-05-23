# Runbook: Config Corruption

| Field | Value |
|-------|-------|
| Runbook ID | `RB-007` |
| Severity | HIGH |
| Category | Configuration |
| Status | 🚧 **Skeleton — Full content needed before Phase 4** |
| Phase Required | Phase 4+ |

## Trigger Condition
- Config file JSON parse failure
- Config hash mismatch on startup
- Missing required keys
- Schema validation failure

## Diagnosis
```bash
python -c "
from core.config_bootstrap import validate_config
errors = validate_config()
for e in errors: print(f'ERROR: {e}')
"
```

## Resolution
1. Check which config file is corrupted (config.json, config.local.json)
2. Restore from backup: `copy config.json.bak config.json`
3. If no backup → regenerate from defaults: `copy index_config.defaults.json config.json`
4. Re-apply any overrides (env vars, config.local.json)
5. Verify: `python scripts/validate_config_schema.py`
6. If env override has the fix → restart without changing file

## Runbook Status
⏳ **This runbook needs a detailed procedure before Phase 4 certification.**

## Related Runbooks
- None standalone — may trigger during startup sequence
