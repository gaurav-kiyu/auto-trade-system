# OPB WEB CLOSURE WIP11 — FUNCTIONAL CLICK-PATH CONTINUATION

Baseline: OPB_WEB_CLOSURE_WIP10
Status: NOT CERTIFIED / DO NOT DEPLOY

## This pass

### User Signals
- Replaced the modal "Execute Paper Trade" anchor (`href="#"`) with a real button.
- Removed per-open `.onclick` assignment and replaced it with a nonce-safe delegated/event-listener path.
- Preserved signal symbol, direction and score in data attributes before execution.
- Paper trade now sends the actual signal direction and score instead of only the symbol.
- Button is temporarily disabled while the request is executing.

### Admin Portfolio Analyzer
- Removed the misleading Google-search fallback for broker authentication.
- Broker login control starts disabled until `/api/v1/admin/broker/info/{broker_code}` returns a real `auth_url`.
- If broker metadata is unavailable, the UI explicitly says `Login URL unavailable` instead of presenting a dead link.

### CSP / Static Functional Scan
- 0 HTML inline event-handler attributes remain across enterprise templates.
- Existing JavaScript property assignments are runtime event wiring, not HTML inline handlers.

## Regression validation

Selected suites:
- tests/test_admin.py
- tests/test_control_rbac.py
- tests/test_user_signal_permissions.py
- tests/test_admin_auth.py
- tests/test_admin_control_plane.py
- tests/test_auth_register.py
- tests/test_all_ui_screens_and_navigation.py

Result: ALL SELECTED TESTS PASSED.

## Important remaining work

This package is intentionally NOT certified. The next closure pass must continue the full Web functional matrix:

Page -> control -> JavaScript handler -> API -> authorization -> response -> DOM update

Priority areas:
1. Admin Configuration every control and modal action.
2. Admin Signals every filter, outcome action and dispatch flow.
3. Admin Portfolio every broker, import, analysis and action control.
4. Intelligence Engine all tabs and every action button.
5. Dashboard/Strategy/Execution/P&L click paths.
6. Direct API authorization parity with visible RBAC permissions.
7. Audit-log verification for every administrative mutation.
8. Internal-link and route contract verification.
9. Only after Web closure: complete mobile functional matrix.

Do NOT deploy WIP11 to AWS until the above matrix is closed.
