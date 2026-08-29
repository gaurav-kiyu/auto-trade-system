# OPB FINAL AWS SMOKE / E2E SIGN-OFF

Run against the intended AWS deployment with approved test accounts and
non-destructive test configuration.

1. Authentication / authorization
- Login works.
- Unprivileged users cannot mutate protected setup configuration.
- Privileged users can mutate only permitted settings.
- Direct API calls enforce the same RBAC as the UI.

2. Setup configuration
- Safely change Deployment URL.
- Safely change Admin URL override.
- Safely change Base/Public URL.
- Verify persistence after reload and a new session.

3. Notification
- Super Admin receives immediate notification after a privileged change.
- Notification contains correct context and no secrets.
- If SMTP quota is exhausted, notification failure is recorded without
  corrupting/partially applying the underlying configuration transaction.

4. Approval lifecycle
- Submit -> PENDING_APPROVAL.
- Reject without reason -> rejected by server.
- Reject with reason -> REJECTED and reason audited.
- Approve -> APPLIED and audited.
- Rollback without reason -> rejected by server.
- Rollback with reason -> rollback succeeds and reason is audited.

5. Audit / operational logging
Verify actor, action, target, timestamp, result, before/after where applicable,
reason where required, and correlation/request ID. Verify secrets are absent.

6. Canonical URL propagation
Verify SSO/action URLs, notification links, UI/admin links, and generated
application links use the configured canonical URL.

7. Safety / replay
Attempt unauthorized mutation, duplicate approval, reject-after-approval,
invalid rollback, and replay of an already-processed mutation. Each must be
safely rejected and audited.

8. Final smoke
Health check, login, setup page, one safe privileged change, Super Admin
notification, audit event, rollback with mandatory reason, URL generation, and
clean application logs.

Production certification requires all live checks to pass.
