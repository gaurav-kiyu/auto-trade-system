# OPB Web Closure WIP24

## Focus
Dashboard runtime control closure: duplicate DOM IDs and non-functional Refresh buttons.

## Defect found
`templates/enterprise/dashboard.html` contained two different Refresh controls sharing the same `id="dashboardRefreshBtn"`. Neither control had a click listener bound to the `refresh-dashboard` action. The dashboard therefore exposed visible Refresh buttons that could do nothing, while duplicate IDs made DOM targeting ambiguous.

## Remediation
- Renamed the two controls to unique IDs: `dashboardRefreshBtnTop` and `dashboardRefreshBtnSubbar`.
- Added a shared delegated binding for `[data-action="refresh-dashboard"]`.
- Each control now invokes the existing `loadDashboardData()` telemetry reload path.
- Buttons are disabled during the asynchronous refresh to prevent duplicate requests.
- Added regression tests in `tests/test_dashboard_refresh_controls.py`.

## Validation
Selected Web/RBAC/UI regression suite: PASS.
Dashboard refresh contract: PASS.
Web closure contract: PASS.
Web route contract: PASS.
Web RBAC parity: PASS.
Admin signal RBAC: PASS.
Control RBAC: PASS.
UI/navigation suite: PASS.

## Boundary
WIP24 is a Web closure candidate only. No AWS deployment and no production certification are claimed. Full authenticated browser click-path validation remains pending.
