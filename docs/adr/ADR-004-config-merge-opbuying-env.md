# ADR-004: 3-Layer Config Merge with OPBUYING_* Environment Injection

## Status
ACCEPTED — July 2026

## Context
The trading system requires a flexible configuration system that supports:
- Safe defaults for development
- Environment-specific overrides
- Secret injection without hardcoding
- Audit trail for config changes
- Schema validation on startup

## Decision
Configuration is resolved via a **4-stage merge pipeline**:
1. **`json/index_config.defaults.json`** — Single source of truth for all default values (974+ keys). Must be the canonical schema.
2. **`json/config.json`** — Environment-specific overrides (git-tracked for audit trail)
3. **`json/config.local.json`** — Machine-specific overrides (gitignored)
4. **`OPBUYING_*` Environment Variables** — Secret injection. Prefix `OPBUYING_` is stripped and matched against config keys. All secrets (BOT_TOKEN, API_KEY, PASSWORD) must come from env vars with empty defaults in config.

## Consequences
- **Positive:** Clear separation between code, config, and secrets. Full audit trail via `json/config_audit.jsonl`. Schema validation catches configuration errors at startup. Base64 obfuscation support for legacy deployments.
- **Negative:** 974+ config keys create management complexity. Config v1/v2 format drift exists. Some keys lack schema validation.
- **Trade-off:** Expressiveness over simplicity. Acceptable for an institutional trading system with complex configuration needs.

## Related
- `core/config_bootstrap.py` (merge engine)
- `core/config_loader.py` (env override logic)
- `core/config_validator.py` (schema validation)
- `core/config_audit_log.py` (audit trail)
- `scripts/generate_config_schemas.py` (schema generation)
