# OPB WEB CLOSURE WIP27 — Configurable Public Base URL

## Scope
Web-only functional closure pass. No trading strategy, broker execution, risk-engine, or database-schema changes.

## Change
Added `PUBLIC_BASE_URL_ADMIN_OVERRIDE`.

Authorized Super Admin/Admin users with `modify_config` can change it from the existing Admin Configuration UI.

### Resolution precedence
1. `PUBLIC_BASE_URL_ADMIN_OVERRIDE` when configured
2. deployment environment URL variables
3. legacy persisted configuration URL
4. production/development fallback

### Safety
- HTTP/HTTPS URL validation.
- Embedded credentials rejected.
- Production loopback URLs rejected.
- Existing config backup/audit mechanism records changes.
- Public URL resolver cache is invalidated after config apply/rollback.
- Notification/action links use the centralized resolver.

### UI
The setting is exposed under Admin Configuration → System.

### Validation
- URL/notification/Web closure targeted suite: 19 passed.
- Additional Admin/RBAC/Web suites passed:
  `test_admin.py`, `test_control_rbac.py`,
  `test_admin_control_plane.py`, `test_web_route_contract.py`,
  `test_all_ui_screens_and_navigation.py`.

### Deployment
NOT deployed to AWS.
NOT production-certified.

Next: authenticated Super Admin runtime browser closure, then permission matrix, then mobile.
