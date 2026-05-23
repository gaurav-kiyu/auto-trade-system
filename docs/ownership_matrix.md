# Module Ownership Matrix

Last Updated: 2026-05-22

## Core Modules

### Risk & Safety (P0 — Capital Protection)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/risk/authoritative_engine.py` | Risk team | Always | Canonical risk authority |
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
| `core/execution_engine.py` | Execution team | Always | Primary execution path |
| `core/adapters/broker_adapters.py` | Execution team | Always | Broker abstraction layer |
| `core/broker_failover.py` | Execution team | Always | Broker failover management |
| `core/execution_policy.py` | Execution team | Always | Execution mode policies |
| `core/execution_guards.py` | Execution team | Always | Safety guards on execution |
| `core/execution_wiring.py` | Execution team | Always | Execution wiring/integration |
| `core/hybrid_execution.py` | Execution team | Always | Hybrid paper/live routing |
| `core/limit_order_engine.py` | Execution team | Always | Limit order pricing/fill |
| `core/scalein_manager.py` | Execution team | Always | Scale-in entry management |
| `core/wal/journal.py` | Execution team | Always | Write-ahead journal |
| `core/execution/idempotency/` | Execution team | Always | Exactly-once certification |

### Signal Generation (P1 — Trade Quality)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/pure_index_signal.py` | Strategy team | Always | Signal generation core |
| `core/adaptive_signal.py` | Strategy team | Always | Signal scoring pipeline |
| `core/strategy_engine.py` | Strategy team | Always | Strategy orchestration |
| `core/scoring_engine.py` | Strategy team | Always | Signal scoring |
| `core/strike_selector.py` | Strategy team | Always | Strike price selection |
| `core/session_classifier.py` | Strategy team | Always | Time-of-day session bands |
| `core/spread_strategy.py` | Strategy team | Always | Debit spread engine |
| `core/straddle_strategy.py` | Strategy team | Always | Straddle/strangle engine |
| `core/iron_condor_strategy.py` | Strategy team | Always | Iron condor engine |
| `core/reentry_evaluator.py` | Strategy team | Always | Re-entry cooldown + score gate |

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
| `core/gex_analyzer.py` | Data team | Always | Gamma exposure analysis |

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

### Monitoring & Observability (P2 — Visibility)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/health_checker.py` | Ops team | Yes | System health checks |
| `core/health_reporter.py` | Ops team | Yes | Health reporting |
| `core/metrics_exporter.py` | Ops team | Yes | Prometheus metrics |
| `core/benchmark.py` | Ops team | Yes | Benchmark comparison |
| `core/telegram_queue.py` | Ops team | Yes | Telegram dispatch queue |
| `core/telegram_engine.py` | Ops team | Yes | Telegram notifications |
| `core/alert_router.py` | Ops team | Yes | Alert routing |
| `core/anomaly_detector.py` | Ops team | Yes | Anomaly detection |
| `core/incident_alerting.py` | Ops team | Yes | Incident alerting |
| `core/environment.py` | Ops team | Yes | Environment validation |

### Dashboard & CLI (P2 — User Interface)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/web_dashboard.py` | Platform team | Yes | FastAPI dashboard |
| `core/report_generator.py` | Platform team | Yes | PDF report generation |
| `core/signal_autopsy.py` | Platform team | Yes | Win-rate diagnostics |
| `core/trade_replayer.py` | Platform team | Yes | Trade replay visualizer |
| `core/sensitivity_analyzer.py` | Platform team | Yes | Parameter sensitivity |
| `core/presentation_engine.py` | Platform team | Yes | Data presentation |
| `core/dashboard_engine.py` | Platform team | Yes | Dashboard data engine |

### Infrastructure & Governance (P2 — Platform)

| Module | Owner | Review Required | Notes |
|--------|-------|----------------|-------|
| `core/logging.py` | Platform team | Yes | Logging configuration |
| `core/log_helpers.py` | Platform team | Yes | Logging utilities |
| `core/datetime_ist.py` | Platform team | Yes | IST timezone handling |
| `core/python_runtime.py` | Platform team | Yes | Python version enforcement |
| `core/config_audit_log.py` | Platform team | Yes | Config change audit trail |
| `core/config_schema_validate.py` | Platform team | Yes | JSON schema validation |
| `core/startup_checklist.py` | Platform team | Yes | Startup validation |
| `core/startup_reconciliation.py` | Platform team | Yes | Startup reconciliation |
| `core/startup_validation.py` | Platform team | Yes | Startup validation checks |

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
| `tests/test_environment.py` | Ops team | Yes |
| `tests/test_db_migration.py` | Platform team | Yes |
| `tests/test_data_governance.py` | Platform team | Yes |
| All other `tests/` | Owner of corresponding module | Yes |

## Review Policy
- **Always**: Every PR modifying this module requires owner review
- **Yes**: Owner review required for non-trivial changes (>50 lines or behavioral change)
- **No**: Owner review encouraged but not required for minor fixes

## Update Procedure
1. This matrix is reviewed monthly (first trading day of each month)
2. Ownership changes must be approved by the current owner and team lead
3. Unclaimed modules default to Platform team ownership
4. New modules must be added to this matrix within 2 weeks of creation
