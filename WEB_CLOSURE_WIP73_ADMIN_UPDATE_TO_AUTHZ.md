# OPB WEB CLOSURE WIP73 — Admin Update → Authorization Trace

Candidate mutation endpoints: 21

## Endpoint authorization evidence
### `/blacklist/user` — `archive/unrelated_modules/realestate/fraud_detection.py:497`
- **No explicit authorization/check signal found in the immediate route neighborhood.**
### `/kyc/{user_id}/verify` — `archive/unrelated_modules/realestate/admin_panel.py:423`
- **No explicit authorization/check signal found in the immediate route neighborhood.**
### `/users` — `core/auth/routes.py:422`
- `if not is_super_admin_identity(admin.username, admin.role) and role != "viewer":`
- `if new_role == "super_admin" and not is_super_admin_identity(admin.username, admin.role):`
- `if str(target.role).lower() == "super_admin" and new_role != "super_admin" and not is_super_admin_identity(admin.username, admin.role):`
### `/users/{username}/role` — `core/auth/routes.py:483`
- `if new_role == "super_admin" and not is_super_admin_identity(admin.username, admin.role):`
- `if str(target.role).lower() == "super_admin" and new_role != "super_admin" and not is_super_admin_identity(admin.username, admin.role):`
### `/users/{username}/reset-password` — `core/auth/routes.py:519`
- **No explicit authorization/check signal found in the immediate route neighborhood.**
### `/users/{username}/disable` — `core/auth/routes.py:536`
- **No explicit authorization/check signal found in the immediate route neighborhood.**
### `/users/{username}/enable` — `core/auth/routes.py:548`
- **No explicit authorization/check signal found in the immediate route neighborhood.**
### `/users/{username}` — `core/auth/routes.py:559`
- **No explicit authorization/check signal found in the immediate route neighborhood.**
### `/users/{username}/permissions` — `core/auth/routes.py:661`
- `if requested_role != target_role and not is_super_admin_identity(admin.username, admin.role):`
- `if target_role == "super_admin" and not is_super_admin_identity(admin.username, admin.role):`
- `if not is_super_admin_identity(admin.username, admin.role):`
### `/users/{username}/toggle-signals` — `core/auth/routes.py:741`
- `"""Signal Intelligence / Accuracy / Category Breakdown for authorized viewers."""`
- `current_user: AuthUser = Depends(auth_deps.require_auth),`
- `username=current_user.username,`
### `/users/{username}/revoke-sessions` — `core/auth/routes.py:831`
- `current_user: AuthUser = Depends(auth_deps.require_auth),`
- `username=current_user.username,`
- `auth_handler.set_mfa_secret(current_user.username, secret)`
- `auth_handler.update_mfa_recovery_codes(current_user.username, hashed_codes)`
- `current_user: AuthUser = Depends(auth_deps.require_auth),`
### `/roles/{operator}` — `core/control_plane/server.py:704`
- `require_permission(role_manager_ref, identity, "modify_config")`
- `require_permission(role_manager_ref, identity, "modify_config")`
- `authorization: str | None = Header(default=None),`
- `token_obj = _auth.authenticate_request(authorization)`
- `def get_state(authorization: str | None = Header(default=None)) -> dict:`
- `identity = _resolve_identity(authorization)`
- `_check_permission(identity, "control_state")`
- `authorization: str | None = Header(default=None),`
- `identity = _resolve_identity(authorization)`
- `_check_permission(identity, "control_audit")`
### `/api/v1/admin/test-dispatch-signal` — `core/enterprise_dashboard/routes/admin.py:23`
- `async def api_test_dispatch_signal(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):`
### `/api/v1/admin/test-email` — `core/enterprise_dashboard/routes/admin.py:205`
- `async def api_test_email(user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):`
- `async def api_get_config(user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):  # type: ignore[no-untyped-def]`
- `async def api_get_defaults(user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):  # type: ignore[no-untyped-def]`
### `/api/v1/admin/broker/fetch-holdings` — `core/enterprise_dashboard/routes/admin.py:648`
- `async def api_broker_info(broker_code: str, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_broker_fetch_holdings(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("add_brokers"))):  # type: ignore[no-untyped-def]`
- `async def api_analyze_portfolio(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_get_market_regime(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_get_broker_health(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_auto_hedge_portfolio(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_execute_hedge(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_tax_loss_harvest(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_generate_report(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
### `/api/v1/admin/analyze-portfolio` — `core/enterprise_dashboard/routes/admin.py:666`
- `async def api_analyze_portfolio(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_get_market_regime(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_get_broker_health(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_auto_hedge_portfolio(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_execute_hedge(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_tax_loss_harvest(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_generate_report(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_system_status(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
### `/api/v1/admin/auto-hedge` — `core/enterprise_dashboard/routes/admin.py:694`
- `async def api_get_broker_health(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_auto_hedge_portfolio(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_execute_hedge(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_tax_loss_harvest(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_generate_report(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_system_status(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
### `/api/v1/admin/execute-hedge` — `core/enterprise_dashboard/routes/admin.py:703`
- `async def api_execute_hedge(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_tax_loss_harvest(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_generate_report(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_system_status(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
### `/api/v1/admin/tax-loss-harvest` — `core/enterprise_dashboard/routes/admin.py:723`
- `async def api_tax_loss_harvest(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]`
- `async def api_generate_report(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_system_status(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
### `/api/v1/admin/generate-report` — `core/enterprise_dashboard/routes/admin.py:743`
- `async def api_generate_report(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
- `async def api_system_status(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]`
### `/api/intelligence/accessibility/assess` — `core/enterprise_dashboard/routes/intelligence.py:1118`
- **No explicit authorization/check signal found in the immediate route neighborhood.**