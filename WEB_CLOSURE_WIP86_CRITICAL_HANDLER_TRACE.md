# OPB WEB CLOSURE WIP86 — Critical Handler Trace

Inventory routes parsed: 20
Handlers successfully inspected: 20
Handlers with audit signal in body: 0

## Critical handler traces
### `/signals/{signal_id}/mark-order-placed` — `tests/test_admin_signal_rbac_contract.py:17` — `test_read_only_signal_viewers_do_not_get_write_checkbox`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `read_text`, `test_read_only_signal_viewers_do_not_get_write_checkbox`
### `/blacklist/user` — `archive/unrelated_modules/realestate/fraud_detection.py:497` — `blacklist_user`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Query`, `blacklist_user`, `get`
### `/moderation/{property_id}/approve` — `archive/unrelated_modules/realestate/admin_panel.py:372` — `approve_listing`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `HTTPException`, `approve_listing`, `post`
### `/moderation/{property_id}/reject` — `archive/unrelated_modules/realestate/admin_panel.py:379` — `reject_listing`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `HTTPException`, `post`, `reject_listing`
### `/kyc/{user_id}/verify` — `archive/unrelated_modules/realestate/admin_panel.py:423` — `verify_kyc`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `HTTPException`, `get`, `verify_kyc`
### `/orders` — `archive/unrelated_modules/realestate/payments.py:463` — `create_payment_order`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `HTTPException`, `Query`, `create_order`, `create_payment_order`, `post`, `to_dict`
### `/users` — `core/auth/routes.py:422` — `create_user`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Depends`, `HTTPException`, `create_user`, `get`, `get_instance`, `is_super_admin_identity`, `json`, `lower`, `notify_new_registration`, `put`, `strip`, `update_user_permissions`, `warning`
### `/users/{username}/role` — `core/auth/routes.py:483` — `update_user_role`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Depends`, `HTTPException`, `get`, `get_instance`, `get_user`, `is_super_admin_identity`, `json`, `list_users`, `lower`, `post`, `update_user_permissions`, `update_user_role`, `warning`
### `/users/{username}/reset-password` — `core/auth/routes.py:519` — `reset_user_password`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Depends`, `HTTPException`, `admin_reset_password`, `get`, `json`, `post`, `reset_user_password`, `revoke_all_user_sessions`
### `/users/{username}/disable` — `core/auth/routes.py:536` — `disable_user`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Depends`, `HTTPException`, `disable_user`, `get`, `post`, `revoke_all_user_sessions`
### `/users/{username}/enable` — `core/auth/routes.py:548` — `enable_user`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Depends`, `HTTPException`, `delete`, `enable_user`, `get`
### `/users/{username}` — `core/auth/routes.py:559` — `delete_user`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Depends`, `HTTPException`, `delete_user`, `delete_user_permissions`, `get`, `get_instance`, `get_user`, `list_users`, `lower`, `strip`
### `/mfa/setup` — `core/auth/routes.py:884` — `mfa_setup`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Depends`, `generate_mfa_secret`, `generate_recovery_codes`, `get_mfa_provisioning_uri`, `hash_recovery_code`, `mfa_setup`, `post`, `secret`, `set_mfa_secret`, `update_mfa_recovery_codes`
### `/api/governance/approve` — `core/enterprise_dashboard/routes/governance.py:189` — `api_governance_approve`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Body`, `Depends`, `api_governance_approve`, `approve_transition`, `debug`, `except`, `get`, `get_approval_workflow`, `json`, `post`, `strategy_name`, `time`, `to_state`
### `/api/governance/reject` — `core/enterprise_dashboard/routes/governance.py:218` — `api_governance_reject`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Body`, `Depends`, `api_governance_reject`, `debug`, `except`, `get`, `get_approval_workflow`, `json`, `reason`, `reject_transition`, `strategy_name`, `time`, `to_state`
### `/api/platform/provisioning/requests/{request_id}/approve` — `core/enterprise_dashboard/routes/provisioning.py:119` — `api_provisioning_approve`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Depends`, `_provisioner`, `api_provisioning_approve`, `approve_provisioning`, `debug`, `except`, `get`, `getattr`, `json`, `post`, `request`, `to_dict`
### `/api/platform/provisioning/requests/{request_id}/reject` — `core/enterprise_dashboard/routes/provisioning.py:158` — `api_provisioning_reject`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Depends`, `_provisioner`, `api_provisioning_reject`, `debug`, `except`, `get`, `json`, `reject_provisioning`, `request`, `to_dict`
### `/api/v1/admin/test-dispatch-signal` — `core/enterprise_dashboard/routes/admin.py:23` — `api_test_dispatch_signal`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `Depends`, `MIMEMultipart`, `MIMEText`, `SMTP`, `api_test_dispatch_signal`, `append`, `attach`, `build_rich_html_email`, `build_rich_telegram_html`, `float`, `get`, `get_eligible_recipients`, `get_instance`, `get_public_base_url`, `join`, `json`, `login`, `now_ist`, `post`, `recipient`, `record_generated_signal`, `replace`, `require_permission`, `round`, `send_message`, `split`, `starttls`, `strftime`, `strip`, `upper`
### `/api/intelligence/risk-score` — `core/enterprise_dashboard/routes/intelligence_analysis.py:176` — `api_risk_score`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `api_risk_score`, `except`, `get`, `get_risk_scorer`, `json`, `score_change`, `summary_text`, `time`, `to_dict`, `warning`
### `/signals/inject` — `core/enterprise_dashboard/routes/webhooks.py:71` — `signal_webhook`
- Parse status: **OK**
- Audit signal in handler body: **NO**
- Calls: `_route_signal_via_dispatcher`, `append`, `check`, `except`, `get`, `json`, `put`, `signal_webhook`, `time`, `warning`