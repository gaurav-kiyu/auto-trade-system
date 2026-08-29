# OPB WEB CLOSURE WIP78 — Indirect Audit Trace

State-changing route declarations: 174
Direct audit evidence: 43
Routes without direct audit evidence: 131

These routes require deeper service/repository tracing before being called unaudited.

## `/login` — `tests/test_auth_comprehensive.py:167`
Potential service/repository calls:
- `user_obj = handler.authenticate(uname, pwd, ip)`
- `token = handler.create_session(user_obj, ip, "pytest")`
- `def deps_client(handler: Any) -> Any:`
- `Returns (client, handler, deps) tuple.`
- `app, deps = _build_test_app(handler)`
- `_add_login_route(app, handler)`
- `return TestClient(app), handler, deps`
- `from core.auth.handler import hash_password, verify_password`
- `from core.auth.handler import hash_password`
- `from core.auth.handler import hash_password, verify_password`
- `from core.auth.handler import verify_password`
- `from core.auth.handler import hash_password, verify_password`
- `from core.auth.handler import hash_password, verify_password`
- `from core.auth.handler import PBKDF2_ITERATIONS, hash_password`
- `from core.auth.handler import hash_password, verify_password`
- `from core.auth.handler import validate_password_strength`
- `from core.auth.handler import validate_password_strength`
- `from core.auth.handler import validate_password_strength`
- `from core.auth.handler import validate_password_strength`
- `from core.auth.handler import validate_password_strength`
## `/signals/{signal_id}/mark-order-placed` — `tests/test_admin_signal_rbac_contract.py:17`
- No obvious service/repository call in the immediate neighborhood.
## `/chat` — `archive/unrelated_modules/realestate/ai_chatbot.py:372`
- No obvious service/repository call in the immediate neighborhood.
## `/projects` — `archive/unrelated_modules/realestate/builder_portal.py:368`
- No obvious service/repository call in the immediate neighborhood.
## `/projects/{project_id}/units` — `archive/unrelated_modules/realestate/builder_portal.py:404`
- No obvious service/repository call in the immediate neighborhood.
## `/projects/{project_id}/units/bulk` — `archive/unrelated_modules/realestate/builder_portal.py:409`
- No obvious service/repository call in the immediate neighborhood.
## `/projects/{project_id}/units/{unit_id}/book` — `archive/unrelated_modules/realestate/builder_portal.py:425`
- No obvious service/repository call in the immediate neighborhood.
## `/projects/{project_id}/status` — `archive/unrelated_modules/realestate/builder_portal.py:436`
- No obvious service/repository call in the immediate neighborhood.
## `/check-property` — `archive/unrelated_modules/realestate/fraud_detection.py:459`
- No obvious service/repository call in the immediate neighborhood.
## `/check-enquiry` — `archive/unrelated_modules/realestate/fraud_detection.py:482`
- No obvious service/repository call in the immediate neighborhood.
## `/blacklist/phone` — `archive/unrelated_modules/realestate/fraud_detection.py:492`
- No obvious service/repository call in the immediate neighborhood.
## `/blacklist/user` — `archive/unrelated_modules/realestate/fraud_detection.py:497`
- No obvious service/repository call in the immediate neighborhood.
## `/moderation/{property_id}/approve` — `archive/unrelated_modules/realestate/admin_panel.py:372`
- No obvious service/repository call in the immediate neighborhood.
## `/moderation/{property_id}/reject` — `archive/unrelated_modules/realestate/admin_panel.py:379`
- No obvious service/repository call in the immediate neighborhood.
## `/reports` — `archive/unrelated_modules/realestate/admin_panel.py:387`
- No obvious service/repository call in the immediate neighborhood.
## `/reports/{report_id}/resolve` — `archive/unrelated_modules/realestate/admin_panel.py:404`
- No obvious service/repository call in the immediate neighborhood.
## `/kyc/submit` — `archive/unrelated_modules/realestate/admin_panel.py:416`
- No obvious service/repository call in the immediate neighborhood.
## `/kyc/{user_id}/verify` — `archive/unrelated_modules/realestate/admin_panel.py:423`
- No obvious service/repository call in the immediate neighborhood.
## `/{property_id}` — `archive/unrelated_modules/realestate/saved_properties.py:120`
- No obvious service/repository call in the immediate neighborhood.
## `/{property_id}` — `archive/unrelated_modules/realestate/saved_properties.py:130`
- No obvious service/repository call in the immediate neighborhood.
## `/predict` — `archive/unrelated_modules/realestate/ml_prediction.py:405`
- No obvious service/repository call in the immediate neighborhood.
## `/predict/train` — `archive/unrelated_modules/realestate/ml_prediction.py:436`
- No obvious service/repository call in the immediate neighborhood.
## `/tasks/{task_id}/run` — `archive/unrelated_modules/realestate/scheduler.py:425`
- No obvious service/repository call in the immediate neighborhood.
## `/run-all` — `archive/unrelated_modules/realestate/scheduler.py:441`
- No obvious service/repository call in the immediate neighborhood.
## `/tasks/{task_id}/toggle` — `archive/unrelated_modules/realestate/scheduler.py:479`
- No obvious service/repository call in the immediate neighborhood.
## `/import` — `archive/unrelated_modules/realestate/export_import.py:319`
Potential service/repository calls:
- `raise HTTPException(status_code=503, detail="Property service not available")`
- `raise HTTPException(status_code=503, detail="Property service not available")`
## `/orders` — `archive/unrelated_modules/realestate/payments.py:463`
Potential service/repository calls:
- `"""Get payment service statistics."""`
## `/verify` — `archive/unrelated_modules/realestate/payments.py:480`
Potential service/repository calls:
- `"""Get payment service statistics."""`
## `/offline` — `archive/unrelated_modules/realestate/payments.py:492`
Potential service/repository calls:
- `"""Get payment service statistics."""`
## `/refund` — `archive/unrelated_modules/realestate/payments.py:526`
Potential service/repository calls:
- `"""Get payment service statistics."""`
## `/webhook` — `archive/unrelated_modules/realestate/payments.py:537`
Potential service/repository calls:
- `"""Get payment service statistics."""`
## `/google` — `archive/unrelated_modules/realestate/auth_service.py:389`
- No obvious service/repository call in the immediate neighborhood.
## `/guest` — `archive/unrelated_modules/realestate/auth_service.py:400`
- No obvious service/repository call in the immediate neighborhood.
## `/logout` — `archive/unrelated_modules/realestate/auth_service.py:406`
- No obvious service/repository call in the immediate neighborhood.
## `/{notification_id}/read` — `archive/unrelated_modules/realestate/notifications.py:395`
- No obvious service/repository call in the immediate neighborhood.
## `/mark-all-read` — `archive/unrelated_modules/realestate/notifications.py:401`
- No obvious service/repository call in the immediate neighborhood.
## `/{notification_id}` — `archive/unrelated_modules/realestate/notifications.py:407`
- No obvious service/repository call in the immediate neighborhood.
## `/saved-searches` — `archive/unrelated_modules/realestate/notifications.py:413`
- No obvious service/repository call in the immediate neighborhood.
## `/add` — `archive/unrelated_modules/realestate/comparison.py:163`
- No obvious service/repository call in the immediate neighborhood.
## `/remove` — `archive/unrelated_modules/realestate/comparison.py:172`
- No obvious service/repository call in the immediate neighborhood.
## `/clear` — `archive/unrelated_modules/realestate/comparison.py:189`
- No obvious service/repository call in the immediate neighborhood.
## `/register` — `archive/unrelated_modules/realestate/rera_compliance.py:349`
- No obvious service/repository call in the immediate neighborhood.
## `/register` — `archive/unrelated_modules/realestate/webhooks.py:348`
- No obvious service/repository call in the immediate neighborhood.
## `/{endpoint_id}` — `archive/unrelated_modules/realestate/webhooks.py:359`
- No obvious service/repository call in the immediate neighborhood.
## `/test/{event_type}` — `archive/unrelated_modules/realestate/webhooks.py:371`
- No obvious service/repository call in the immediate neighborhood.
## `/payments` — `archive/unrelated_modules/realestate/tenant_portal.py:340`
- No obvious service/repository call in the immediate neighborhood.
## `/maintenance` — `archive/unrelated_modules/realestate/tenant_portal.py:370`
- No obvious service/repository call in the immediate neighborhood.
## `/maintenance/{request_id}/status` — `archive/unrelated_modules/realestate/tenant_portal.py:395`
- No obvious service/repository call in the immediate neighborhood.
## `/properties` — `archive/unrelated_modules/realestate/api/__init__.py:95`
- No obvious service/repository call in the immediate neighborhood.
## `/properties/{property_id}/media` — `archive/unrelated_modules/realestate/api/__init__.py:164`
- No obvious service/repository call in the immediate neighborhood.
## `/properties/{property_id}` — `archive/unrelated_modules/realestate/api/__init__.py:177`
- No obvious service/repository call in the immediate neighborhood.
## `/leads` — `archive/unrelated_modules/realestate/api/__init__.py:224`
- No obvious service/repository call in the immediate neighborhood.
## `/leads/{lead_id}/status` — `archive/unrelated_modules/realestate/api/__init__.py:245`
- No obvious service/repository call in the immediate neighborhood.
## `/enquiries` — `archive/unrelated_modules/realestate/api/__init__.py:253`
- No obvious service/repository call in the immediate neighborhood.
## `/agreements/rent` — `archive/unrelated_modules/realestate/api/__init__.py:275`
- No obvious service/repository call in the immediate neighborhood.
## `/agreements/rent/{agreement_id}/e-stamp` — `archive/unrelated_modules/realestate/api/__init__.py:306`
- No obvious service/repository call in the immediate neighborhood.
## `/agreements/rent/{agreement_id}/e-sign` — `archive/unrelated_modules/realestate/api/__init__.py:314`
- No obvious service/repository call in the immediate neighborhood.
## `/{auction_id}/bid` — `archive/unrelated_modules/realestate/auction/engine.py:506`
- No obvious service/repository call in the immediate neighborhood.
## `/{auction_id}/buy-it-now` — `archive/unrelated_modules/realestate/auction/engine.py:523`
- No obvious service/repository call in the immediate neighborhood.
## `/{auction_id}/start` — `archive/unrelated_modules/realestate/auction/engine.py:534`
- No obvious service/repository call in the immediate neighborhood.
## `/{auction_id}/close` — `archive/unrelated_modules/realestate/auction/engine.py:540`
- No obvious service/repository call in the immediate neighborhood.
## `/register` — `core/auth/routes.py:137`
- No obvious service/repository call in the immediate neighborhood.
## `/login` — `core/auth/routes.py:225`
- No obvious service/repository call in the immediate neighborhood.
## `/logout` — `core/auth/routes.py:283`
- No obvious service/repository call in the immediate neighborhood.
## `/profile` — `core/auth/routes.py:349`
- No obvious service/repository call in the immediate neighborhood.
## `/change-password` — `core/auth/routes.py:389`
- No obvious service/repository call in the immediate neighborhood.
## `/users` — `core/auth/routes.py:422`
- No obvious service/repository call in the immediate neighborhood.
## `/users/{username}/role` — `core/auth/routes.py:483`
- No obvious service/repository call in the immediate neighborhood.
## `/users/{username}/reset-password` — `core/auth/routes.py:519`
- No obvious service/repository call in the immediate neighborhood.
## `/users/{username}/disable` — `core/auth/routes.py:536`
- No obvious service/repository call in the immediate neighborhood.
## `/users/{username}/enable` — `core/auth/routes.py:548`
- No obvious service/repository call in the immediate neighborhood.
## `/users/{username}` — `core/auth/routes.py:559`
- No obvious service/repository call in the immediate neighborhood.
## `/mfa/setup` — `core/auth/routes.py:884`
- No obvious service/repository call in the immediate neighborhood.
## `/mfa/verify` — `core/auth/routes.py:921`
- No obvious service/repository call in the immediate neighborhood.
## `/mfa/disable` — `core/auth/routes.py:956`
- No obvious service/repository call in the immediate neighborhood.
## `/mfa/verify-session` — `core/auth/routes.py:1005`
- No obvious service/repository call in the immediate neighborhood.
## `/forgot-password` — `core/auth/routes.py:1174`
Potential service/repository calls:
- `"""Emergency self-service password reset using master recovery key."""`
## `/verify-reset-token` — `core/auth/routes.py:1193`
Potential service/repository calls:
- `"""Emergency self-service password reset using master recovery key."""`
## `/reset-password` — `core/auth/routes.py:1209`
Potential service/repository calls:
- `"""Emergency self-service password reset using master recovery key."""`
## `/emergency-reset-password` — `core/auth/routes.py:1222`
Potential service/repository calls:
- `"""Emergency self-service password reset using master recovery key."""`
## `/logout` — `core/enterprise_dashboard/main.py:458`
- No obvious service/repository call in the immediate neighborhood.
## `/api/governance/request` — `core/enterprise_dashboard/routes/governance.py:157`
- No obvious service/repository call in the immediate neighborhood.
## `/api/governance/approve` — `core/enterprise_dashboard/routes/governance.py:189`
- No obvious service/repository call in the immediate neighborhood.
## `/api/governance/reject` — `core/enterprise_dashboard/routes/governance.py:218`
- No obvious service/repository call in the immediate neighborhood.
## `/api/platform/provisioning/request` — `core/enterprise_dashboard/routes/provisioning.py:80`
Potential service/repository calls:
- `"""Create a self-service provisioning request (no ops ticket)."""`
- `actor = str(body.get("actor", getattr(user, "username", "self-service")))`
- `"""Get the full self-service provisioning report (admin only)."""`
## `/api/platform/provisioning/requests/{request_id}/approve` — `core/enterprise_dashboard/routes/provisioning.py:119`
Potential service/repository calls:
- `"""Get the full self-service provisioning report (admin only)."""`
## `/api/platform/provisioning/requests/{request_id}/provisioned` — `core/enterprise_dashboard/routes/provisioning.py:139`
Potential service/repository calls:
- `"""Get the full self-service provisioning report (admin only)."""`
## `/api/platform/provisioning/requests/{request_id}/reject` — `core/enterprise_dashboard/routes/provisioning.py:158`
Potential service/repository calls:
- `"""Get the full self-service provisioning report (admin only)."""`
## `/api/v1/admin/test-dispatch-signal` — `core/enterprise_dashboard/routes/admin.py:23`
- No obvious service/repository call in the immediate neighborhood.
## `/api/v1/admin/test-email` — `core/enterprise_dashboard/routes/admin.py:205`
- No obvious service/repository call in the immediate neighborhood.
## `/api/system/self-test` — `core/enterprise_dashboard/routes/admin.py:560`
- No obvious service/repository call in the immediate neighborhood.
## `/api/v1/admin/generate-report` — `core/enterprise_dashboard/routes/admin.py:743`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/presentation/generate-all` — `core/enterprise_dashboard/routes/intelligence.py:479`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/synthetic-monitor/run` — `core/enterprise_dashboard/routes/intelligence.py:513`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/sbom/generate` — `core/enterprise_dashboard/routes/intelligence.py:550`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/chaos/run` — `core/enterprise_dashboard/routes/intelligence.py:583`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/ai-gate/analyze-prompt` — `core/enterprise_dashboard/routes/intelligence.py:618`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/ai-gate/analyze-response` — `core/enterprise_dashboard/routes/intelligence.py:648`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/threat-model/analyze` — `core/enterprise_dashboard/routes/intelligence.py:714`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/postmortem/generate` — `core/enterprise_dashboard/routes/intelligence.py:766`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/decisions/record` — `core/enterprise_dashboard/routes/intelligence.py:849`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/digital-twin/snapshot` — `core/enterprise_dashboard/routes/intelligence.py:961`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/runtime-security/check` — `core/enterprise_dashboard/routes/intelligence.py:1020`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/executive/briefing` — `core/enterprise_dashboard/routes/intelligence.py:1080`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/accessibility/assess` — `core/enterprise_dashboard/routes/intelligence.py:1118`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/ml/retrain` — `core/enterprise_dashboard/routes/intelligence.py:1147`
- No obvious service/repository call in the immediate neighborhood.
## `/api/payoff-calculator/compute` — `core/enterprise_dashboard/routes/payoff_calculator.py:69`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/security/scan` — `core/enterprise_dashboard/routes/intelligence_bi.py:103`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/performance/analyze` — `core/enterprise_dashboard/routes/intelligence_bi.py:139`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/architecture/analyze` — `core/enterprise_dashboard/routes/intelligence_bi.py:175`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/recommendations/generate` — `core/enterprise_dashboard/routes/intelligence_bi.py:218`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/presentation/generate` — `core/enterprise_dashboard/routes/intelligence_bi.py:260`
- No obvious service/repository call in the immediate neighborhood.
## `/api/fundamentals/weights` — `core/enterprise_dashboard/routes/fundamentals.py:52`
- No obvious service/repository call in the immediate neighborhood.
## `/api/fundamentals/screen` — `core/enterprise_dashboard/routes/fundamentals.py:147`
- No obvious service/repository call in the immediate neighborhood.
## `/api/v1/trade/paper-trade` — `core/enterprise_dashboard/routes/monitoring.py:70`
- No obvious service/repository call in the immediate neighborhood.
## `/api/system/notifications/{notif_id}/acknowledge` — `core/enterprise_dashboard/routes/monitoring.py:104`
- No obvious service/repository call in the immediate neighborhood.
## `/api/system/notifications/acknowledge-all` — `core/enterprise_dashboard/routes/monitoring.py:110`
- No obvious service/repository call in the immediate neighborhood.
## `/api/system/notifications/push` — `core/enterprise_dashboard/routes/monitoring.py:118`
- No obvious service/repository call in the immediate neighborhood.
## `/api/telegram/webhook` — `core/enterprise_dashboard/routes/monitoring.py:440`
- No obvious service/repository call in the immediate neighborhood.
## `/api/v1/push/subscribe` — `core/enterprise_dashboard/routes/monitoring.py:469`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/root-cause/investigate` — `core/enterprise_dashboard/routes/intelligence_analysis.py:72`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/risk-score` — `core/enterprise_dashboard/routes/intelligence_analysis.py:176`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/incidents/create` — `core/enterprise_dashboard/routes/intelligence_incidents.py:48`
Potential service/repository calls:
- `("Service Catalog",         "core.service_catalog",         "get_service_catalog"),`
## `/api/intelligence/incidents/acknowledge/{incident_id}` — `core/enterprise_dashboard/routes/intelligence_incidents.py:83`
Potential service/repository calls:
- `("Service Catalog",         "core.service_catalog",         "get_service_catalog"),`
## `/api/intelligence/incidents/resolve/{incident_id}` — `core/enterprise_dashboard/routes/intelligence_incidents.py:96`
Potential service/repository calls:
- `("Service Catalog",         "core.service_catalog",         "get_service_catalog"),`
## `/api/intelligence/incidents/close/{incident_id}` — `core/enterprise_dashboard/routes/intelligence_incidents.py:109`
Potential service/repository calls:
- `("Service Catalog",         "core.service_catalog",         "get_service_catalog"),`
## `/api/intelligence/incidents/detect` — `core/enterprise_dashboard/routes/intelligence_incidents.py:122`
Potential service/repository calls:
- `("Service Catalog",         "core.service_catalog",         "get_service_catalog"),`
## `/signals/inject` — `core/enterprise_dashboard/routes/webhooks.py:71`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/test-generator/analyze` — `core/enterprise_dashboard/routes/intelligence_pipeline.py:22`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/docs/generate` — `core/enterprise_dashboard/routes/intelligence_pipeline.py:51`
- No obvious service/repository call in the immediate neighborhood.
## `/api/intelligence/pipeline/run` — `core/enterprise_dashboard/routes/intelligence_pipeline.py:87`
- No obvious service/repository call in the immediate neighborhood.