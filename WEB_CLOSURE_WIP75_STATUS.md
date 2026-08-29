# OPB WEB CLOSURE WIP75 — Mandatory Reject/Rollback Reason

The privileged setup-configuration workflow now requires an appropriate reason
for both REJECT and ROLLBACK actions.

## Rules

- Reason is mandatory.
- Blank/whitespace-only reason is rejected.
- Minimum 10 characters.
- UI marks the field required.
- Server validates it independently.
- Reason is persisted with actor, timestamp, change/request ID, configuration,
  old value and new value.
- Reason appears in the audit trail and Super Admin notification.
- REJECT/ROLLBACK cannot proceed without a valid reason.
- Original submitted change remains immutable in history.

This rule applies regardless of whether the actor is an Admin or another
privileged user; Super Admin remains the highest authority.

WIP75 updates the workflow contract and regression coverage. The next pass
should implement/verify this validation in the actual approval/rejection/
rollback endpoints and UI.

NOT deployed to AWS.
NOT production-certified.
