# `core/environment.py` — Environment Separation

## What it does

Validates the deployment environment at startup and guards against running
in an unsafe mode/environment combination. Six environments:
`dev` / `qa` / `paper` / `shadow` / `staging` / `production`
(`Environment` enum).

## Resolution precedence

`validate_environment(cfg)` resolves the effective environment with this
precedence: `OPBUYING_ENVIRONMENT` env var > `ENVIRONMENT` config key. If
both are set to different values, it logs a warning and uses the env var.
An invalid value for either is a hard startup failure (`sys.exit(88)`).

Note: `current_environment()` (a separate, simpler helper) only reads the
env var and defaults to `DEV` if unset — it does **not** check the config
key. Use `validate_environment(cfg)` for the full-precedence resolution;
`current_environment()` is for callers that only have the env var context.

## Guards (both hard-exit on violation)

- **`guard_dev_config_in_production(cfg)`** — if `ENVIRONMENT=production`,
  warns (and, if `environment_block_on_violation` is true, the default,
  blocks startup) when the config still looks dev-like: placeholder
  `BOT_TOKEN`/`CHAT_ID` (`"YOUR_..."`), `BASE_CAPITAL` under 10,000, an
  empty/default `admin_control_plane_auth_token`, or a web dashboard enabled
  with no auth token.
- **`guard_mode_env_compatibility(execution_mode, env)`** — refuses to start
  if `execution_mode` is `FULL_AUTO` or `LIVE_MANUAL_CONFIRM` outside of
  `STAGING`/`SHADOW`/`PRODUCTION`.

Both guards are called from `validate_environment()`, so calling that one
function at startup exercises the full check.

## Config keys

`ENVIRONMENT` (default `"dev"`), `environment_block_on_violation` (default
`true`), `EXECUTION_MODE` (default `"SIGNAL_ONLY"`).

## Public API

`Environment`, `current_environment()`, `validate_environment()`,
`guard_dev_config_in_production()`, `guard_mode_env_compatibility()` — see
`__all__`.

## Tests

`tests/test_environment.py`.
