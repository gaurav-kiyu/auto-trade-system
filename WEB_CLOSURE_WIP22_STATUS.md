# OPB Web Closure WIP22

## Focus
Admin Signals read/write RBAC separation.

## Defect fixed
The Admin Signals page could be opened with `view_logs`, while its analytics API required `manage_users`. Conversely, the page rendered the `Order Placed?` write checkbox to read-only signal viewers even though the mutation endpoint requires `manage_users`.

## Remediation
- Added `AuthDependencies.require_any_permission()` using the same effective per-user RBAC semantics as `require_permission()`.
- Signal analytics now accepts `manage_users` OR `view_logs`.
- `mark-order-placed` remains restricted to `manage_users`.
- Read-only signal viewers now see a non-editable `Recorded` / `View only` state instead of a write checkbox.
- Added dedicated regression contracts.

## Validation
- Python compileall: PASS
- WIP22 RBAC/closure contract suite: 17/17 PASS
- Trading/strategy/broker/database logic: not modified
- AWS deployment: NOT performed
- Production certification: NOT claimed
