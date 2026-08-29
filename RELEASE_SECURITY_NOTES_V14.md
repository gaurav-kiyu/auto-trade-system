# OPB v14 Release Security Notes

This release is a clean source/runtime-boundary package.

## Preserved implementation
- Registration -> authorization/permission workflow.
- Role-based access control and Super Admin protections.
- User signal categories, conviction tiers, quotas and channel routing.
- Registration email and administrator notification flow.
- Audit/logging contracts and privileged-change workflow.
- Web/mobile interaction fixes from v13.

## Security corrections
- Self-registered accounts are created with signal authorization disabled until explicitly granted by an administrator.
- Admin-created accounts default to signal delivery disabled; administrators must explicitly grant signal privileges.
- Observer and Developer roles are now supported consistently by the auth handler as well as the RBAC matrix.
- SMTP password is no longer packaged in `json/config.json`; production SMTP credentials must come from environment/secret storage.
- Historical config-drift reports containing a real SMTP credential were sanitized.
- Runtime authentication/session databases, user permission state, vault key, logs, backups and generated reports are excluded from the release archive to prevent stale sessions, reset tokens, private state and secrets from being redeployed.
- The application will create required runtime state on first start. Existing runtime data should be restored from the user's separately retained backup only when intentionally required.

## Verification boundary
This package is source-validated. Live browser/AWS certification still requires runtime E2E verification.
