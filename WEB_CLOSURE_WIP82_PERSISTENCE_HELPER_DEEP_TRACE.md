# OPB WEB CLOSURE WIP82 — Persistence Helper Deep Trace

Persistence helper candidates discovered: 70
Candidates with direct audit in body: 33

## Candidates
- `_apply_config_change` — `core/enterprise_dashboard/main.py:839` — direct audit: **YES**
- `_audit_log` — `core/auth/handler/handler.py:594` — direct audit: **YES**
- `_check_audit_engine_regression` — `scripts/run_regression.py:113` — direct audit: **YES**
- `_check_hard_stops_via_risk` — `index_app/index_trader.py:1090` — direct audit: **YES**
- `_check_lockout` — `core/auth/handler/handler.py:525` — direct audit: **YES**
- `_check_strategy_data` — `core/audit_mode.py:528` — direct audit: **YES**
- `_cli` — `core/secrets_vault.py:425` — direct audit: **YES**
- `_init_db` — `core/auth/handler/handler.py:70` — direct audit: **YES**
- `_make_service` — `tests/test_trading_loop_service.py:21` — direct audit: **NO**
- `_rollback_config` — `core/enterprise_dashboard/main.py:963` — direct audit: **YES**
- `_write_audit_record` — `tests/test_metrics_trend_routes.py:351` — direct audit: **YES**
- `admin_reset_password` — `core/auth/handler/handler.py:309` — direct audit: **YES**
- `append` — `core/execution/event_system.py:284` — direct audit: **YES**
- `auth_with_user` — `tests/test_auth_handler.py:140` — direct audit: **YES**
- `authenticate` — `core/auth/handler/handler.py:176` — direct audit: **YES**
- `create_user` — `core/auth/handler/handler.py:236` — direct audit: **YES**
- `delete` — `core/secrets_vault.py:258` — direct audit: **YES**
- `delete_user` — `core/auth/handler/handler.py:489` — direct audit: **YES**
- `disable_mfa` — `core/auth/handler/mfa_handler.py:84` — direct audit: **YES**
- `disable_user` — `core/auth/handler/handler.py:465` — direct audit: **YES**
- `enable_mfa` — `core/auth/handler/mfa_handler.py:67` — direct audit: **YES**
- `enable_user` — `core/auth/handler/handler.py:477` — direct audit: **YES**
- `execute_order` — `core/services/execution_service.py:337` — direct audit: **YES**
- `failing_handler` — `tests/test_command_bus.py:117` — direct audit: **NO**
- `failing_handler` — `tests/test_query_bus.py:120` — direct audit: **NO**
- `generate_report` — `core/presentation_generator.py:1030` — direct audit: **NO**
- `get_audit_log` — `core/auth/handler/handler.py:612` — direct audit: **YES**
- `get_stats` — `core/auth/handler/session_manager.py:267` — direct audit: **YES**
- `handler` — `tests/test_cqrs.py:33` — direct audit: **NO**
- `handler` — `tests/test_cqrs.py:124` — direct audit: **NO**
- `handler` — `tests/test_cqrs.py:147` — direct audit: **NO**
- `handler` — `tests/test_query_bus.py:148` — direct audit: **NO**
- `handler` — `tests/test_query_bus.py:172` — direct audit: **NO**
- `handler` — `tests/test_query_bus.py:196` — direct audit: **NO**
- `import_score_system` — `tests/test_score_system.py:25` — direct audit: **YES**
- `main` — `scripts/release_governance.py:713` — direct audit: **YES**
- `manager` — `tests/test_config_domain_manager.py:21` — direct audit: **NO**
- `register_service` — `core/service_catalog.py:231` — direct audit: **NO**
- `reset_vault` — `tests/test_secrets_vault.py:10` — direct audit: **YES**
- `run_cycle` — `tests/test_production_extensions.py:118` — direct audit: **YES**
- `test_adapter_context_manager` — `tests/test_end_to_end.py:93` — direct audit: **NO**
- `test_alert_manager_tracks_mode` — `tests/test_catastrophic_scenarios.py:185` — direct audit: **NO**
- `test_audit_log_on_delete` — `tests/test_auth_comprehensive.py:906` — direct audit: **YES**
- `test_context_manager` — `tests/test_database_duckdb_adapter.py:59` — direct audit: **NO**
- `test_context_manager` — `tests/test_database_mongodb_adapter.py:98` — direct audit: **NO**
- `test_context_manager` — `tests/test_database_mysql_adapter.py:119` — direct audit: **NO**
- `test_context_manager` — `tests/test_database_postgres_adapter.py:128` — direct audit: **NO**
- `test_context_manager` — `tests/test_database_redis_adapter.py:108` — direct audit: **NO**
- `test_context_manager` — `tests/test_database_sqlalchemy_adapter.py:59` — direct audit: **NO**
- `test_context_manager_execute_inside` — `tests/test_database_port.py:233` — direct audit: **NO**
- `test_decorator_handler` — `tests/test_cqrs.py:40` — direct audit: **NO**
- `test_decorator_handler` — `tests/test_cqrs.py:155` — direct audit: **NO**
- `test_dry_run_reports_table_details` — `tests/test_pg_migration.py:521` — direct audit: **NO**
- `test_execute_handler_error` — `tests/test_command_bus.py:113` — direct audit: **NO**
- `test_execute_handler_error` — `tests/test_query_bus.py:116` — direct audit: **NO**
- `test_execute_no_handler` — `tests/test_command_bus.py:106` — direct audit: **NO**
- `test_execute_no_handler` — `tests/test_query_bus.py:109` — direct audit: **NO**
- `test_init_creates_tables` — `tests/test_auth_handler.py:165` — direct audit: **YES**
- `test_multiple_handlers` — `tests/test_query_bus.py:128` — direct audit: **NO**
- `test_no_handler` — `tests/test_cqrs.py:52` — direct audit: **NO**
- `test_no_handler` — `tests/test_cqrs.py:168` — direct audit: **NO**
- `test_register_handler` — `tests/test_cqrs.py:27` — direct audit: **NO**
- `test_register_handler` — `tests/test_cqrs.py:142` — direct audit: **NO**
- `test_report_with_commits` — `tests/test_engineering_analytics.py:59` — direct audit: **NO**
- `test_unregister_handler` — `tests/test_cqrs.py:120` — direct audit: **NO**
- `test_wire_default_services_handles_import_errors_gracefully` — `tests/test_di_container.py:601` — direct audit: **NO**
- `unregister_service` — `core/service_catalog.py:242` — direct audit: **NO**
- `update_password` — `core/auth/handler/handler.py:283` — direct audit: **YES**
- `update_user_permissions` — `core/auth/routes.py:662` — direct audit: **YES**
- `update_user_role` — `core/auth/handler/handler.py:448` — direct audit: **YES**

## Repair rule
Where a persistence helper changes durable state and has no proven downstream audit boundary, the audit must be added at the shared transactional service boundary rather than duplicated across controllers.
