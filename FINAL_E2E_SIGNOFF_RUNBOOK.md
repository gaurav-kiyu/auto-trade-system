# OPB FINAL E2E SIGN-OFF RUNBOOK

This stage can proceed independently while the complete pytest suite runs.

## 1. Privileged Setup Configuration

Test as a privileged user:
- Read Deployment URL.
- Update Deployment URL.
- Read Admin URL override.
- Update Admin URL override.
- Read Base/Public URL.
- Update Base/Public URL.

Expected:
- Permission is enforced server-side.
- Validation rejects malformed/unsafe URLs.
- Change is persisted transactionally.
- Exactly one authoritative audit event is produced.
- Operational log contains correlation/request context.
- Super Admin receives immediate notification for privileged changes.

## 2. Approval lifecycle

For a change requiring approval:
- Create change -> PENDING_APPROVAL.
- Reject without reason -> MUST be rejected by server.
- Reject with reason -> REJECTED + reason audited.
- Rollback without reason -> MUST be rejected by server.
- Rollback with reason -> state restored + reason audited.
- Approve -> APPLIED + audit transition.

## 3. Authorization

Verify:
- Unprivileged user cannot read/write protected setup configuration beyond
  explicitly allowed read permissions.
- Privileged user can perform only the actions granted by RBAC.
- Super Admin can approve/reject/rollback when policy requires it.
- Direct API calls are denied even if the UI is bypassed.

## 4. URL propagation

After changing the canonical configured URL, verify:
- SSO/action URLs.
- Notification links.
- Generated application links.
- Admin/UI links.
- External/public URLs.

No executable link-generation path may fall back to a hard-coded deployment
host.

## 5. Logging and audit

For each mutation verify:
- actor identity,
- action,
- target,
- timestamp,
- result,
- before/after where applicable,
- reason where required,
- correlation/request ID.

Verify secrets/passwords/tokens/API keys are absent.

## 6. Negative/security tests

Attempt:
- unauthorized configuration mutation,
- invalid URL,
- localhost/private/internal URL where production policy forbids it,
- duplicate approval,
- reject after approval,
- rollback without an applicable prior state,
- replay of an already-processed mutation.

Each must be safely rejected and appropriately logged/audited.

## 7. Production smoke

After deployment:
- login,
- privileged setup page,
- change a non-destructive configuration value,
- verify audit event,
- verify Super Admin notification,
- verify generated URL,
- verify rollback,
- verify application health.

Do not use production credentials/secrets in test artifacts.
