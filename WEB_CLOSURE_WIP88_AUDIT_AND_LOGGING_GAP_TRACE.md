# OPB WEB CLOSURE WIP88 — Audit + Proper Logging Gap Trace

WIP87 persistence candidates without direct audit: 10
Resolved candidate definitions inspected: 18
Candidates with direct audit: 4
Candidates with operational logging/error logging: 4

## Required logging standard
- Audit logs are immutable security records, not ordinary debug logs.
- Operational logs record useful execution/error context without secrets.
- Every state-changing operation must produce an audit event.
- Audit events include actor, action, target, timestamp, result and applicable before/after/reason/correlation data.
- Reject/Rollback requires a reason and records it.
- Failures are logged with correlation context; secrets/passwords/tokens are never logged.
- Audit and operational logs must not create excessive duplicate events.

## Remaining candidates
- `/users/{username}/reset-password` → `revoke_all_user_sessions` — `core/auth/handler/session_manager.py:179` — audit: **NO** — operational logging: **NO** — callees: `_get_conn`, `close`, `get_user`, `items`, `pop`, `revoke_all_user_sessions`
- `/users/{username}/disable` → `revoke_all_user_sessions` — `core/auth/handler/session_manager.py:179` — audit: **NO** — operational logging: **NO** — callees: `_get_conn`, `close`, `get_user`, `items`, `pop`, `revoke_all_user_sessions`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/cache.py:97` — audit: **YES** — operational logging: **NO** — callees: `_audit`, `_persist_vault`, `delete`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/cache.py:97` — audit: **NO** — operational logging: **NO** — callees: `delete`, `pop`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/cache.py:97` — audit: **NO** — operational logging: **YES** — callees: `HTTPException`, `delete`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/api/__init__.py:26` — audit: **YES** — operational logging: **NO** — callees: `_audit`, `_persist_vault`, `delete`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/api/__init__.py:26` — audit: **NO** — operational logging: **NO** — callees: `delete`, `pop`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/api/__init__.py:26` — audit: **NO** — operational logging: **YES** — callees: `HTTPException`, `delete`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/infrastructure/postgres_repository.py:377` — audit: **YES** — operational logging: **NO** — callees: `_audit`, `_persist_vault`, `delete`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/infrastructure/postgres_repository.py:377` — audit: **NO** — operational logging: **NO** — callees: `delete`, `pop`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/infrastructure/postgres_repository.py:377` — audit: **NO** — operational logging: **YES** — callees: `HTTPException`, `delete`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/infrastructure/repository.py:33` — audit: **YES** — operational logging: **NO** — callees: `_audit`, `_persist_vault`, `delete`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/infrastructure/repository.py:33` — audit: **NO** — operational logging: **NO** — callees: `delete`, `pop`
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/infrastructure/repository.py:33` — audit: **NO** — operational logging: **YES** — callees: `HTTPException`, `delete`
- `/mfa/setup` → `set_mfa_secret` — `core/auth/handler/mfa_handler.py:54` — audit: **NO** — operational logging: **NO** — callees: `Set`, `_get_conn`, `close`, `lower`, `set_mfa_secret`, `strip`
- `/mfa/setup` → `update_mfa_recovery_codes` — `core/auth/handler/mfa_handler.py:135` — audit: **NO** — operational logging: **NO** — callees: `Update`, `_get_conn`, `close`, `dumps`, `lower`, `strip`, `update_mfa_recovery_codes`
- `/api/platform/provisioning/requests/{request_id}/approve` → `approve_provisioning` — `core/self_service_provisioning.py:226` — audit: **NO** — operational logging: **NO** — callees: `_save`, `approve_provisioning`, `get`, `request`, `time`
- `/api/platform/provisioning/requests/{request_id}/reject` → `reject_provisioning` — `core/self_service_provisioning.py:259` — audit: **NO** — operational logging: **NO** — callees: `_save`, `get`, `reject_provisioning`, `request`, `time`