# Environment Separation

**Module:** `core/environment.py`

Validates the deployment environment and prevents misconfiguration. Ensures
that production-like execution modes (FULL_AUTO, LIVE_MANUAL_CONFIRM) are only
permitted in appropriate environments.

## Environments

| Environment | Code | Description |
|-------------|------|-------------|
| DEV | `dev` | Local development (default) |
| QA | `qa` | Quality assurance testing |
| PAPER | `paper` | Paper trading (no real money) |
| SHADOW | `shadow` | Shadow deployment (parallel to production) |
| STAGING | `staging` | Pre-production staging |
| PRODUCTION | `production` | Live trading with real capital |

## Resolution Precedence

1. `OPBUYING_ENVIRONMENT` env var (highest priority)
2. `ENVIRONMENT` config key (from `index_config.defaults.json`)

A warning is logged if both are set to different values. The env var always wins.

## Guards

### `validate_environment(cfg)`
Main startup validation:
- Detects environment from env var or config
- Validates the value against allowed set
- Calls `guard_dev_config_in_production()` and `guard_mode_env_compatibility()`
- Returns the resolved `Environment` enum value

### `guard_dev_config_in_production(cfg)`
Prevents running with dev-like config in production:
- Placeholder BOT_TOKEN/CHAT_ID values
- BASE_CAPITAL below 10,000
- Missing admin auth token
- Dashboard enabled without auth
- Can block startup with `environment_block_on_violation: true`

### `guard_mode_env_compatibility(execution_mode, env)`
Blocks FULL_AUTO / LIVE_MANUAL_CONFIRM outside STAGING/SHADOW/PRODUCTION:
- Prevents accidental live execution in dev/test environments
- Exits with code 88 if violation detected

## Config Keys

- `ENVIRONMENT` — Deployment environment string
- `environment_block_on_violation` — Block startup on prod config violations
