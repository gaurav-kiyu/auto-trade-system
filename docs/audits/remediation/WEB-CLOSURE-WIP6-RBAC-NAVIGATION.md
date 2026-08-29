# OPB WEB CLOSURE WIP6 — RBAC / NAVIGATION / ADMIN ACTIONS

## Scope
Web-first continuation of the production UI closure. No trading strategy, scoring, execution, broker, or database schema changes were made.

## Changes
- Added a centralized Jinja `user_can(user, permission)` resolver using the same effective per-user RBAC model as the FastAPI permission dependency.
- Preserved role permissions as the baseline when a user has no per-user permission record.
- Per-user explicit allow/deny overrides remain effective when a record exists; explicit deny wins.
- Super Admin remains unrestricted.
- Admin navigation now derives visibility from effective permissions rather than role-only checks for governance controls.
- Removed duplicate `User Controls & Permissions` shortcut from the Admin Users page header; the canonical location is the Admin & Governance navigation submenu.
- Made the Admin Users action column sticky and added minimum action-button dimensions so View/Edit/Reset/Enable/Disable/Delete controls remain visible while horizontally scrolling the wide permissions grid.
- Retained the existing delegated `data-action` event model for dynamically-rendered user rows.

## Regression Evidence
- Python compilation: PASS.
- Jinja enterprise-template compilation: PASS.
- JavaScript syntax checks across enterprise templates: PASS.
- `tests/test_auth_dependencies.py`: PASS.
- `tests/test_permissions.py`: PASS.
- `tests/test_rbac.py`: PASS.
- `tests/test_control_rbac.py`: PASS.
- `tests/test_user_signal_permissions.py`: PASS.
- `tests/test_admin.py`: PASS.
- `tests/test_admin_auth.py`: PASS.
- `tests/test_admin_control_plane.py`: PASS.

## Important Correctness Fix
The first RBAC implementation incorrectly replaced a role's baseline permission with `False` when no per-user permission record existed. This caused a legitimate Admin `halt_trading` check to fail. WIP6 fixes this by retaining the role baseline until a per-user record is present.

## Deployment Boundary
This WIP package is **not certified for AWS deployment**. Production browser verification remains required after deployment.
