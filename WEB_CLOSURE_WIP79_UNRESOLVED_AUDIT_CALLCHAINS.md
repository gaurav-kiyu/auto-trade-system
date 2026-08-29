# OPB WEB CLOSURE WIP79 — Unresolved Audit Call-Chain Map

Unresolved state-changing route neighborhoods: 132

These routes did not show an audit call in their immediate handler neighborhood.
The candidate service calls below are the next call-chain tracing targets.
## `/login` — `tests/test_auth_comprehensive.py:167`
- Candidate calls: `create_session`, `set_cookie`
## `/signals/{signal_id}/mark-order-placed` — `tests/test_admin_signal_rbac_contract.py:17`
- Candidate calls: none identified
## `/chat` — `archive/unrelated_modules/realestate/ai_chatbot.py:372`
- Candidate calls: none identified
## `/projects` — `archive/unrelated_modules/realestate/builder_portal.py:368`
- Candidate calls: `create_project`, `update_project_status`
## `/projects/{project_id}/units` — `archive/unrelated_modules/realestate/builder_portal.py:404`
- Candidate calls: `update_project_status`
## `/projects/{project_id}/units/bulk` — `archive/unrelated_modules/realestate/builder_portal.py:409`
- Candidate calls: `update_project_status`
## `/projects/{project_id}/units/{unit_id}/book` — `archive/unrelated_modules/realestate/builder_portal.py:425`
- Candidate calls: `update_project_status`
## `/projects/{project_id}/status` — `archive/unrelated_modules/realestate/builder_portal.py:436`
- Candidate calls: `update_project_status`
## `/check-property` — `archive/unrelated_modules/realestate/fraud_detection.py:459`
- Candidate calls: `fraud_report`, `generate_report`
## `/check-enquiry` — `archive/unrelated_modules/realestate/fraud_detection.py:482`
- Candidate calls: `fraud_report`, `generate_report`
## `/blacklist/phone` — `archive/unrelated_modules/realestate/fraud_detection.py:492`
- Candidate calls: `fraud_report`, `generate_report`
## `/blacklist/user` — `archive/unrelated_modules/realestate/fraud_detection.py:497`
- Candidate calls: `fraud_report`, `generate_report`
## `/moderation/{property_id}/approve` — `archive/unrelated_modules/realestate/admin_panel.py:372`
- Candidate calls: `get_reported_listings`, `get_reports`, `report_listing`, `resolve_report`
## `/moderation/{property_id}/reject` — `archive/unrelated_modules/realestate/admin_panel.py:379`
- Candidate calls: `get_reported_listings`, `get_reports`, `report_listing`, `resolve_report`
## `/reports` — `archive/unrelated_modules/realestate/admin_panel.py:387`
- Candidate calls: `get_reported_listings`, `get_reports`, `report_listing`, `resolve_report`
## `/reports/{report_id}/resolve` — `archive/unrelated_modules/realestate/admin_panel.py:404`
- Candidate calls: `resolve_report`
## `/kyc/submit` — `archive/unrelated_modules/realestate/admin_panel.py:416`
- Candidate calls: none identified
## `/kyc/{user_id}/verify` — `archive/unrelated_modules/realestate/admin_panel.py:423`
- Candidate calls: none identified
## `/{property_id}` — `archive/unrelated_modules/realestate/saved_properties.py:120`
- Candidate calls: `check_saved`, `delete`, `get_saved`, `get_saved_count`, `get_saved_properties`, `is_saved`, `save_property`, `saved_count`, `unsave_property`
## `/{property_id}` — `archive/unrelated_modules/realestate/saved_properties.py:130`
- Candidate calls: `check_saved`, `delete`, `get_saved`, `get_saved_count`, `get_saved_properties`, `is_saved`, `saved_count`, `unsave_property`
## `/predict` — `archive/unrelated_modules/realestate/ml_prediction.py:405`
- Candidate calls: none identified
## `/predict/train` — `archive/unrelated_modules/realestate/ml_prediction.py:436`
- Candidate calls: none identified
## `/tasks/{task_id}/run` — `archive/unrelated_modules/realestate/scheduler.py:425`
- Candidate calls: none identified
## `/run-all` — `archive/unrelated_modules/realestate/scheduler.py:441`
- Candidate calls: none identified
## `/tasks/{task_id}/toggle` — `archive/unrelated_modules/realestate/scheduler.py:479`
- Candidate calls: none identified
## `/import` — `archive/unrelated_modules/realestate/export_import.py:319`
- Candidate calls: none identified
## `/orders` — `archive/unrelated_modules/realestate/payments.py:463`
- Candidate calls: `create_order`, `create_payment_order`
## `/verify` — `archive/unrelated_modules/realestate/payments.py:480`
- Candidate calls: none identified
## `/offline` — `archive/unrelated_modules/realestate/payments.py:492`
- Candidate calls: none identified
## `/refund` — `archive/unrelated_modules/realestate/payments.py:526`
- Candidate calls: none identified
## `/webhook` — `archive/unrelated_modules/realestate/payments.py:537`
- Candidate calls: none identified
## `/google` — `archive/unrelated_modules/realestate/auth_service.py:389`
- Candidate calls: `create_auth_page_router`
## `/guest` — `archive/unrelated_modules/realestate/auth_service.py:400`
- Candidate calls: `create_auth_page_router`
## `/logout` — `archive/unrelated_modules/realestate/auth_service.py:406`
- Candidate calls: `create_auth_page_router`
## `/{notification_id}/read` — `archive/unrelated_modules/realestate/notifications.py:395`
- Candidate calls: `delete`, `delete_notification`, `get_saved_searches`, `save_search`
## `/mark-all-read` — `archive/unrelated_modules/realestate/notifications.py:401`
- Candidate calls: `delete`, `delete_notification`, `get_saved_searches`, `save_search`
## `/{notification_id}` — `archive/unrelated_modules/realestate/notifications.py:407`
- Candidate calls: `delete`, `delete_notification`, `get_saved_searches`, `save_search`
## `/saved-searches` — `archive/unrelated_modules/realestate/notifications.py:413`
- Candidate calls: `get_saved_searches`, `save_search`
## `/add` — `archive/unrelated_modules/realestate/comparison.py:163`
- Candidate calls: `MultiLanguageService`, `create_comparison_page_router`
## `/remove` — `archive/unrelated_modules/realestate/comparison.py:172`
- Candidate calls: `MultiLanguageService`, `create_comparison_page_router`
## `/clear` — `archive/unrelated_modules/realestate/comparison.py:189`
- Candidate calls: `MultiLanguageService`, `create_comparison_page_router`
## `/register` — `archive/unrelated_modules/realestate/rera_compliance.py:349`
- Candidate calls: `create_default_services`, `create_rera_page_router`
## `/register` — `archive/unrelated_modules/realestate/webhooks.py:348`
- Candidate calls: `delete`
## `/{endpoint_id}` — `archive/unrelated_modules/realestate/webhooks.py:359`
- Candidate calls: `delete`
## `/test/{event_type}` — `archive/unrelated_modules/realestate/webhooks.py:371`
- Candidate calls: none identified
## `/payments` — `archive/unrelated_modules/realestate/tenant_portal.py:340`
- Candidate calls: `update_maintenance_status`
## `/maintenance` — `archive/unrelated_modules/realestate/tenant_portal.py:370`
- Candidate calls: `update_maintenance_status`
## `/maintenance/{request_id}/status` — `archive/unrelated_modules/realestate/tenant_portal.py:395`
- Candidate calls: `update_maintenance_status`
## `/properties` — `archive/unrelated_modules/realestate/api/__init__.py:95`
- Candidate calls: `create_property`, `delete`, `delete_property`
## `/properties/{property_id}/media` — `archive/unrelated_modules/realestate/api/__init__.py:164`
- Candidate calls: `create_lead`, `create_rent_agreement`, `delete`, `delete_property`, `update_lead_status`
## `/properties/{property_id}` — `archive/unrelated_modules/realestate/api/__init__.py:177`
- Candidate calls: `create_agreement`, `create_lead`, `create_rent_agreement`, `delete`, `delete_property`, `update_lead_status`
## `/leads` — `archive/unrelated_modules/realestate/api/__init__.py:224`
- Candidate calls: `create_agreement`, `create_lead`, `create_rent_agreement`, `update_lead_status`
## `/leads/{lead_id}/status` — `archive/unrelated_modules/realestate/api/__init__.py:245`
- Candidate calls: `create_agreement`, `create_rent_agreement`, `update_lead_status`
## `/enquiries` — `archive/unrelated_modules/realestate/api/__init__.py:253`
- Candidate calls: `create_agreement`, `create_rent_agreement`
## `/agreements/rent` — `archive/unrelated_modules/realestate/api/__init__.py:275`
- Candidate calls: `create_agreement`, `create_realestate_router`, `create_rent_agreement`
## `/agreements/rent/{agreement_id}/e-stamp` — `archive/unrelated_modules/realestate/api/__init__.py:306`
- Candidate calls: `create_realestate_router`
## `/agreements/rent/{agreement_id}/e-sign` — `archive/unrelated_modules/realestate/api/__init__.py:314`
- Candidate calls: `create_realestate_router`
## `/{auction_id}/bid` — `archive/unrelated_modules/realestate/auction/engine.py:506`
- Candidate calls: none identified
## `/{auction_id}/buy-it-now` — `archive/unrelated_modules/realestate/auction/engine.py:523`
- Candidate calls: none identified
## `/{auction_id}/start` — `archive/unrelated_modules/realestate/auction/engine.py:534`
- Candidate calls: none identified
## `/{auction_id}/close` — `archive/unrelated_modules/realestate/auction/engine.py:540`
- Candidate calls: none identified
## `/register` — `core/auth/routes.py:137`
- Candidate calls: `create_session`, `create_user`, `update_user_permissions`
## `/login` — `core/auth/routes.py:225`
- Candidate calls: `_set_csrf_cookie`, `_set_session_cookie`, `create_session`, `revoke_session`
## `/logout` — `core/auth/routes.py:283`
- Candidate calls: `revoke_session`, `update_my_profile`, `update_password`, `update_user_metadata`, `update_user_permissions`
## `/profile` — `core/auth/routes.py:349`
- Candidate calls: `create_user`, `update_my_profile`, `update_password`, `update_user_metadata`, `update_user_permissions`
## `/change-password` — `core/auth/routes.py:389`
- Candidate calls: `create_user`, `update_password`, `update_user_permissions`, `update_user_role`
## `/users` — `core/auth/routes.py:422`
- Candidate calls: `admin_reset_password`, `create_user`, `reset_user_password`, `revoke_all_user_sessions`, `update_user_permissions`, `update_user_role`
## `/users/{username}/role` — `core/auth/routes.py:483`
- Candidate calls: `admin_reset_password`, `delete`, `delete_user`, `delete_user_permissions`, `reset_user_password`, `revoke_all_user_sessions`, `update_user_permissions`, `update_user_role`
## `/users/{username}/reset-password` — `core/auth/routes.py:519`
- Candidate calls: `admin_reset_password`, `delete`, `delete_user`, `delete_user_permissions`, `reset_user_password`, `revoke_all_user_sessions`, `update_user_permissions`
## `/users/{username}/disable` — `core/auth/routes.py:536`
- Candidate calls: `delete`, `delete_user`, `delete_user_permissions`, `revoke_all_user_sessions`, `update_user_permissions`
## `/users/{username}/enable` — `core/auth/routes.py:548`
- Candidate calls: `delete`, `delete_user`, `delete_user_permissions`, `update_user_permissions`
## `/users/{username}` — `core/auth/routes.py:559`
- Candidate calls: `delete`, `delete_user`, `delete_user_permissions`, `update_user_permissions`
## `/mfa/setup` — `core/auth/routes.py:884`
- Candidate calls: `mfa_setup`, `set_mfa_secret`, `update_mfa_recovery_codes`
## `/mfa/verify` — `core/auth/routes.py:921`
- Candidate calls: none identified
## `/mfa/disable` — `core/auth/routes.py:956`
- Candidate calls: none identified
## `/mfa/verify-session` — `core/auth/routes.py:1005`
- Candidate calls: none identified
## `/forgot-password` — `core/auth/routes.py:1174`
- Candidate calls: `create_password_reset_token`, `emergency_master_reset_password`, `emergency_reset_password`, `reset_password`, `reset_password_with_token`, `verify_password_reset_token`, `verify_reset_token`
## `/verify-reset-token` — `core/auth/routes.py:1193`
- Candidate calls: `emergency_master_reset_password`, `emergency_reset_password`, `reset_password`, `reset_password_with_token`, `verify_password_reset_token`, `verify_reset_token`
## `/reset-password` — `core/auth/routes.py:1209`
- Candidate calls: `emergency_master_reset_password`, `emergency_reset_password`, `reset_password`, `reset_password_with_token`
## `/emergency-reset-password` — `core/auth/routes.py:1222`
- Candidate calls: `emergency_master_reset_password`, `emergency_reset_password`
## `/logout` — `core/enterprise_dashboard/main.py:458`
- Candidate calls: `exception_handler`
## `/api/governance/request` — `core/enterprise_dashboard/routes/governance.py:157`
- Candidate calls: `get_source_health_report`
## `/api/governance/approve` — `core/enterprise_dashboard/routes/governance.py:189`
- Candidate calls: `get_source_health_report`
## `/api/governance/reject` — `core/enterprise_dashboard/routes/governance.py:218`
- Candidate calls: `get_source_health_report`
## `/api/platform/provisioning/request` — `core/enterprise_dashboard/routes/provisioning.py:80`
- Candidate calls: `api_provisioning_report`, `get_report`, `report`
## `/api/platform/provisioning/requests/{request_id}/approve` — `core/enterprise_dashboard/routes/provisioning.py:119`
- Candidate calls: `api_provisioning_report`, `get_report`, `report`
## `/api/platform/provisioning/requests/{request_id}/provisioned` — `core/enterprise_dashboard/routes/provisioning.py:139`
- Candidate calls: `api_provisioning_report`, `get_report`, `report`
## `/api/platform/provisioning/requests/{request_id}/reject` — `core/enterprise_dashboard/routes/provisioning.py:158`
- Candidate calls: `api_provisioning_report`, `get_report`, `report`
## `/api/v1/admin/test-dispatch-signal` — `core/enterprise_dashboard/routes/admin.py:23`
- Candidate calls: none identified
## `/api/v1/admin/test-email` — `core/enterprise_dashboard/routes/admin.py:205`
- Candidate calls: none identified
## `/api/system/self-test` — `core/enterprise_dashboard/routes/admin.py:560`
- Candidate calls: none identified
## `/api/v1/admin/generate-report` — `core/enterprise_dashboard/routes/admin.py:743`
- Candidate calls: `api_generate_report`, `generate_report`, `get_report_builder`
## `/api/intelligence/presentation/generate-all` — `core/enterprise_dashboard/routes/intelligence.py:479`
- Candidate calls: `get_last_report`
## `/api/intelligence/synthetic-monitor/run` — `core/enterprise_dashboard/routes/intelligence.py:513`
- Candidate calls: `get_last_report`
## `/api/intelligence/sbom/generate` — `core/enterprise_dashboard/routes/intelligence.py:550`
- Candidate calls: `get_last_report`
## `/api/intelligence/chaos/run` — `core/enterprise_dashboard/routes/intelligence.py:583`
- Candidate calls: `api_ai_gate_report`, `get_last_report`, `get_report`
## `/api/intelligence/ai-gate/analyze-prompt` — `core/enterprise_dashboard/routes/intelligence.py:618`
- Candidate calls: `api_ai_gate_report`, `get_report`
## `/api/intelligence/ai-gate/analyze-response` — `core/enterprise_dashboard/routes/intelligence.py:648`
- Candidate calls: `api_ai_gate_report`, `get_report`
## `/api/intelligence/threat-model/analyze` — `core/enterprise_dashboard/routes/intelligence.py:714`
- Candidate calls: `api_postmortem_report`, `get_report`
## `/api/intelligence/postmortem/generate` — `core/enterprise_dashboard/routes/intelligence.py:766`
- Candidate calls: `api_postmortem_report`, `get_report`
## `/api/intelligence/decisions/record` — `core/enterprise_dashboard/routes/intelligence.py:849`
- Candidate calls: `api_decision_report`, `get_report`
## `/api/intelligence/digital-twin/snapshot` — `core/enterprise_dashboard/routes/intelligence.py:961`
- Candidate calls: `api_versioning_report`, `get_api_version_manager`, `get_report`
## `/api/intelligence/runtime-security/check` — `core/enterprise_dashboard/routes/intelligence.py:1020`
- Candidate calls: `api_versioning_report`, `get_api_version_manager`, `get_report`
## `/api/intelligence/executive/briefing` — `core/enterprise_dashboard/routes/intelligence.py:1080`
- Candidate calls: none identified
## `/api/intelligence/accessibility/assess` — `core/enterprise_dashboard/routes/intelligence.py:1118`
- Candidate calls: none identified
## `/api/intelligence/ml/retrain` — `core/enterprise_dashboard/routes/intelligence.py:1147`
- Candidate calls: none identified
## `/api/payoff-calculator/compute` — `core/enterprise_dashboard/routes/payoff_calculator.py:69`
- Candidate calls: none identified
## `/api/intelligence/security/scan` — `core/enterprise_dashboard/routes/intelligence_bi.py:103`
- Candidate calls: `api_architecture_last_report`, `api_performance_last_report`, `api_security_last_report`
## `/api/intelligence/performance/analyze` — `core/enterprise_dashboard/routes/intelligence_bi.py:139`
- Candidate calls: `api_architecture_last_report`, `api_performance_last_report`
## `/api/intelligence/architecture/analyze` — `core/enterprise_dashboard/routes/intelligence_bi.py:175`
- Candidate calls: `api_architecture_last_report`
## `/api/intelligence/recommendations/generate` — `core/enterprise_dashboard/routes/intelligence_bi.py:218`
- Candidate calls: none identified
## `/api/intelligence/presentation/generate` — `core/enterprise_dashboard/routes/intelligence_bi.py:260`
- Candidate calls: none identified
## `/api/fundamentals/weights` — `core/enterprise_dashboard/routes/fundamentals.py:52`
- Candidate calls: `api_fundamentals_weights_update`, `set_weights`
## `/api/fundamentals/screen` — `core/enterprise_dashboard/routes/fundamentals.py:147`
- Candidate calls: `set_weights`
## `/api/v1/trade/paper-trade` — `core/enterprise_dashboard/routes/monitoring.py:70`
- Candidate calls: none identified
## `/api/system/notifications/{notif_id}/acknowledge` — `core/enterprise_dashboard/routes/monitoring.py:104`
- Candidate calls: none identified
## `/api/system/notifications/acknowledge-all` — `core/enterprise_dashboard/routes/monitoring.py:110`
- Candidate calls: none identified
## `/api/system/notifications/push` — `core/enterprise_dashboard/routes/monitoring.py:118`
- Candidate calls: none identified
## `/api/telegram/webhook` — `core/enterprise_dashboard/routes/monitoring.py:440`
- Candidate calls: none identified
## `/api/v1/push/subscribe` — `core/enterprise_dashboard/routes/monitoring.py:469`
- Candidate calls: none identified
## `/api/copier/execute` — `core/enterprise_dashboard/routes/monitoring.py:493`
- Candidate calls: none identified
## `/api/intelligence/root-cause/investigate` — `core/enterprise_dashboard/routes/intelligence_analysis.py:72`
- Candidate calls: `api_knowledge_report`, `get_report`
## `/api/intelligence/risk-score` — `core/enterprise_dashboard/routes/intelligence_analysis.py:176`
- Candidate calls: `api_dependency_report`
## `/api/intelligence/incidents/create` — `core/enterprise_dashboard/routes/intelligence_incidents.py:48`
- Candidate calls: `api_incidents_create`, `create_incident`
## `/api/intelligence/incidents/acknowledge/{incident_id}` — `core/enterprise_dashboard/routes/intelligence_incidents.py:83`
- Candidate calls: none identified
## `/api/intelligence/incidents/resolve/{incident_id}` — `core/enterprise_dashboard/routes/intelligence_incidents.py:96`
- Candidate calls: none identified
## `/api/intelligence/incidents/close/{incident_id}` — `core/enterprise_dashboard/routes/intelligence_incidents.py:109`
- Candidate calls: none identified
## `/api/intelligence/incidents/detect` — `core/enterprise_dashboard/routes/intelligence_incidents.py:122`
- Candidate calls: none identified
## `/signals/inject` — `core/enterprise_dashboard/routes/webhooks.py:71`
- Candidate calls: none identified
## `/api/intelligence/test-generator/analyze` — `core/enterprise_dashboard/routes/intelligence_pipeline.py:22`
- Candidate calls: none identified
## `/api/intelligence/docs/generate` — `core/enterprise_dashboard/routes/intelligence_pipeline.py:51`
- Candidate calls: none identified
## `/api/intelligence/pipeline/run` — `core/enterprise_dashboard/routes/intelligence_pipeline.py:87`
- Candidate calls: none identified