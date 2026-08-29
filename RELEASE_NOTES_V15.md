# OPB Web Clean Release v15 — Deadline Hardening

## Purpose

v15 is the v14 security-hardened release with two production-readiness corrections found during final pre-deployment verification.

## Corrections

- Corrected the production dashboard port in `json/config.json` from 8000 to 8765 so it matches the Docker/AWS mapping, health checks, deployment scripts, and documented access URL.
- Corrected the active notification threshold in `json/config.json` from 100 to 60 so the configured Telegram gate no longer silently discards valid signals scored 60–99.

- Added Authlib 1.7.2 and HTTPX 0.28.0+ to runtime enterprise-dashboard dependencies so the implemented SSO/OIDC flow is deployable rather than silently degrading because its runtime dependencies are absent.
- Added Authlib 1.7.2 to the curated dependency lock.
- Updated the dashboard optional dependency group in `pyproject.toml` with Authlib and HTTPX.
- Made `AuthHandler` create the parent directory for its SQLite database before initialization, allowing a clean source checkout to bootstrap authentication without shipping runtime databases.
- Bumped Docker image metadata from 2.59.0 to 2.59.1.

## Preserved features

The v14 security-hardening and v13 interaction fixes remain intact, including registration lifecycle, RBAC/privileges, notification routing/filtering, audit controls, SSO URL boundaries, password controls, navigation/mobile interaction fixes, route reconciliation, and secret-free source packaging.

## Verification

- Python compileall: PASS
- JavaScript syntax check: PASS
- Targeted registration/RBAC/notification/security/audit/web closure suite: PASS (all selected tests passed)
- Canonical `static/theme_engine.js` and `core/static/theme_engine.js`: byte-identical
- Runtime DB files, sessions, reset-token stores, vault keys and generated reports/logs: excluded from release
- SSO runtime dependency gap: corrected in requirements and lock
