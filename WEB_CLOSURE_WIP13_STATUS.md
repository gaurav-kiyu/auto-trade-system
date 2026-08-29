# OPB WEB CLOSURE WIP13 — NAVIGATION / CONTRACT REGRESSION GUARD

Baseline: OPB_WEB_CLOSURE_WIP12
Status: NOT CERTIFIED / DO NOT DEPLOY

## This pass

### 1. Internal navigation contract
Added `tests/test_web_route_contract.py` to mechanically verify every enterprise-template internal `href` resolves to a declared FastAPI route (excluding static assets and fragment-only links).

### 2. Production URL hygiene
Added a regression guard preventing `localhost:8000` from appearing directly in enterprise HTML templates. Runtime notification/action URLs remain centralized through `core.notifications.url_resolver` so production can use the configured public base URL.

### 3. CSP / event-handler regression guard
Added a repository-level test ensuring enterprise templates contain no inline DOM event-handler attributes. JavaScript must remain nonce/CSP compliant and use `addEventListener`.

## Validation

`tests/test_web_route_contract.py`: 3/3 PASS.

Existing WIP12 selected functional suites remain the baseline and must continue to pass after subsequent functional repairs.

## Important finding

A full repository `pytest` invocation in this analysis environment cannot currently be treated as a complete certification because the uploaded environment is missing optional test/runtime dependencies including `hypothesis`, `duckdb`, and `yfinance`. This is an environment limitation, not evidence that those tests pass.

## Remaining closure work

1. Browser-level Admin Configuration control matrix.
2. Browser-level Admin Signals control/outcome matrix.
3. Browser-level Admin Portfolio control matrix.
4. Intelligence Engine full tab/action matrix.
5. Dashboard/Strategy/Execution/P&L click-path matrix.
6. Permission-to-navigation visibility matrix.
7. Privileged API authorization matrix.
8. Audit-log mutation/reconstruction verification.
9. Desktop Web closure.
10. Mobile only after Web closure.

Do not deploy WIP13 to AWS as a certified release.
