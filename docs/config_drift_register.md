# Configuration Drift Register

**Authority:** Final Master System Constitution — Mandatory Technical Debt Governance  
**Purpose:** Track configuration drift between environments, config files, and documented defaults  
**Last Updated:** 2026-05-30  
**Review Cycle:** Every release

---

## Format

| ID | Key | Default File | Env File | CI Config | Drift Detected | Status |
|----|-----|-------------|----------|-----------|----------------|--------|
| CDR-001 | — | — | — | — | — | — |

---

## Active Entries

*No configuration drift entries currently tracked.*

## Drift Categories

| Category | Description | Detection Method |
|----------|-------------|-----------------|
| **KEY_MISSING** | Key exists in defaults but not in env.example or CI config | Automated diff |
| **VALUE_MISMATCH** | Same key has different default values across files | Automated diff |
| **TYPE_MISMATCH** | Same key has different expected types | Schema validation |
| **ORPHANED_KEY** | Key exists in config but not in defaults/schema | Automated scan |
| **STALE_VARIABLE** | Env var referenced in CI/Docker but removed from codebase | Cross-reference scan |
| **DOCUMENTED_WRONG** | Documentation describes different behavior than config | Manual review |

## Remediation Policy

1. **Detection**: Automated via `scripts/sync_artifacts.py --check-config-drift` and CI pipeline
2. **Alignment**: Update env.example, CI configs, and documentation to match defaults
3. **Validation**: Run `scripts/validate_config_schema.py --all` to verify
4. **Prevention**: All new config keys must be added to defaults first, then synced

## Resolved Entries

*No entries have been resolved yet.*

---

*End of Configuration Drift Register — v1.0*
