# OPB WEB CLOSURE WIP63 — User Registration & Permission Lifecycle

## Scope

This pass moves to the lifecycle that underpins the RBAC model:

Registration
→ pending/default access
→ welcome email
→ Admin/Super Admin notification
→ privileged approval
→ role/permission assignment
→ audit trail
→ user access.

The source was reviewed for concrete registration, email/notification, role,
permission and approval implementations.

No broad mutation was made in this pass.

## Safety rule

Do not automatically grant elevated privileges during registration.
A newly registered user must remain in the platform's defined pending/default
state until an authorized privileged user assigns access.

## Next

Trace the concrete registration handler, email service, notification recipient
logic, persistence model, and Admin Users approval/update path. Then close the
lifecycle as one transaction.

NOT deployed to AWS.
NOT production-certified.
