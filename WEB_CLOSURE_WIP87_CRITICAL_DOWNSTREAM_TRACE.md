# OPB WEB CLOSURE WIP87 — Critical Downstream Trace

Critical handlers: 20
Resolved downstream function candidates: 37
Candidates with persistence: 17
Candidates with direct audit: 7

## Candidates
- `/moderation/{property_id}/approve` → `approve_listing` — `archive/unrelated_modules/realestate/admin_panel.py:114` — persistence: **NO** — audit: **NO**
- `/moderation/{property_id}/approve` → `approve_listing` — `archive/unrelated_modules/realestate/admin_panel.py:373` — persistence: **NO** — audit: **NO**
- `/moderation/{property_id}/reject` → `reject_listing` — `archive/unrelated_modules/realestate/admin_panel.py:122` — persistence: **NO** — audit: **NO**
- `/moderation/{property_id}/reject` → `reject_listing` — `archive/unrelated_modules/realestate/admin_panel.py:380` — persistence: **NO** — audit: **NO**
- `/orders` → `create_order` — `archive/unrelated_modules/realestate/payments.py:165` — persistence: **NO** — audit: **NO**
- `/orders` → `create_payment_order` — `archive/unrelated_modules/realestate/payments.py:464` — persistence: **NO** — audit: **NO**
- `/users` → `create_user` — `core/auth/routes.py:423` — persistence: **NO** — audit: **NO**
- `/users` → `create_user` — `core/auth/handler/handler.py:236` — persistence: **YES** — audit: **YES**
- `/users` → `update_user_permissions` — `core/auth/routes.py:662` — persistence: **YES** — audit: **YES**
- `/users` → `update_user_permissions` — `core/auth/user_signal_permissions.py:217` — persistence: **NO** — audit: **NO**
- `/users/{username}/role` → `update_user_permissions` — `core/auth/routes.py:662` — persistence: **YES** — audit: **YES**
- `/users/{username}/role` → `update_user_permissions` — `core/auth/user_signal_permissions.py:217` — persistence: **NO** — audit: **NO**
- `/users/{username}/role` → `update_user_role` — `core/auth/routes.py:484` — persistence: **NO** — audit: **NO**
- `/users/{username}/role` → `update_user_role` — `core/auth/handler/handler.py:448` — persistence: **YES** — audit: **YES**
- `/users/{username}/reset-password` → `admin_reset_password` — `core/auth/handler/handler.py:309` — persistence: **YES** — audit: **YES**
- `/users/{username}/reset-password` → `reset_user_password` — `core/auth/routes.py:520` — persistence: **NO** — audit: **NO**
- `/users/{username}/reset-password` → `revoke_all_user_sessions` — `core/auth/handler/session_manager.py:179` — persistence: **YES** — audit: **NO**
- `/users/{username}/disable` → `revoke_all_user_sessions` — `core/auth/handler/session_manager.py:179` — persistence: **YES** — audit: **NO**
- `/users/{username}/enable` → `delete` — `core/secrets_vault.py:258` — persistence: **YES** — audit: **YES**
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/cache.py:97` — persistence: **YES** — audit: **NO**
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/api/__init__.py:26` — persistence: **YES** — audit: **NO**
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/infrastructure/postgres_repository.py:377` — persistence: **YES** — audit: **NO**
- `/users/{username}/enable` → `delete` — `archive/unrelated_modules/realestate/infrastructure/repository.py:33` — persistence: **YES** — audit: **NO**
- `/users/{username}` → `delete_user` — `core/auth/routes.py:560` — persistence: **NO** — audit: **NO**
- `/users/{username}` → `delete_user` — `core/auth/handler/handler.py:489` — persistence: **YES** — audit: **YES**
- `/users/{username}` → `delete_user_permissions` — `core/auth/user_signal_permissions.py:274` — persistence: **NO** — audit: **NO**
- `/mfa/setup` → `mfa_setup` — `core/auth/routes.py:885` — persistence: **NO** — audit: **NO**
- `/mfa/setup` → `set_mfa_secret` — `core/auth/handler/mfa_handler.py:54` — persistence: **YES** — audit: **NO**
- `/mfa/setup` → `update_mfa_recovery_codes` — `core/auth/handler/mfa_handler.py:135` — persistence: **YES** — audit: **NO**
- `/api/governance/approve` → `api_governance_approve` — `core/enterprise_dashboard/routes/governance.py:190` — persistence: **NO** — audit: **NO**
- `/api/governance/approve` → `approve_transition` — `core/strategy/approval_workflow.py:275` — persistence: **NO** — audit: **NO**
- `/api/governance/reject` → `api_governance_reject` — `core/enterprise_dashboard/routes/governance.py:219` — persistence: **NO** — audit: **NO**
- `/api/governance/reject` → `reject_transition` — `core/strategy/approval_workflow.py:329` — persistence: **NO** — audit: **NO**
- `/api/platform/provisioning/requests/{request_id}/approve` → `api_provisioning_approve` — `core/enterprise_dashboard/routes/provisioning.py:120` — persistence: **NO** — audit: **NO**
- `/api/platform/provisioning/requests/{request_id}/approve` → `approve_provisioning` — `core/self_service_provisioning.py:226` — persistence: **YES** — audit: **NO**
- `/api/platform/provisioning/requests/{request_id}/reject` → `api_provisioning_reject` — `core/enterprise_dashboard/routes/provisioning.py:159` — persistence: **NO** — audit: **NO**
- `/api/platform/provisioning/requests/{request_id}/reject` → `reject_provisioning` — `core/self_service_provisioning.py:259` — persistence: **YES** — audit: **NO**