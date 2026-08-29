# OPB WEB CLOSURE WIP74 — Privileged Setup Configuration Workflow

## Design adopted

Per the requested security model, privileged setup/configuration changes are
split into two classes:

### Low-risk configuration
May become effective immediately when the actor has the required permission,
with immediate Super Admin notification and audit.

### High-risk configuration
Uses:
SUBMIT → PENDING_APPROVAL → SUPER ADMIN NOTIFIED → APPROVE / REJECT / ROLLBACK.

High-risk examples include Deployment URL, Admin URL override, Public/Base URL,
authentication/security, RBAC, and email/system infrastructure.

## Required properties

- Server-side authorization; UI visibility is not the security boundary.
- Old/new values captured.
- Actor and timestamp captured.
- Immediate Super Admin notification.
- Approval/rejection/rollback are themselves audited.
- Rejected changes do not become effective.
- Rollback restores the previous effective value.
- Super Admin remains the highest authority.

## Scope

WIP74 establishes the closure contract and maps the existing source. No broad
application rewrite was performed.

NOT deployed to AWS.
NOT production-certified.
