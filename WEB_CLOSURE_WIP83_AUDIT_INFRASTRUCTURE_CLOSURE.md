# OPB WEB CLOSURE WIP83 — Audit Infrastructure Closure

Files containing audit infrastructure: 244
Audit-related definitions discovered: 621
Callable audit/event writers discovered: 370

## Existing audit/event writers
- `core/adaptive_behavior_governance.py` — `_init_audit_log(self)`
- `core/threat_modeler.py` — `_load_history(self)`
- `core/change_management.py` — `get_audit_log(self, n: int = 50)`
- `core/change_management.py` — `_record_audit(self, change_id: str, action: str, actor: str, details: str = "")`
- `core/root_cause_analyzer.py` — `get_incident_history(self,
        incident_type: str | None = None,
        limit: int = 50,)`
- `core/root_cause_analyzer.py` — `clear_history(self)`
- `core/root_cause_analyzer.py` — `_load_history(self)`
- `core/ai_security_gate.py` — `clear_audit(self)`
- `core/ai_security_gate.py` — `_load_audit(self)`
- `core/ai_security_gate.py` — `get_ai_security_gate()`
- `core/ai_security_gate.py` — `reset_ai_security_gate()`
- `core/config_helpers.py` — `build_audit_config_snapshot(cfg: dict[str, Any])`
- `core/quality_gates.py` — `get_history(self, limit: int = 20)`
- `core/quality_gates.py` — `_score_security(self, result: QGResult, files: list[str])`
- `core/quality_gates.py` — `_load_history(self)`
- `core/quality_gates.py` — `_save_history(self)`
- `core/audit_mode.py` — `run_full_audit(self)`
- `core/audit_mode.py` — `audit_security(self)`
- `core/audit_mode.py` — `get_auditor()`
- `core/audit_mode.py` — `run_audit(scope: str = "all")`
- `core/config_audit_log.py` — `format_config_audit_log_line(timestamp_iso: str, key: str, old: object, new: object)`
- `core/config_audit_log.py` — `append_soft_reload_audit_diff(audit_log_path: str | pathlib.Path,
    diff_log: Sequence[Mapping[str, object]],
    *,
    now_iso: Callable[[], str],)`
- `core/health_reporter.py` — `run_weekly_audit(self)`
- `core/all_nse_scanner.py` — `_log_signal_audit_record(self,
        signal: ScannedStockSignal,
        category: str,
        threshold_applied: int,
        decision: str,  # "ACCEPTED" or "NO_TRADE"
        rejection_reason: str = "",)`
- `core/operating_mode.py` — `get_history(self)`
- `core/audit_journal.py` — `_get_event_id(self)`
- `core/audit_journal.py` — `log_event(self,
        event_type: AuditEventType,
        severity: AuditSeverity,
        message: str,
        correlation_id: str = "",
        intent_id: str = "",
        symbol: str = "",
        details: dict[str, Any] | None = None,
        stack_trace: str = "",)`
- `core/audit_journal.py` — `get_audit_journal(config: dict | None = None)`
- `core/runtime_security.py` — `get_runtime_security()`
- `core/runtime_security.py` — `reset_runtime_security()`
- `core/continuous_intelligence.py` — `_load_history(self)`
- `core/continuous_intelligence.py` — `_save_history(self)`
- `core/continuous_intelligence.py` — `get_history(self, limit: int = 10)`
- `core/ics_self_healing_bridge.py` — `_record_handler_event(self, action_name: str, component: str, status: str, message: str,)`
- `core/ics_self_healing_bridge.py` — `get_history(self, limit: int = 20)`
- `core/data_governance.py` — `_prune_signal_history(self)`
- `core/bias_detector.py` — `get_history(self, limit: int = 10)`
- `core/bias_detector.py` — `clear_history(self)`
- `core/bias_detector.py` — `_record_history(self, report: BiasReport)`
- `core/bias_detector.py` — `_load_history(self)`
- `core/security_auditor.py` — `get_security_auditor()`
- `core/security_auditor.py` — `reset_security_auditor()`
- `core/constitution_ai_gate.py` — `_audit(self, action: str, result: str, detail: AIGateResult)`
- `core/constitution_ai_gate.py` — `get_audit_log(self, limit: int = 100)`
- `core/secrets_vault.py` — `get_audit_log(self, limit: int = 50, action: str = "")`
- `core/secrets_vault.py` — `_audit(self, action: str, key: str, success: bool, detail: str = "")`
- `core/secrets_vault.py` — `_persist_audit(self)`
- `core/enterprise_evolution.py` — `_analyze_security(self, evidence: dict[str, Any])`
- `core/enterprise_evolution.py` — `_persist_history(self)`
- `core/enterprise_evolution.py` — `_load_history(self)`
- `index_app/index_trader.py` — `_get_trade_history_snapshot()`
- `scripts/release_governance.py` — `write_audit_record(version: str, branch: str, changes: list[str] | None = None,
                       trend_snapshot_captured: bool = False,
                       register_gate_passed: bool | None = None,
                       register_gate_status: str = "unknown")`
- `scripts/e2e_integration_test.py` — `test_audit()`
- `scripts/run_regression.py` — `_check_audit_engine_regression()`
- `scripts/pre_implementation_check.py` — `check_git_history(count: int = 10)`
- `scripts/run_v5_v6_empirical_calibration_audit.py` — `run_empirical_audit()`
- `scripts/run_pr_audit.py` — `run_audit(quick: bool = False)`
- `scripts/run_coverage_heatmap.py` — `_load_history()`
- `scripts/run_coverage_heatmap.py` — `_save_history(heatmap: dict[str, Any])`
- `scratch/test_all_app_routes.py` — `run_comprehensive_route_audit()`
- `scratch/generate_final_deliverables.py` — `generate_audit_pdf()`
- `scratch/test_page_routes_only.py` — `run_page_audit()`
- `tests/test_forensic_audit_fixes.py` — `test_setup_graceful_shutdown_returns_event()`
- `tests/test_wip72_rbac_enforcement.py` — `test_audit_concept_exists()`
- `tests/test_secrets_vault.py` — `test_audit_log(self, reset_vault)`
- `tests/test_secrets_vault.py` — `test_audit_failed_get(self, reset_vault)`
- `tests/test_secrets_vault.py` — `test_audit_rotate(self, reset_vault)`
- `tests/test_event_system.py` — `test_append_event(self, event_store)`
- `tests/test_event_system.py` — `test_get_events_for_order(self, event_store)`
- `tests/test_event_system.py` — `test_get_events_for_order_nonexistent(self, event_store)`
- `tests/test_event_system.py` — `test_get_events_by_type(self, event_store)`
- `tests/test_event_system.py` — `test_get_events_by_type_empty(self, event_store)`
- `tests/test_event_system.py` — `test_get_events_by_type_with_limit(self, event_store)`
- `tests/test_event_system.py` — `test_get_events_in_range(self, event_store)`
- `tests/test_event_system.py` — `test_get_events_in_range_empty(self, event_store)`
- `tests/test_event_system.py` — `test_get_events_for_order_error(self, event_store)`
- `tests/test_event_system.py` — `test_get_events_by_type_error(self, event_store)`
- `tests/test_event_system.py` — `test_get_events_in_range_error(self, event_store)`
- `tests/test_event_system.py` — `test_get_recent_events(self, event_bus)`
- `tests/test_event_system.py` — `test_get_recent_events_empty(self, event_bus)`
- `tests/test_event_system.py` — `test_event_history_max_size(self, event_bus)`
- `tests/test_event_system.py` — `test_verify_chain_single_event(self, event_store)`
- `tests/test_event_system.py` — `test_verify_chain_multiple_events(self, event_store)`
- `tests/test_event_system.py` — `test_verify_chain_detects_tampered_event_type(self, event_store)`
- `tests/test_event_system.py` — `test_get_event_bus_returns_bus(self)`
- `tests/test_event_system.py` — `test_get_event_bus_singleton(self)`
- `tests/test_event_system.py` — `test_get_event_store_returns_store(self)`
- `tests/test_event_system.py` — `test_get_event_store_singleton(self)`
- `tests/test_event_system.py` — `test_get_event_store_from_bus(self)`
- `tests/test_wip78_audit_indirect_trace.py` — `test_universal_audit_contract_remains()`
- `tests/test_operational_hardening.py` — `test_audit_engine_writes_jsonl(tmp_path)`
- `tests/test_wip80_audit_service_chain.py` — `test_universal_audit_gate_is_preserved()`
- `tests/test_wip67_registration_direct_calls.py` — `test_registration_has_auditable_access_concepts()`
- `tests/test_smoke_execution_hardening.py` — `test_log_event(self)`
- `tests/test_enterprise_dashboard.py` — `test_lifespan_events(self, state_file: str, trades_db: str, config_file: str, defaults_file: str)`
- `tests/test_enterprise_dashboard.py` — `test_apply_creates_audit_trail(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_history_returns_backups(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_history_sorted_newest_first(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_history_empty(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_history_handles_bad_filenames(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_history_triggers_valueerror(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_audit_log_returns_recorded_entries_newest_first(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_audit_log_includes_rollback_entries(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_audit_log_empty_when_no_file(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_audit_log_respects_limit(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_log_config_audit_writes_file(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_log_config_audit_append(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_log_audit_write_error_does_not_raise(self)`
- `tests/test_enterprise_dashboard.py` — `test_apply_creates_audit_log(self, tmp_path)`
- `tests/test_enterprise_dashboard.py` — `test_audit_log_error_does_not_crash(self, monkeypatch)`
- `tests/test_enterprise_dashboard.py` — `test_config_history_with_auth(self, admin_client: TestClient)`
- `tests/test_enterprise_dashboard.py` — `test_api_config_history_internal(self, dashboard)`
- `tests/test_enterprise_dashboard.py` — `test_security_page_requires_login(self, mock_templates, no_csrf, admin_auth)`
- `tests/test_enterprise_dashboard.py` — `test_security_page_blocks_non_admin(self, mock_templates, no_csrf, admin_auth)`
- `tests/test_enterprise_dashboard.py` — `test_security_page_allows_admin(self, mock_templates, no_csrf, admin_auth)`
- `tests/test_wip82_persistence_helper_trace.py` — `test_audit_contract_is_retained()`
- `tests/test_ai_governance.py` — `test_audit_log_records_actions(self, governance_with_model)`
- `tests/test_ai_governance.py` — `test_audit_log_approval(self, governance_with_model)`
- `tests/test_ai_governance.py` — `test_audit_log_promotion(self, governance_with_model)`
- `tests/test_ai_governance.py` — `test_audit_log_rollback(self, governance_with_model)`
- `tests/test_ai_governance.py` — `test_audit_log_limit(self, governance_with_model)`
- `tests/test_ai_governance.py` — `test_audit_log_thread_safety(self, governance)`
- `tests/test_auth_register.py` — `test_register_creates_audit_log(self, client, auth_handler)`
- `tests/test_hardening_improvements.py` — `test_record_returns_audit_record(self, tmp_path)`
- `tests/test_hardening_improvements.py` — `test_audit_severity_constants_complete(self)`
- `tests/test_health_reporter.py` — `test_run_weekly_audit_success(self)`
- `tests/test_health_reporter.py` — `test_run_weekly_audit_failure(self)`
- `tests/test_data_governance.py` — `test_summary_includes_signals_history_entry(self, minimal_cfg: dict)`
- `tests/test_data_governance.py` — `test_stop_sets_event(self, mock_governor: MagicMock)`
- `tests/test_wip74_setup_config_workflow.py` — `test_audit_and_notification_are_mandatory()`
- `tests/test_dashboard_api.py` — `test_kill_and_resume_write_kill_switch_audit_entries(self, dashboard, admin_client: TestClient)`
- `tests/test_ai_safety_gate.py` — `test_get_audit_log(self)`
- `tests/test_audit_journal.py` — `test_log_event_returns_event_id(self, journal: AuditJournal)`
- `tests/test_audit_journal.py` — `test_log_event_writes_to_file(self, journal: AuditJournal)`
- `tests/test_audit_journal.py` — `test_log_event_with_details(self, journal: AuditJournal)`
- `tests/test_audit_journal.py` — `test_log_event_with_trace_ids(self, journal: AuditJournal)`
- `tests/test_audit_journal.py` — `test_append_multiple_events(self, journal: AuditJournal)`
- `tests/test_audit_journal.py` — `test_concurrent_log_events(self, tmp_path: Path)`
- `tests/test_audit_journal.py` — `write_events()`
- `tests/test_audit_journal.py` — `test_concurrent_different_event_types(self, tmp_path: Path)`
- `tests/test_audit_journal.py` — `test_get_audit_journal_returns_instance(self, tmp_path: Path)`
- `tests/test_audit_journal.py` — `test_get_audit_journal_singleton(self, tmp_path: Path)`
- `tests/test_audit_journal.py` — `test_audit_log_function(self, tmp_path: Path)`
- `tests/test_thread_safety_integration.py` — `test_reentrant_audit_engine()`
- `tests/test_thread_safety_integration.py` — `test_reentrant_event_calendar()`
- `tests/test_thread_safety_integration.py` — `test_concurrent_audit_engine()`
- `tests/test_thread_safety_integration.py` — `write_event(idx: int)`
- `tests/test_wip79_audit_callchain_map.py` — `test_universal_audit_contract_remains_hard_gate()`
- `tests/test_metrics_trend_routes.py` — `_write_audit_record(tmp_path: Path, filename: str, **fields: dict)`
- `tests/test_metrics_trend_routes.py` — `test_release_audits_surfaces_register_gate(client: TestClient, monkeypatch,
                                               tmp_path: Path)`
- `tests/test_metrics_trend_routes.py` — `test_release_audits_legacy_records_default_unknown(client: TestClient,
                                                       monkeypatch,
                                                       tmp_path: Path)`
- `tests/test_metrics_trend_routes.py` — `test_release_audits_drift_verdict(client: TestClient, monkeypatch,
                                      tmp_path: Path)`
- `tests/test_metrics_trend_routes.py` — `test_audit_dir_resolves_to_repo_logs_audit()`
- `tests/test_metrics_trend_routes.py` — `test_release_audits_empty_when_no_records(client: TestClient, monkeypatch,
                                              tmp_path: Path)`
- `tests/test_metrics_trend_routes.py` — `test_release_audits_sorted_newest_first(client: TestClient, monkeypatch,
                                            tmp_path: Path)`
- `tests/test_constitution.py` — `test_needs_9_audit_threshold(self)`
- `tests/test_constitution.py` — `test_needs_95_audit_threshold(self)`
- `tests/test_constitution.py` — `test_add_audit(self)`
- `tests/test_constitution.py` — `test_add_duplicate_audit(self)`
- `tests/test_constitution.py` — `test_security_audit_trails(self)`
- `tests/test_constitution.py` — `test_score_above_9_5_requires_audits(self)`
- `tests/test_constitution.py` — `test_score_above_9_5_with_audits_passes(self)`
- `tests/test_constitution.py` — `test_audit_log_records_actions(self)`
- `tests/test_constitution.py` — `test_audit_log_limit(self)`
- `tests/test_constitution.py` — `test_audit_log_change_pipeline(self)`
- `tests/test_constitution.py` — `test_audit_log_pre_implementation(self)`
- `tests/test_constitution.py` — `test_security_standard_implemented(self)`
- `tests/test_constitution.py` — `test_security_standard_not_implemented(self)`
- `tests/test_constitution.py` — `test_unknown_security_standard(self)`
- `tests/test_constitution.py` — `test_validate_all_security(self)`
- `tests/test_production_extensions.py` — `test_orchestrator_audits_and_honors_safety_gate(tmp_path)`
- `tests/test_smoke.py` — `test_index_adaptive_threshold_tightens_after_weak_recent_history()`
- `tests/test_admin_control_plane.py` — `test_audit_no_token(client)`
- `tests/test_admin_control_plane.py` — `test_wired_audit_log(wired_client)`
- `tests/test_admin_control_plane.py` — `test_config_reload_audit_event(reload_client)`
- `tests/test_safety_state.py` — `test_clear_hard_halt_adds_to_history(self)`
- `tests/test_safety_state.py` — `test_clear_history_limited(self)`
- `tests/test_quant_math_invariants.py` — `test_invariant_8_sha256_audit_hash_chain()`
- `tests/test_control_plane.py` — `test_enabled_audit_logger_unavailable(self)`
- `tests/test_secure_config.py` — `test_get_secret_logs_audit(self)`
- `tests/test_secure_config.py` — `test_get_secret_logs_audit_for_custom_key(self)`
- `tests/test_auth_comprehensive.py` — `test_audit_log_on_login_success(self, handler: Any, test_user: dict[str, Any])`
- `tests/test_auth_comprehensive.py` — `test_audit_log_on_login_failure(self, handler: Any, test_user: dict[str, Any])`
- `tests/test_auth_comprehensive.py` — `test_audit_log_on_user_created(self, handler: Any)`
- `tests/test_auth_comprehensive.py` — `test_audit_log_on_password_change(self, handler: Any, test_user: dict[str, Any])`
- `tests/test_auth_comprehensive.py` — `test_audit_log_on_admin_reset(self, handler: Any, test_user: dict[str, Any])`
- `tests/test_auth_comprehensive.py` — `test_audit_log_on_role_change(self, handler: Any, test_user: dict[str, Any])`
- `tests/test_auth_comprehensive.py` — `test_audit_log_on_disable(self, handler: Any, test_user: dict[str, Any])`
- `tests/test_auth_comprehensive.py` — `test_audit_log_on_delete(self, handler: Any, test_user: dict[str, Any])`
- `tests/test_auth_comprehensive.py` — `test_audit_log_filter_by_event_type(self, handler: Any, test_user: dict[str, Any])`
- `tests/test_auth_comprehensive.py` — `test_audit_log_limit(self, handler: Any, test_user: dict[str, Any])`
- `tests/test_auth_comprehensive.py` — `test_stats_reflects_activity(self, handler: Any, test_user: dict[str, Any])`
- `tests/test_constitution_ai_gate.py` — `test_audit_history_not_reviewed(self)`
- `tests/test_constitution_ai_gate.py` — `test_acknowledge_records_audit(self)`
- `tests/test_constitution_ai_gate.py` — `test_validate_records_audit(self)`
- `tests/test_constitution_ai_gate.py` — `test_audit_log_limit(self)`
- `tests/test_constitution_ai_gate.py` — `test_audit_log_format(self)`
- `tests/test_wip71_notification_content.py` — `test_notification_content_audit_exists()`
- `tests/test_dashboard_comprehensive.py` — `test_config_history(self, tmp_path)`
- `tests/test_dashboard_comprehensive.py` — `test_config_history_sorted(self, tmp_path)`
- `tests/test_dashboard_comprehensive.py` — `test_config_history_empty(self, tmp_path)`
- `tests/test_dashboard_comprehensive.py` — `test_config_history_bad_filenames(self, tmp_path)`
- `tests/test_dashboard_comprehensive.py` — `test_log_config_audit(self, tmp_path)`
- `tests/test_dashboard_comprehensive.py` — `test_apply_creates_audit_log(self, tmp_path)`
- `tests/test_dashboard_comprehensive.py` — `test_audit_log(self, base_cfg, trades_db, monkeypatch)`
- `tests/test_dashboard_comprehensive.py` — `test_audit_log_filtered(self, base_cfg, trades_db, monkeypatch)`
- `tests/test_dashboard_comprehensive.py` — `test_lifespan_events(self, state_file, trades_db, base_cfg)`
- `tests/test_auditor.py` — `test_audit_architecture(self)`
- `tests/test_auditor.py` — `test_audit_risk_controls_without_config(self)`
- `tests/test_auditor.py` — `test_audit_risk_controls_with_config(self)`
- `tests/test_auditor.py` — `test_audit_execution(self)`
- `tests/test_auditor.py` — `test_audit_strategies(self)`
- `tests/test_auditor.py` — `test_audit_scoring(self)`
- `tests/test_auditor.py` — `test_audit_replay(self)`
- `tests/test_auditor.py` — `test_audit_governance(self)`
- `tests/test_auditor.py` — `test_audit_all(self)`
- `tests/test_auditor.py` — `test_audit_all_with_config(self)`
- `tests/test_auditor.py` — `test_get_auditor(self)`
- `tests/test_wip77_audit_implementation_closure.py` — `test_audit_closure_report_exists()`
- `tests/test_wip77_audit_implementation_closure.py` — `test_shared_audit_infrastructure_exists()`
- `tests/test_wip77_audit_implementation_closure.py` — `test_security_log_exclusion_is_documented()`
- `tests/test_sovereignty_guard.py` — `test_audit_blocked(self, blocked_cfg: dict)`
- `tests/test_sovereignty_guard.py` — `test_audit_full_access(self, full_access_cfg: dict)`
- `tests/test_sovereignty_guard.py` — `test_audit_mixed(self)`
- `tests/test_sovereignty_guard.py` — `test_audit_manual_blocks_broker(self)`
- `tests/test_continuous_intelligence.py` — `test_save_and_load_history(self, pipeline: ContinuousIntelligenceEngine, tmp_path: Path)`
- `tests/test_continuous_intelligence.py` — `test_load_history_from_existing(self, tmp_path: Path)`
- `tests/test_continuous_intelligence.py` — `test_get_history_limit(self, pipeline: ContinuousIntelligenceEngine, tmp_path: Path)`
- `tests/test_audit_engine.py` — `test_record_returns_audit_record(self, engine: AuditEngine)`
- `tests/test_audit_engine.py` — `test_record_multiple_events(self, engine: AuditEngine, tmp_log: Path)`
- `tests/test_audit_engine.py` — `test_concurrent_same_event(self, tmp_log: Path)`
- `tests/test_audit_engine.py` — `test_record_empty_event(self, engine: AuditEngine, tmp_log: Path)`
- `tests/test_audit_engine.py` — `test_audit_record_dataclass(self, engine: AuditEngine)`
- `tests/test_ai_security_gate.py` — `test_clear_audit(self)`
- `tests/test_ai_security_gate.py` — `test_audit_record_to_dict(self)`
- `tests/test_wip75_reject_rollback_reason.py` — `test_reason_is_audited()`
- `tests/test_release_governance.py` — `test_audit_record_returns_bool(self, tmp_path: Path)`
- `tests/test_release_governance.py` — `test_audit_record_creates_json_file(self, tmp_path: Path)`
- `tests/test_release_governance.py` — `test_audit_record_json_has_expected_fields(self, tmp_path: Path)`
- `tests/test_release_governance.py` — `test_audit_record_contains_version(self, tmp_path: Path)`
- `tests/test_release_governance.py` — `test_audit_record_no_changes(self, tmp_path: Path)`
- `tests/test_release_governance.py` — `test_audit_record_trend_snapshot_field_defaults_false(self, tmp_path: Path)`
- `tests/test_release_governance.py` — `test_audit_record_trend_snapshot_field_true(self, tmp_path: Path)`
- `tests/test_release_governance.py` — `test_audit_record_register_gate_fields_written(self, tmp_path: Path)`
- `tests/test_release_governance.py` — `test_audit_record_register_gate_defaults_unknown(self, tmp_path: Path)`
- `tests/test_release_governance.py` — `test_audit_record_register_gate_drift_failure(self, tmp_path: Path)`
- `tests/test_release_governance.py` — `test_audit_log_dir_constant(self)`
- `tests/test_release_governance.py` — `test_main_audit_only(self, tmp_path: Path)`
- `tests/test_release_governance.py` — `test_main_pipeline_audit_records_register_gate(self, monkeypatch: Any,
                                                       tmp_path: Path)`
- `tests/test_auth_system.py` — `test_audit_log(self, client)`
- `tests/test_change_management.py` — `test_get_audit_log(self)`
- `tests/test_run_pr_audit.py` — `test_returns_audit_section(self)`
- `tests/test_run_pr_audit.py` — `test_run_audit_returns_report(self, mock_subprocess)`
- `tests/test_run_pr_audit.py` — `test_run_audit_quick_skips_dead_code(self, mock_subprocess)`
- `tests/test_run_pr_audit.py` — `test_run_audit_full_includes_slow_checks(self, mock_subprocess)`
- `tests/test_wip76_audit_coverage_contract.py` — `test_audit_matrix_exists()`
- `tests/test_wip76_audit_coverage_contract.py` — `test_audit_matrix_covers_security_and_rbac()`
- `tests/test_wip76_audit_coverage_contract.py` — `test_reasoned_reject_rollback_is_audited()`
- `tests/test_di_container.py` — `test_wire_security_services()`
- `tests/test_di_container.py` — `test_wire_security_services_idempotent()`
- `tests/test_config_engine.py` — `test_audit_log_enabled_no_file_error(self)`
- `tests/test_config_engine.py` — `test_audit_log_enabled_with_file_ok(self)`
- `tests/test_config_engine.py` — `test_audit_log_disabled_no_error(self)`
- `tests/test_wip81_persistence_audit.py` — `test_persistence_audit_gap_report_exists()`
- `tests/test_wip81_persistence_audit.py` — `test_universal_audit_contract_is_retained()`
- `tests/test_opbuying_observability.py` — `test_append_soft_reload_audit_diff_reexported(self)`
- `tests/test_audit_mode.py` — `test_audit_architecture_returns_report(self, auditor: Auditor)`
- `tests/test_audit_mode.py` — `test_audit_risk_returns_report(self, auditor: Auditor)`
- `tests/test_audit_mode.py` — `test_audit_strategy_returns_report(self, auditor: Auditor)`
- `tests/test_audit_mode.py` — `test_audit_execution_returns_report(self, auditor: Auditor)`
- `tests/test_audit_mode.py` — `test_audit_scoring_returns_report(self, auditor: Auditor)`
- `tests/test_audit_mode.py` — `test_audit_security_returns_report(self, auditor: Auditor)`
- `tests/test_audit_mode.py` — `test_full_audit_returns_combined_report(self, auditor: Auditor)`
- `tests/test_audit_mode.py` — `test_full_audit_aggregates_multi_scope(self, auditor: Auditor)`
- `tests/test_audit_mode.py` — `test_full_audit_duration_positive(self, auditor: Auditor)`
- `tests/test_audit_mode.py` — `test_full_audit_all_findings_have_scope(self, auditor: Auditor)`
- `tests/test_audit_mode.py` — `test_full_audit_verdict_is_string(self, auditor: Auditor)`
- `tests/test_audit_mode.py` — `test_get_auditor_returns_instance(self)`
- `tests/test_audit_mode.py` — `test_get_auditor_singleton(self)`
- `tests/test_audit_mode.py` — `test_run_audit_all_returns_report(self)`
- `tests/test_audit_mode.py` — `test_run_audit_risk_scope(self)`
- `tests/test_audit_mode.py` — `test_run_audit_invalid_scope_defaults_all(self)`
- `tests/test_auth_handler_protocols.py` — `_audit_log(self,
        event_type: str,
        username: str,
        ip_address: str | None = None,
        details: Any | None = None,)`
- `tests/test_auth_handler_protocols.py` — `_audit_log(self, x: int)`
- `tests/test_auth_handler_protocols.py` — `_audit_log(self,
        event_type: str,
        username: str,
        ip_address: str | None = None,
        details: Any | None = None,)`
- `tests/test_auth_handler_protocols.py` — `_audit_log(self,
        event_type: str,
        username: str,
        ip_address: str | None = None,
        details: Any | None = None,)`
- `tests/test_auth_handler_protocols.py` — `_audit_log(self, event_type, username, ip_address=None, details=None)`
- `tests/test_auth_handler_protocols.py` — `test_missing_audit_log_fails(self)`
- `tests/test_auth_handler.py` — `test_audit_log_records_events(self, auth_with_user: AuthHandler)`
- `tests/test_auth_handler.py` — `test_audit_log_filter(self, auth_with_user: AuthHandler)`
- `tests/test_auth_handler.py` — `test_audit_log_limit(self, auth_with_user: AuthHandler)`
- `tests/test_score_system.py` — `test_needs_9_audit_flag(self)`
- `tests/test_score_system.py` — `test_needs_95_audit_flag(self)`
- `infrastructure/security/audit_logger.py` — `log_event(self,
                  event_type: str,
                  resource: str,
                  action: str,
                  outcome: str = "success",
                  details: dict[str, Any] | None = None,
                  severity: str = "info",
                  user_id: str | None = None,
                  session_id: str | None = None,
                  ip_address: str | None = None,
                  correlation_id: str | None = None)`
- `infrastructure/security/audit_logger.py` — `get_trade_audit_trail(self, trade_id: str)`
- `infrastructure/security/audit_logger.py` — `log_security_violation(self, event_type: str, resource: str, action: str,
                              details: dict[str, Any] | None = None,
                              user_id: str | None = None,
                              session_id: str | None = None,
                              ip_address: str | None = None)`
- `infrastructure/security/audit_logger.py` — `get_audit_logger()`
- `infrastructure/security/audit_logger.py` — `init_audit_logger(log_file: Path | None = None,
                     max_file_size: int = 10 * 1024 * 1024,
                     backup_count: int = 5,
                     enable_console_output: bool = False)`
- `infrastructure/security/audit_logger.py` — `log_security_violation(event_type: str, resource: str, action: str,
                          details: dict[str, Any] | None = None,
                          user_id: str | None = None,
                          session_id: str | None = None,
                          ip_address: str | None = None)`
- `infrastructure/security/audit_logger.py` — `get_trade_audit_trail(trade_id: str)`
- `core/auditor/auditor.py` — `get_auditor()`
- `core/auditor/auditor.py` — `reset_auditor()`
- `core/ai/governance.py` — `_audit(self, action: str, model_id: str, detail: dict[str, Any])`
- `core/ai/governance.py` — `get_audit_log(self, limit: int = 100)`
- `core/ai/safety_gate.py` — `_audit(self, result: str, verdict: AISafetyVerdict)`
- `core/ai/safety_gate.py` — `get_audit_log(self, limit: int = 100)`
- `core/auth/routes.py` — `get_my_signal_history(year: str = "all",
        month: str = "all",
        week: str = "all",
        day: str = "all",
        category: str = "all",
        current_user: AuthUser = Depends(auth_deps.require_auth)`
- `core/auth/routes.py` — `get_audit_log(limit: int = 100,
        event_type: str | None = None,
        admin: AuthUser = Depends(manage_users)`
- `core/strategy/approval_workflow.py` — `get_request_history(self, strategy_name: str | None = None)`
- `core/strategy/approval_workflow.py` — `_log_approval_event(self,
        event: str,
        request: TransitionRequest,
        approver: str = "",
        reason: str = "",
        **extra: Any,)`
- `core/strategy/sandbox.py` — `_record_signal_event(self, signal: StrategySignalOutput, fill: dict)`
- `core/certification/gate.py` — `_run_security_compliance(cfg: dict[str, Any])`
- `core/certification/report_generators.py` — `generate_security_certification(config: dict[str, Any] | None = None,
    version: str = "2.55+",)`
- `core/control_plane/audit_store.py` — `get_legacy_audit_events(limit: int = 100)`
- `core/control_plane/server.py` — `_audit(self, action: str, target: str, value: str, identity: str,
        success: bool, reason: str = "",
        previous_state: dict | None = None, new_state: dict | None = None,)`
- `core/control_plane/server.py` — `control_audit(self, limit: int = 100)`
- `core/control_plane/server.py` — `get_audit_log(request: Request)`
- `core/control_plane/server.py` — `get_audit(limit: int = 100,
        authorization: str | None = Header(default=None)`
- `core/control_plane/helpers.py` — `legacy_audit_log(audit_logger: Any, event_type: str, resource: str, action: str,
    outcome: str = "success", details: dict | None = None,
    user_id: str | None = None, ip_address: str | None = None,)`
- `core/services/execution_service.py` — `record_execution_audit(self,
        audit_trail: ExecutionAuditTrail,)`
- `core/services/execution_service.py` — `get_execution_audit_trail(self,
        execution_id: str,)`
- `core/services/execution_service.py` — `_audit_trail_to_trade_data(self,
        audit_trail: ExecutionAuditTrail,)`
- `core/enterprise_dashboard/main.py` — `on_event(self, *args: Any, **kwargs: Any)`
- `core/enterprise_dashboard/main.py` — `_get_config_history(self)`
- `core/enterprise_dashboard/main.py` — `_log_config_audit(self, username: str, keys: list, values: list, action: str)`
- `core/enterprise_dashboard/main.py` — `_get_config_audit_log(self, limit: int = 50)`
- `core/constitution/__init__.py` — `add_audit(self, category_id: str, audit_type: str)`
- `core/constitution/__init__.py` — `validate_security_governance_standard(self,
        standard_id: str,
        implemented: bool = False,
        evidence: str = "",)`
- `core/constitution/__init__.py` — `validate_all_security_governance(self,
        standard_status: dict[str, bool],)`
- `core/constitution/__init__.py` — `get_audit_log(self, limit: int = 100)`
- `core/constitution/__init__.py` — `_audit(self, action: str, details: dict[str, Any])`
- `core/constitution/models.py` — `needs_9_audit(self)`
- `core/constitution/models.py` — `needs_95_audit(self)`
- `core/integrations/security_feeds.py` — `get_security_feed_reporter()`
- `core/integrations/security_feeds.py` — `wire_security_feeds()`
- `core/integrations/cqrs_event_sourcing.py` — `wire_cqrs_to_event_sourcing()`
- `core/di_container/wire_security.py` — `wire_security_services(container_instance: DIContainer | None = None)`
- `core/di_container/wire_security.py` — `wire_ai_security_gate_services(container_instance: DIContainer | None = None)`
- `core/di_container/wire_security.py` — `wire_runtime_security_services(container_instance: DIContainer | None = None)`
- `core/signals/signal_tracker.py` — `_seed_sample_history(self, cur: sqlite3.Cursor)`
- `core/execution/event_system.py` — `trace_event(*a: object, **kw: object)`
- `core/execution/event_system.py` — `_canonical_event_data(self, event: TradingEvent)`
- `core/execution/event_system.py` — `get_events_for_order(self, client_order_id: str)`
- `core/execution/event_system.py` — `get_event_stats(self)`
- `core/execution/event_system.py` — `get_events_by_type(self, event_type: EventType, limit: int = 1000)`
- `core/execution/event_system.py` — `get_events_in_range(self, start_time: str, end_time: str)`
- `core/execution/event_system.py` — `_rows_to_events(self, cursor: sqlite3.Cursor)`
- `core/execution/event_system.py` — `get_recent_events(self, count: int = 100)`
- `core/execution/event_system.py` — `get_event_bus()`
- `core/execution/event_system.py` — `get_event_store()`
- `core/auto_tuner/tuner.py` — `_write_audit(result: TuneResult)`
- `core/ports/execution/execution_port.py` — `record_execution_audit(self,
        audit_trail: ExecutionAuditTrail,)`
- `core/ports/execution/execution_port.py` — `get_execution_audit_trail(self,
        execution_id: str,)`
- `core/telegram/audit/manager.py` — `_setup_audit_logger(self)`
- `core/enterprise_dashboard/routes/governance.py` — `api_governance_history(strategy_name: str = "",
        user: Any = Depends(operator_or_admin)`
- `core/enterprise_dashboard/routes/admin.py` — `api_config_history(user: Any = Depends(dashboard._auth_deps.require_permission("modify_config")`
- `core/enterprise_dashboard/routes/admin.py` — `api_config_audit_log(limit: int = 50, user: Any = Depends(dashboard._auth_deps.require_permission("view_logs")`
- `core/enterprise_dashboard/routes/admin.py` — `api_changes_history(user: Any = Depends(dashboard._auth_deps.require_permission("view_logs")`
- `core/enterprise_dashboard/routes/intelligence.py` — `api_runtime_security_check(user: Any = operator_or_admin)`
- `core/enterprise_dashboard/routes/intelligence.py` — `api_runtime_security_stats(user: Any = operator_or_admin)`
- `core/enterprise_dashboard/routes/intelligence_bi.py` — `api_security_scan(user: Any = operator_or_admin)`
- `core/enterprise_dashboard/routes/intelligence_bi.py` — `api_security_stats(user: Any = operator_or_admin)`
- `core/enterprise_dashboard/routes/intelligence_bi.py` — `api_security_last_report(user: Any = operator_or_admin)`
- `core/enterprise_dashboard/routes/metrics_trend.py` — `_list_audit_records(limit: int = 50)`
- `core/enterprise_dashboard/routes/metrics_trend.py` — `api_metrics_trend_release_audits(limit: int = 50,
        user: Any = Depends(dashboard._auth_deps.require_auth_optional)`
- `core/enterprise_dashboard/routes/monitoring.py` — `_event_generator()`
- `core/auth/handler/handler.py` — `_audit_log(self, event_type: str, username: str, ip_address: str = "", details: dict | None = None, success: bool | None = None)`
- `core/auth/handler/handler.py` — `get_audit_log(self, limit: int = 100, event_type: str | None = None)`
- `core/auth/handler/mfa_handler.py` — `_audit_log(self, event_type: str, username: str, ip_address: str, details: object = None)`
- `core/auth/handler/protocols.py` — `_audit_log(self,
        event_type: str,
        username: str,
        ip_address: str | None = None,
        details: Any | None = None,)`

## Closure requirement
- Use the existing shared audit infrastructure where it already provides a server-side immutable event.
- Do not add duplicate controller-level audit calls when a downstream transactional/service layer already records the mutation.
- Any uncovered durable mutation must be wired to the shared audit boundary.
- Reject/Rollback must require and persist a reason before the state transition.
- Audit records must exclude secrets, passwords, tokens and credentials.