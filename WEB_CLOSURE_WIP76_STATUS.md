# OPB WEB CLOSURE WIP76 — Universal Audit Requirement

The requirement has been expanded from configuration auditing to **all
state-changing actions across the application**.

## Mandatory audit model

Every state-changing action must produce a server-side immutable audit event.

Examples:
- create/update/delete,
- login/logout/security events,
- role/permission changes,
- configuration changes,
- approve/reject/rollback,
- enable/disable,
- assignment/revocation,
- signal/stop-loss changes,
- operational actions,
- imports/exports where policy requires,
- administrative actions.

## Minimum event information

Where applicable:
- actor/user,
- action,
- target/entity,
- timestamp,
- result,
- before/after values,
- correlation/request ID,
- source/session/IP context according to policy,
- reason for rejection/rollback.

Never store passwords, tokens, secrets, or other sensitive credentials in audit records.

## Important

WIP76 establishes the universal audit contract and coverage matrix. It does
not falsely certify every route as audited merely because an audit helper exists.
Routes marked without nearby audit signals require implementation/verification.

NOT deployed to AWS.
NOT production-certified.
