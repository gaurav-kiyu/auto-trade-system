# OPB WEB CLOSURE WIP85 — Open Critical Audit Routes

Critical mutation routes without nearby audit evidence: 20

These are the remaining critical routes requiring downstream call-chain verification.
- `/signals/{signal_id}/mark-order-placed` — `tests/test_admin_signal_rbac_contract.py:17` — handler: `test_read_only_signal_viewers_do_not_get_write_checkbox`
- `/blacklist/user` — `archive/unrelated_modules/realestate/fraud_detection.py:497` — handler: `blacklist_user`
- `/moderation/{property_id}/approve` — `archive/unrelated_modules/realestate/admin_panel.py:372` — handler: `approve_listing`
- `/moderation/{property_id}/reject` — `archive/unrelated_modules/realestate/admin_panel.py:379` — handler: `reject_listing`
- `/kyc/{user_id}/verify` — `archive/unrelated_modules/realestate/admin_panel.py:423` — handler: `verify_kyc`
- `/orders` — `archive/unrelated_modules/realestate/payments.py:463` — handler: `create_payment_order`
- `/users` — `core/auth/routes.py:422` — handler: `create_user`
- `/users/{username}/role` — `core/auth/routes.py:483` — handler: `update_user_role`
- `/users/{username}/reset-password` — `core/auth/routes.py:519` — handler: `reset_user_password`
- `/users/{username}/disable` — `core/auth/routes.py:536` — handler: `disable_user`
- `/users/{username}/enable` — `core/auth/routes.py:548` — handler: `enable_user`
- `/users/{username}` — `core/auth/routes.py:559` — handler: `delete_user`
- `/mfa/setup` — `core/auth/routes.py:884` — handler: `mfa_setup`
- `/api/governance/approve` — `core/enterprise_dashboard/routes/governance.py:189` — handler: `api_governance_approve`
- `/api/governance/reject` — `core/enterprise_dashboard/routes/governance.py:218` — handler: `api_governance_reject`
- `/api/platform/provisioning/requests/{request_id}/approve` — `core/enterprise_dashboard/routes/provisioning.py:119` — handler: `api_provisioning_approve`
- `/api/platform/provisioning/requests/{request_id}/reject` — `core/enterprise_dashboard/routes/provisioning.py:158` — handler: `api_provisioning_reject`
- `/api/v1/admin/test-dispatch-signal` — `core/enterprise_dashboard/routes/admin.py:23` — handler: `api_test_dispatch_signal`
- `/api/intelligence/risk-score` — `core/enterprise_dashboard/routes/intelligence_analysis.py:176` — handler: `api_risk_score`
- `/signals/inject` — `core/enterprise_dashboard/routes/webhooks.py:71` — handler: `signal_webhook`