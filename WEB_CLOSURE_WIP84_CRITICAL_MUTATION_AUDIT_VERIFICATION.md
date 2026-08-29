# OPB WEB CLOSURE WIP84 — Critical Mutation Audit Verification

Critical mutation route declarations: 34
With nearby audit evidence: 14
With transaction/error-boundary evidence: 32

## Critical route verification
- `/signals/{signal_id}/mark-order-placed` — `tests/test_admin_signal_rbac_contract.py:17` — audit: **NO** — transaction/error boundary: **NO**
- `/blacklist/user` — `archive/unrelated_modules/realestate/fraud_detection.py:497` — audit: **NO** — transaction/error boundary: **NO**
- `/moderation/{property_id}/approve` — `archive/unrelated_modules/realestate/admin_panel.py:372` — audit: **NO** — transaction/error boundary: **YES**
- `/moderation/{property_id}/reject` — `archive/unrelated_modules/realestate/admin_panel.py:379` — audit: **NO** — transaction/error boundary: **YES**
- `/kyc/{user_id}/verify` — `archive/unrelated_modules/realestate/admin_panel.py:423` — audit: **NO** — transaction/error boundary: **YES**
- `/orders` — `archive/unrelated_modules/realestate/payments.py:463` — audit: **NO** — transaction/error boundary: **YES**
- `/users` — `core/auth/routes.py:422` — audit: **NO** — transaction/error boundary: **YES**
- `/users/{username}/role` — `core/auth/routes.py:483` — audit: **NO** — transaction/error boundary: **YES**
- `/users/{username}/reset-password` — `core/auth/routes.py:519` — audit: **NO** — transaction/error boundary: **YES**
- `/users/{username}/disable` — `core/auth/routes.py:536` — audit: **NO** — transaction/error boundary: **YES**
- `/users/{username}/enable` — `core/auth/routes.py:548` — audit: **NO** — transaction/error boundary: **YES**
- `/users/{username}` — `core/auth/routes.py:559` — audit: **NO** — transaction/error boundary: **YES**
- `/users/{username}/permissions` — `core/auth/routes.py:661` — audit: **YES** — transaction/error boundary: **YES**
- `/users/{username}/toggle-signals` — `core/auth/routes.py:741` — audit: **YES** — transaction/error boundary: **YES**
- `/signals/{signal_id}/mark-order-placed` — `core/auth/routes.py:794` — audit: **YES** — transaction/error boundary: **YES**
- `/users/{username}/revoke-sessions` — `core/auth/routes.py:831` — audit: **YES** — transaction/error boundary: **YES**
- `/mfa/setup` — `core/auth/routes.py:884` — audit: **NO** — transaction/error boundary: **YES**
- `/roles/{operator}` — `core/control_plane/server.py:704` — audit: **YES** — transaction/error boundary: **YES**
- `/config/reload` — `core/control_plane/server.py:724` — audit: **YES** — transaction/error boundary: **YES**
- `/control/risk_limit/{name}/{value}` — `core/control_plane/server.py:841` — audit: **YES** — transaction/error boundary: **YES**
- `/api/governance/approve` — `core/enterprise_dashboard/routes/governance.py:189` — audit: **NO** — transaction/error boundary: **YES**
- `/api/governance/reject` — `core/enterprise_dashboard/routes/governance.py:218` — audit: **NO** — transaction/error boundary: **YES**
- `/api/platform/provisioning/requests/{request_id}/approve` — `core/enterprise_dashboard/routes/provisioning.py:119` — audit: **NO** — transaction/error boundary: **YES**
- `/api/platform/provisioning/requests/{request_id}/reject` — `core/enterprise_dashboard/routes/provisioning.py:158` — audit: **NO** — transaction/error boundary: **YES**
- `/api/v1/admin/test-dispatch-signal` — `core/enterprise_dashboard/routes/admin.py:23` — audit: **NO** — transaction/error boundary: **YES**
- `/api/config/validate` — `core/enterprise_dashboard/routes/admin.py:306` — audit: **YES** — transaction/error boundary: **YES**
- `/api/config/preview` — `core/enterprise_dashboard/routes/admin.py:314` — audit: **YES** — transaction/error boundary: **YES**
- `/api/config/apply` — `core/enterprise_dashboard/routes/admin.py:322` — audit: **YES** — transaction/error boundary: **YES**
- `/api/config/rollback/{version}` — `core/enterprise_dashboard/routes/admin.py:389` — audit: **YES** — transaction/error boundary: **YES**
- `/api/changes/approve/{change_id}` — `core/enterprise_dashboard/routes/admin.py:497` — audit: **YES** — transaction/error boundary: **YES**
- `/api/changes/reject/{change_id}` — `core/enterprise_dashboard/routes/admin.py:516` — audit: **YES** — transaction/error boundary: **YES**
- `/api/v1/admin/analyze-portfolio` — `core/enterprise_dashboard/routes/admin.py:666` — audit: **YES** — transaction/error boundary: **YES**
- `/api/intelligence/risk-score` — `core/enterprise_dashboard/routes/intelligence_analysis.py:176` — audit: **NO** — transaction/error boundary: **YES**
- `/signals/inject` — `core/enterprise_dashboard/routes/webhooks.py:71` — audit: **NO** — transaction/error boundary: **YES**

## Mandatory critical areas
- User registration and user administration
- Role and individual permission changes
- Setup Configuration changes
- Deployment URL / Admin URL override / Base URL
- Approve / Reject / Rollback
- Signal and stop-loss changes
- Trading/risk state changes where present