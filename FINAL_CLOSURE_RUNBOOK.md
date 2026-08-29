# OPB FINAL CLOSURE RUNBOOK

This is the final verification gate. No additional WIP numbering is required
unless a real defect is found.

## A. Dependency verification

Required packages previously blocking collection:
- hypothesis
- duckdb
- yfinance

The user's Windows environment has confirmed all three import successfully.

## B. Full test suite

Run from the project root:

    python -m pytest -q

Do not suppress, deselect, or ignore failures.

If failures occur, capture the complete output:

    python -m pytest -q 2>&1 | Tee-Object -FilePath pytest-full.log

## C. Failure triage

Classify every failure as one of:
1. application defect,
2. test defect,
3. dependency/environment issue,
4. expected/intentional result.

Only genuine application defects should be changed.

## D. Privileged configuration E2E

Verify:
- Deployment URL is editable only by authorized privileged users.
- Admin URL override is editable only by authorized privileged users.
- Base/Public URL is editable only by authorized privileged users.
- Every change is audited.
- Super Admin receives the immediate notification.
- High-risk changes can require approval.
- Reject requires a reason.
- Rollback requires a reason.
- Reject/Rollback transitions are audited.
- Unauthorized users are blocked.

## E. URL propagation

Verify configured URLs are used consistently by:
- SSO/action URLs,
- notification links,
- UI links,
- generated application links,
- externally visible routes.

No hard-coded deployment/localhost URL should remain in executable configuration/link generation.

## F. Logging

Verify:
- audit log and operational log remain separate,
- correlation/request ID is present,
- success/failure/error context is useful,
- secrets/passwords/tokens/API keys are not logged,
- audit events are immutable and attributable.

## G. Final certification boundary

A green local pytest suite proves the packaged tests pass. Production closure
still requires environment-level E2E/smoke validation against the intended AWS
deployment and database/notification infrastructure.

Do not mark production-certified solely from static analysis.
