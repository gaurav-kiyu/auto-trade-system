# OPB WEB CLOSURE WIP12 — RBAC / ADMIN CONTROL-PATH HARDENING

Baseline: OPB_WEB_CLOSURE_WIP11
Status: NOT CERTIFIED / DO NOT DEPLOY

## This pass

### 1. Granular authorization parity
The enterprise admin API layer no longer relies on the broad `admin_only` dependency for its configuration, kill-switch, change-management, test-dispatch, and portfolio-control endpoints.

Permissions are now enforced at the API boundary according to operation:
- `modify_config` — configuration reads/validation/preview/apply/history/drift/rollback, change proposals/approval/rejection, test email and test signal dispatch.
- `view_logs` — configuration audit log and change-management history/pending inspection.
- `halt_trading` — kill, resume, pause and resume-entry.
- `view_state` — system self-test, portfolio inspection, broker metadata/health, market regime, portfolio analysis/reporting and system status.
- `add_brokers` — broker holdings import.
- `modify_risk_limits` — auto-hedge, hedge execution and tax-loss-harvest operations.

This closes the previously identified gap where an Admin could be denied a permission in the UI but still reach some administrative API endpoints through a broad role check.

### 2. Admin User Controls hardening
- `Select All` / `Clear All` are real `type="button"` controls rather than `href="#"` links.
- Dynamically generated user action controls explicitly use `type="button"`.
- User-supplied username/display-name values are HTML-escaped before insertion into the dynamic table.
- Existing per-column filtering, sticky Actions column and delegated View/Edit/Reset/Enable/Disable/Delete handlers remain intact.

### 3. Static functional/CSP checks
- Enterprise template inline event-handler attributes: 0.
- Enterprise JavaScript blocks checked with Node/V8 syntax parser: 58/58 PASS.
- Remaining `href="#"`: none in `admin_users.html`; the only remaining occurrence is the intentional in-page anchor to `#strategies-breakdown` in Strategy Sandbox.

## Regression validation

Selected suites:
- tests/test_all_ui_screens_and_navigation.py
- tests/test_web_rbac_parity.py (new WIP12 regression guard)
- tests/test_admin.py
- tests/test_control_rbac.py
- tests/test_user_signal_permissions.py
- tests/test_admin_auth.py
- tests/test_admin_control_plane.py
- tests/test_auth_register.py

Result: ALL SELECTED TESTS PASSED.

Additional validation:
- Python compilation / compileall: PASS
- JavaScript syntax extraction: 58/58 PASS
- Jinja/template parsing regression suite: PASS

## Important remaining work

WIP12 is intentionally NOT certified. Continue the full Web functional matrix:
1. Admin Configuration browser click-path verification.
2. Admin Signals browser click-path verification, including outcome filters and test dispatch.
3. Admin Portfolio browser click-path verification for every broker/import/analysis/action control.
4. Intelligence Engine browser click-path verification for every tab/action.
5. Dashboard / Strategy / Execution / P&L browser click-path verification.
6. Audit-log proof for every privileged mutation.
7. Permission-to-menu visibility matrix: visible navigation must match effective permissions.
8. Direct API authorization matrix for all privileged route groups, not only the admin route module.
9. Desktop Web closure first; mobile remains deferred until Web closure is genuinely complete.

Do NOT deploy WIP12 to AWS until the browser-level Web functional matrix is closed.
