# Module Ownership Matrix

Last Updated: 2026-05-22

## Ownership Teams
| Team | Scope |
|------|-------|
| **Risk team** | Capital protection, risk evaluation, position sizing, exposure controls |
| **Execution team** | Order integrity, broker connectivity, WAL, idempotency, failover |
| **Strategy team** | Trade quality, signal generation, scoring, session classification |
| **Data team** | Market data quality, feed management, IV/VIX/GEX analytics |
| **AI team** | ML model lifecycle, training, inference, concept drift |
| **Platform team** | State management, config, persistence, dashboard, tooling |
| **Ops team** | Observability, environment governance, health monitoring |

---

## Core Modules

### Risk & Safety (P0 — Capital Protection)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/services/risk_service.py` | Risk team | Always | **Canonical** risk authority via `RiskPort` |
| `core/ports/risk/risk_port.py` | Risk team | Always | Risk interface contract |
| `core/risk/__init__.py` | Risk team | Always | Architecture declaration |
| `core/risk/limits/manager.py` | Risk team | Always | Risk limits — internal to RiskService |
| `core/risk/sizing/manager.py` | Risk team | Always | Position sizing — internal to RiskService |
| `core/risk/margin_validator.py` | Risk team | Always | Margin validation — internal to RiskService |
| `core/safety_engine.py` | Risk team | Always | Safety context + decisions |
| `core/safety_state.py` | Risk team | Always | Halt/shutdown state machine |
| `core/exposure_limits.py` | Risk team | Always | Exposure calculation |
| `core/equity_protection.py` | Risk team | Always | Capital preservation |
| `core/liquidity_guard.py` | Risk team | Always | Pre-entry liquidity filter |
| `core/capital_manager.py` | Risk team | Always | Position sizing |
| `core/position_sizer.py` | Risk team | Always | Position size calculation |
| `core/kelly_sizer.py` | Risk team | Always | Kelly criterion sizing |
| `core/var_calculator.py` | Risk team | Always | Value-at-Risk |
| `core/stress_tester.py` | Risk team | Always | Scenario stress testing |

### Execution & Broker (P0 — Order Integrity)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/services/execution_service.py` | Execution team | Always | Canonical execution path |
| `core/ports/broker/` | Execution team | Always | Broker interface contract |
| `core/ports/execution/` | Execution team | Always | Execution interface contract |
| `core/adapters/broker_adapters.py` | Execution team | Always | Broker abstraction layer (legacy) |
| `core/adapters/base_adapter.py` | Execution team | Always | Base adapter classes |
| `infrastructure/adapters/brokers/` | Execution team | Always | Multi-broker implementations |
| `infrastructure/adapters/brokers/paper/adapter.py` | Execution team | Always | Paper trading adapter (BrokerPort) |
| `infrastructure/adapters/brokers/kite/adapter.py` | Execution team | Always | Kite adapter |
| `infrastructure/adapters/brokers/angel/adapter.py` | Execution team | Always | Angel adapter |
| `infrastructure/adapters/brokers/iifl/adapter.py` | Execution team | Always | IIFL adapter |
| `infrastructure/adapters/brokers/dhan/adapter.py` | Execution team | Always | Dhan adapter |
| `infrastructure/adapters/brokers/groww/adapter.py` | Execution team | Always | Groww adapter |
| `infrastructure/adapters/brokers/mstock/adapter.py` | Execution team | Always | mStock adapter |
| `infrastructure/adapters/brokers/ibkr/adapter.py` | Execution team | Always | IBKR adapter |
| `infrastructure/adapters/brokers/template/adapter.py` | Execution team | Always | Template for new adapters |
| `core/broker_failover.py` | Execution team | Always | Broker failover management |
| `core/execution_policy.py` | Execution team | Always | Execution mode policies |
| `core/execution_guards.py` | Execution team | Always | Safety guards on execution |
| `core/execution_wiring.py` | Execution team | Always | Execution wiring/integration |
| `core/hybrid_execution.py` | Execution team | Always | Hybrid paper/live routing |
| `core/limit_order_engine.py` | Execution team | Always | Limit order pricing/fill |
| `core/scalein_manager.py` | Execution team | Always | Scale-in entry management |
| `core/wal/journal.py` | Execution team | Always | Write-ahead journal |
| `core/execution/idempotency/` | Execution team | Always | Exactly-once certification |
| `core/execution/broker_gateway.py` | Execution team | Always | Broker gateway abstraction |
| `core/execution/order_manager.py` | Execution team | Always | Order lifecycle manager |
| `core/execution/retry_policy/` | Execution team | Always | Retry policy framework |

### Signal Generation (P1 — Trade Quality)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/pure_index_signal.py` | Strategy team | Always | Signal generation core |
| `core/adaptive_signal.py` | Strategy team | Always | Signal scoring pipeline |
| `core/strategy_engine.py` | Strategy team | Always | **DEPRECATED** — use `StrategyOrchestrator` |
| `core/strategy/orchestrator.py` | Strategy team | Always | **Canonical** strategy orchestrator via `StrategyPort` |
| `core/ports/strategy/` | Strategy team | Always | Strategy interface contract (`StrategyPort`) |
| `core/services/signal_orchestrator.py` | Strategy team | Always | Canonical signal generation pipeline |
| `core/scoring_engine.py` | Strategy team | Always | Signal scoring |
| `core/strike_selector.py` | Strategy team | Always | Strike price selection |
| `core/session_classifier.py` | Strategy team | Always | Time-of-day session bands |
| `core/spread_strategy.py` | Strategy team | Always | Debit spread engine |
| `core/straddle_strategy.py` | Strategy team | Always | Straddle/strangle engine |
| `core/iron_condor_strategy.py` | Strategy team | Always | Iron condor engine |
| `core/reentry_evaluator.py` | Strategy team | Always | Re-entry cooldown + score gate |
| `core/signal_autopsy.py` | Strategy team | Always | Win-rate diagnostics |
| `core/sensitivity_analyzer.py` | Strategy team | Always | Parameter sensitivity |

### Market Data (P1 — Data Quality)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/yf_bar_fetch.py` | Data team | Always | Yahoo Finance data fetch |
| `core/kite_ticker_feed.py` | Data team | Always | WebSocket ticker feed |
| `core/ws_feed_manager.py` | Data team | Always | WebSocket feed management |
| `core/data_engine.py` | Data team | Always | Market data orchestration |
| `core/data_freshness_guard.py` | Data team | Always | Stale data detection |
| `core/ltp_resolver.py` | Data team | Always | LTP resolution chain |
| `core/market_calc.py` | Data team | Always | Market calculations |
| `core/market_warmup.py` | Data team | Always | Pre-market warmup |
| `core/oi_snapshot_store.py` | Data team | Always | OI history recorder |
| `core/iv_rank.py` | Data team | Always | IV Rank/Percentile |
| `core/iv_skew.py` | Data team | Always | IV skew analysis |
| `core/gex_analyzer.py` | Data team | Always | Gamma exposure analysis |
| `core/implied_move.py` | Data team | Always | ATM straddle implied move |
| `core/underlying_analyzer.py` | Data team | Always | Constituent stock breadth |
| `core/corp_action_calendar.py` | Data team | Yes | Corporate action tracking |
| `core/event_calendar.py` | Data team | Yes | Budget/RBI/FOMC calendar |
| `core/correlation_guard.py` | Data team | Always | Cross-index correlation |
| `core/timeframe_divergence.py` | Data team | Always | Multi-timeframe alert |
| `core/fii_dii_tracker.py` | Data team | Always | Institutional flow tracking |
| `core/ports/market_data.py` | Data team | Always | Market data port interface |

### ML & AI (P1 — Prediction Quality)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/ml_classifier.py` | AI team | Always | LightGBM win-prob classifier |
| `core/ml_performance_tracker.py` | AI team | Always | Prediction calibration |
| `core/ml_inference.py` | AI team | Always | ML inference pipeline |
| `core/ml_exit_classifier.py` | AI team | Always | ML exit prediction |
| `core/ml_regime_router.py` | AI team | Always | Regime-based ML routing |
| `core/concept_drift_detector.py` | AI team | Always | PSI/KS drift detection |
| `core/auto_learner.py` | AI team | Always | Automated learning |
| `core/adaptive_learning.py` | AI team | Always | Adaptive threshold adjustment |
| `core/auto_tuner.py` | AI team | Always | Parameter auto-tuning |
| `core/param_optimizer.py` | AI team | Always | Walk-forward optimization |
| `core/ai/governance.py` | AI team | Always | AI governance board |
| `core/ai/model_registry.py` | AI team | Always | Model version registry |
| `core/ai/canary_manager.py` | AI team | Yes | Canary rollout manager |
| `core/ai/rollback_controller.py` | AI team | Yes | Model rollback controller |
| `core/ai/__init__.py` | AI team | Always | AI package |

### State & Persistence (P1 — Data Integrity)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/state_manager.py` | Platform team | Always | Session recovery + state |
| `core/config_bootstrap.py` | Platform team | Always | Config merge + env override |
| `core/config_helpers.py` | Platform team | Always | Config utilities |
| `core/config_engine.py` | Platform team | Always | Config validation |
| `core/defaults_loader.py` | Platform team | Always | Defaults loading |
| `core/performance_metrics.py` | Platform team | Always | Trade analytics |
| `core/trade_journal.py` | Platform team | Always | Execution quality journal |
| `core/pnl_attribution.py` | Platform team | Always | P&L attribution |
| `core/reconciliation_engine.py` | Platform team | Always | Position reconciliation |
| `core/db_migration.py` | Platform team | Always | Schema version management |
| `core/data_governance.py` | Platform team | Always | Data retention policies |
| `core/portfolio/authoritative.py` | Platform team | Always | Portfolio authority |
| `core/portfolio/service.py` | Platform team | Yes | Portfolio orchestration |
| `core/nlp_journal.py` | Platform team | Yes | Post-trade narrative |
| `core/report_generator.py` | Platform team | Yes | PDF report generation |
| `core/trade_replayer.py` | Platform team | Yes | Trade replay visualizer |
| `core/ports/persistence/` | Platform team | Always | Persistence port interface |
| `core/ports/config/` | Platform team | Always | Config port interface |

### Monitoring & Observability (P2 — Visibility)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/health_checker.py` | Ops team | Yes | System health checks |
| `core/health_reporter.py` | Ops team | Yes | Health reporting |
| `core/metrics_exporter.py` | Ops team | Yes | Prometheus metrics |
| `core/telemetry/metrics.py` | Ops team | Yes | SRE-grade metrics |
| `core/telemetry/exporters.py` | Ops team | Yes | Telemetry exporters |
| `core/telemetry/__init__.py` | Ops team | Yes | Telemetry package |
| `core/benchmark.py` | Ops team | Yes | Benchmark comparison |
| `core/telegram_queue.py` | Ops team | Yes | Telegram dispatch queue |
| `core/telegram_engine.py` | Ops team | Yes | Telegram notifications |
| `core/alert_router.py` | Ops team | Yes | Alert routing |
| `core/anomaly_detector.py` | Ops team | Yes | Anomaly detection |
| `core/incident_alerting.py` | Ops team | Yes | Incident alerting |
| `core/environment.py` | Ops team | Yes | Environment validation |
| `core/ports/notification/` | Ops team | Yes | Notification port interface |

### Dashboard & CLI (P2 — User Interface)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/web_dashboard.py` | Platform team | Yes | FastAPI dashboard |
| `dashboard_server.py` | Platform team | Yes | Legacy dashboard (Flask) |
| `core/heatmap.py` | Platform team | Yes | Position heatmap |
| `core/presentation_engine.py` | Platform team | Yes | Data presentation |
| `core/dashboard_engine.py` | Platform team | Yes | Dashboard data engine |
| `launcher.py` | Platform team | Yes | GUI launcher |

### Control Plane & Governance (P2 — Platform)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/control_plane/__init__.py` | Ops team | Always | Control plane package init |
| `core/control_plane/admin_auth.py` | Ops team | Always | JWT admin authentication |
| `core/control_plane/rbac.py` | Ops team | Always | RBAC permission checker |
| `core/control_plane/server.py` | Ops team | Always | FastAPI admin server (pause/resume/state/config) |
| `core/operating_mode.py` | Ops team | Always | **Operating mode enforcement** |
| `core/system_mode.py` | Ops team | Always | System mode management |
| `core/invariants/engine.py` | Ops team | Always | Runtime invariant engine |
| `core/invariants/checks.py` | Ops team | Always | Standard invariant checks |
| `core/invariants/__init__.py` | Ops team | Always | Invariants package |
| `core/auth/role_manager.py` | Ops team | Always | RBAC role management |
| `core/auth/permissions.py` | Ops team | Always | Permission matrix |
| `core/auth/session_store.py` | Ops team | Always | Session tracking with TTL |
| `core/auth/__init__.py` | Ops team | Always | Auth package |
| `core/trade_mandate.py` | Ops team | Always | Trade mandate enforcement |
| `core/startup_checklist.py` | Ops team | Yes | Startup validation |
| `core/startup_reconciliation.py` | Ops team | Yes | Startup reconciliation |
| `core/startup_validation.py` | Ops team | Yes | Startup validation checks |
| `core/live_readiness_checker.py` | Ops team | Yes | Paper→live readiness gate |
| `core/ab_strategy_tester.py` | Ops team | Yes | A/B strategy testing |

### Infrastructure & Utilities

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/logging.py` | Platform team | Yes | Logging configuration |
| `core/log_helpers.py` | Platform team | Yes | Logging utilities |
| `core/datetime_ist.py` | Platform team | Yes | IST timezone handling |
| `core/python_runtime.py` | Platform team | Yes | Python version enforcement |
| `core/config_audit_log.py` | Platform team | Yes | Config change audit trail |
| `core/config_schema_validate.py` | Platform team | Yes | JSON schema validation |
| `core/di_container.py` | Platform team | Yes | Dependency injection container |
| `core/ports/correlation_id.py` | Platform team | Yes | Correlation ID port |
| `core/ports/logging.py` | Platform team | Yes | Logging port interface |
| `core/ports/metrics.py` | Platform team | Yes | Metrics port interface |
| `core/ports/circuit_breaker/` | Platform team | Yes | Circuit breaker port |
| `core/ports/rate_limiting/` | Platform team | Yes | Rate limiting port |

## Index App Modules

| Module | Owner | Review Required |
|--------|-------|----------------|
| `index_app/index_trader.py` | Strategy team | Always |
| `index_app/orchestrator_facade.py` | Platform team | Always |
| `index_app/index_trader_interface.py` | Platform team | Always |

## Test Modules

| Module | Owner | Review Required |
|--------|-------|----------------|
| `tests/conftest.py` | Platform team | Yes |
| `tests/contract/broker/` | Execution team | Always | Broker contract certification |
| `tests/chaos/` | Ops team | Always | Chaos/resilience certification |
| `tests/test_environment.py` | Ops team | Yes |
| `tests/test_db_migration.py` | Platform team | Yes |
| `tests/test_data_governance.py` | Platform team | Yes |
| All other `tests/` | Owner of corresponding module | Yes |

## Deprecated Modules (Do Not Import)

| Module | Replacement | Notes |
|--------|-------------|-------|
| `core/risk_engine.py` | `core/services/risk_service.py` | Use RiskService via RiskPort |
| `core/risk/authoritative_engine.py` | `core/services/risk_service.py` | **Removed** — file deleted |
| `core/predictive_risk.py` | Removed | Dead module |
| `core/trading_risk.py` | Removed | Dead module |
| `core/signal_approval_workflow.py` | `core/strategy/orchestrator.py` | **DEPRECATED** — merged into StrategyOrchestrator v2.0 |
| `core/strategy_engine.py` | `core/strategy/orchestrator.py` | **DEPRECATED** — backward compat shim only |
| `core/signal_approval_workflow.py` | `core/strategy/orchestrator.py` | **DEPRECATED** — merged into StrategyOrchestrator v2.0 |
| `core/admin_control_plane.py` | `core/control_plane/server.py` | **Removed** — replaced by new control plane package |
| `core/signal_router.py` | `core/strategy/orchestrator.py` | **Removed** |
| `core/strategy_engine_v2.py` | `core/strategy/orchestrator.py` | **Removed** |
| `core/mandate_enforcer.py` | `core/services/risk_service.py` | **DEPRECATED** — use RiskService via RiskPort |
| `core/risk/risk_policy_engine.py` | Removed | Dead module |
| `core/risk_engine_v2.py` | Removed | Dead module |
| `core/dynamic_risk_sizer.py` | Removed | Dead module |

## Review Policy
- **Always**: Every PR modifying this module requires owner review
- **Yes**: Owner review required for non-trivial changes (>50 lines or behavioral change)
- **No**: Owner review encouraged but not required for minor fixes

## Update Procedure
1. This matrix is reviewed monthly (first trading day of each month)
2. Ownership changes must be approved by the current owner and team lead
3. Unclaimed modules default to Platform team ownership
4. New modules must be added to this matrix within 2 weeks of creation
