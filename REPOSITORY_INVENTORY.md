# Repository Inventory

> **Phase 1 Deliverable** — Generated from live codebase audit.
> **Date:** 2026-06-20
> **Methodology:** Automated AST scanning + manual verification

---

## 1. Core Modules (`core/`)

### 1.1 Risk Domain
| Module | Purpose | Status |
|--------|---------|--------|
| `core/services/risk_service.py` | Position sizing, VIX scaling, drawdown sizing | ✅ Production |
| `core/domains/risk/service.py` | Domain risk service | ✅ Production |
| `core/domains/risk/model.py` | Risk domain models | ✅ Production |
| `core/risk/sizing/manager.py` | Risk sizing manager | ✅ Production |
| `core/risk/__init__.py` | Risk module exports | ✅ Production |
| `core/var_calculator.py` | Parametric VaR (95/99) | ✅ Production |
| `core/stress_tester.py` | 4-scenario stress test engine | ✅ Production |
| `core/kelly_sizer.py` | Half-Kelly position sizing | ✅ Production |
| `core/reentry_evaluator.py` | Per-index cooldown + score gate | ✅ Production |
| `core/liquidity_guard.py` | Bid-ask + OI + volume filter | ✅ Production |

### 1.2 Execution Domain
| Module | Purpose | Status |
|--------|---------|--------|
| `core/execution/event_system.py` | Hash-chained event store + EventBus | ✅ Production |
| `core/execution/idempotency/certifier.py` | Exactly-once execution certifier | ✅ Production |
| `core/execution/broker_gateway.py` | Broker routing gateway | ✅ Production |
| `core/execution/order_manager.py` | Order lifecycle management | ✅ Production |
| `core/execution/continuous_reconciliation.py` | Continuous reconciliation engine | ✅ Production |
| `core/execution/replay_engine.py` | Deterministic trade replay | ✅ Production |
| `core/execution/retry_policy/manager.py` | Retry policy manager | ✅ Production |
| `core/execution/state_machine.py` | Execution state machine | ✅ Production |

### 1.3 Portfolio Domain
| Module | Purpose | Status |
|--------|---------|--------|
| `core/portfolio/optimizer.py` | Portfolio optimization engine (MVP, Sharpe, Risk Parity) | ✅ v2.53 |
| `core/portfolio/authoritative.py` | Portfolio aggregation | ✅ Production |
| `core/portfolio/adapters/multi_asset_aggregator.py` | Multi-asset capital allocation | ✅ Production |
| `core/correlation_guard.py` | Cross-index correlation block | ✅ Production |
| `core/monte_carlo.py` | Trade P&L shuffle simulation | ✅ Production |
| `core/monte_carlo_tail_risk.py` | Tail risk analysis | ✅ Production |

### 1.4 Signal & Strategy Domain
| Module | Purpose | Status |
|--------|---------|--------|
| `core/adaptive_signal.py` | Signal scoring pipeline | ✅ Production |
| `core/pure_index_signal.py` | Base signal generation (RSI, MACD, ADX, PCR) | ✅ Production |
| `core/strike_selector.py` | ATM/OTM/DELTA strike selection | ✅ Production |
| `core/session_classifier.py` | Time-of-day session bands | ✅ Production |
| `core/iv_rank.py` | IV Rank / IV Percentile | ✅ Production |
| `core/signal_autopsy.py` | Win-rate diagnostics | ✅ Production |
| `core/signal_approval_workflow.py` | Signal routing approval | ✅ Production |
| `core/strategy/orchestrator.py` | Strategy orchestration | ✅ Production |
| `core/strategy/strategy_versioning.py` | Strategy version tracking | ✅ Production |
| `core/spread_strategy.py` | Debit spread engine | ✅ Production |
| `core/straddle_strategy.py` | Straddle/Strangle engine | ✅ Production |
| `core/iron_condor_strategy.py` | Iron Condor credit spread | ✅ Production |
| `core/scalein_manager.py` | Two-legged scale-in entry | ✅ Production |

### 1.5 ML Domain
| Module | Purpose | Status |
|--------|---------|--------|
| `core/ml_classifier.py` | LightGBM win-prob classifier | ✅ Production |
| `core/ml_performance_tracker.py` | SQLite prediction calibration + Brier score | ✅ Production |
| `core/concept_drift_detector.py` | PSI + KS feature drift detection | ✅ Production |
| `core/ml/feature_store.py` | ML feature store with versioning | ✅ Production |
| `core/ml/optimizer.py` | ML hyperparameter optimization | ✅ Production |
| `core/ai/governance.py` | AI model governance + approval workflow | ✅ Production |
| `core/ai/safety_gate.py` | AI safety gate (AI may NOT place orders) | ✅ Production |

### 1.6 Adapters & Brokers
| Module | Purpose | Status |
|--------|---------|--------|
| `core/adapters/broker_adapters.py` | Broker adapter abstraction + PaperBrokerAdapter | ✅ Production |
| `core/broker_failover.py` | Broker failover manager | ✅ Production |
| `core/ports/broker/broker_port.py` | Broker port interface | ✅ Production |
| `infrastructure/adapters/market_data/` | Market data adapters (NSE, yfinance) | ✅ Production |
| `infrastructure/adapters/market_data/equity/` | Equity market data adapters | ✅ Production |
| `infrastructure/adapters/market_data/commodity/` | Commodity market data adapters | ✅ Production |
| `infrastructure/adapters/market_data/currency/` | Currency market data adapters | ✅ Production |

### 1.7 Governance & Compliance
| Module | Purpose | Status |
|--------|---------|--------|
| `core/constitution.py` | Constitution Validation Engine (23 categories) | ✅ Production |
| `core/constitution_ai_gate.py` | AI Governance Gate | ✅ Production |
| `core/environment.py` | Environment separation (DEV/QA/PAPER/PRODUCTION) | ✅ Production |
| `core/data_governance.py` | Retention policies + cleanup scheduler | ✅ Production |
| `core/db_migration.py` | Schema versioning + migration registry | ✅ Production |
| `core/auditor/auditor.py` | Independent Auditor (10 categories) | ✅ Production |
| `core/audit_engine.py` | Structured audit trail | ✅ Production |
| `core/config_audit_log.py` | Config change audit log | ✅ Production |
| `core/slo_governance.py` | SLO/SLA Governance (15 SLOs) | ✅ v2.53 |
| `core/capacity_planning.py` | Capacity planning and forecasting | ✅ v2.53 |
| `core/finops.py` | Cost governance and FinOps analysis | ✅ v2.53 |
| `core/version_compatibility.py` | Version compatibility matrix | ✅ v2.53 |

### 1.8 Certification
| Module | Purpose | Status |
|--------|---------|--------|
| `core/certification/strategy_certifier.py` | Strategy certification | ✅ Production |
| `core/certification/replay_certifier.py` | Replay determinism certification | ✅ Production |
| `core/certification/paper_certifier.py` | Paper trading quality certification | ✅ Production |
| `core/certification/gate.py` | Unified certification gate | ✅ v2.53 |

### 1.9 Self-Healing & Observability
| Module | Purpose | Status |
|--------|---------|--------|
| `core/self_healing/orchestrator.py` | Self-healing orchestration (7 patterns) | ✅ v2.53 |
| `core/health_checker.py` | Automated weekly health check | ✅ Production |
| `core/component_health_monitor.py` | Component health monitoring | ✅ Production |
| `core/observability.py` | Observability facade | ✅ Production |
| `core/metrics_exporter.py` | Prometheus metrics exporter | ✅ Production |
| `core/risk_dashboard.py` | Global Risk Dashboard | ✅ v2.53 |

### 1.10 Market Data
| Module | Purpose | Status |
|--------|---------|--------|
| `core/nse_option_recorder.py` | NSE option chain recorder | ✅ Production |
| `core/oi_snapshot_store.py` | Point-in-time OI recorder | ✅ Production |
| `core/ltp_resolver.py` | LTP resolution and caching | ✅ Production |
| `core/data_quality_monitor.py` | Market data anomaly detection | ✅ Production |
| `core/market_data_fallback.py` | Market data source fallback | ✅ Production |
| `core/news_sentinel.py` | Background RSS risk scanner | ✅ Production |
| `core/event_calendar.py` | Budget/RBI/FOMC event filter | ✅ Production |
| `core/fii_dii_tracker.py` | FII/DII institutional flow tracker | ✅ Production |
| `core/implied_move.py` | ATM straddle implied move calculator | ✅ Production |
| `core/gex_analyzer.py` | Gamma Exposure (GEX) analyzer | ✅ Production |

### 1.11 Analytics & Reporting
| Module | Purpose | Status |
|--------|---------|--------|
| `core/performance_metrics.py` | Trade analytics (Sharpe, drawdown, etc.) | ✅ Production |
| `core/pnl_attribution.py` | Multi-dimension P&L breakdown | ✅ Production |
| `core/report_generator.py` | PDF trade report generator | ✅ Production |
| `core/sensitivity_analyzer.py` | Parameter sensitivity analysis | ✅ Production |
| `core/trade_replayer.py` | ASCII bar-chart trade replay | ✅ Production |
| `core/slippage_model.py` | Linear regression slippage calibration | ✅ Production |
| `core/nlp_journal.py` | Post-trade narrative generation | ✅ Production |

### 1.12 Web Dashboard
| Module | Purpose | Status |
|--------|---------|--------|
| `core/web_dashboard.py` | Dashboard startup and signal log | ✅ Production |
| `core/enterprise_dashboard.py` | Enterprise dashboard (FastAPI + Jinja2 + RBAC) | ✅ Production |

### 1.13 Utility & Infrastructure
| Module | Purpose | Status |
|--------|---------|--------|
| `core/config_bootstrap.py` | Config merge + env override | ✅ Production |
| `core/config_engine.py` | Config validation engine | ✅ Production |
| `core/datetime_ist.py` | IST time utilities | ✅ Production |
| `core/time_provider.py` | Authoritative time source | ✅ Production |
| `core/di_container.py` | Dependency injection container | ✅ Production |
| `core/db_utils.py` | Database connection utilities | ✅ Production |
| `core/exceptions.py` | Typed exception hierarchy | ✅ Production |
| `core/safety_state.py` | Hard halt + shutdown events | ✅ Production |
| `core/telegram_queue.py` | Priority queue for Telegram dispatch | ✅ Production |

---

## 2. Scripts (`scripts/`)

| Script | Purpose | Status |
|--------|---------|--------|
| `gap_audit.py` | Adversarial gap audit | ✅ Production |
| `score_system.py` | Automated constitution scoring | ✅ Production |
| `pre_implementation_check.py` | Pre-change compliance validator | ✅ Production |
| `release_governance.py` | Release pipeline automation | ✅ Production |
| `sync_artifacts.py` | Script & artifact sync checker | ✅ Production |
| `institutional_challenge.py` | Adversarial certification | ✅ Production |
| `hygiene_check.py` | Repository hygiene scanner | ✅ Production |
| `scan_dead_code.py` | Dead code scanner | ✅ Production |
| `generate_config_schemas.py` | JSON schema generation | ✅ Production |
| `validate_config_schema.py` | Config validation against schema | ✅ Production |
| `bootstrap_config.py` | Default config creation | ✅ Production |
| `migrate_config.py` | Config format migration | ✅ Production |
| `check_architecture_compliance.py` | Architecture compliance checker | ✅ Production |
| `rollback.py` | Database rollback script | ✅ Production |
| `run_backtest_replay.py` | Backtest replay runner | ✅ Production |
| `run_backtest_suite.py` | Multi-index backtest suite | ✅ Production |
| `run_csv_backtest.py` | CSV-based backtest runner | ✅ Production |
| `run_walkforward.py` | Walk-forward analysis runner | ✅ Production |

---

## 3. Documentation (`docs/`)

| Document | Purpose | Status |
|----------|---------|--------|
| `adr/` | Architecture Decision Records (10+ ADRs) | ✅ |
| `runbooks/` | Operational runbooks (11 runbooks) | ✅ |
| `operations/runbook_template.md` | Runbook template | ✅ |
| `operations/postmortem_template.md` | Postmortem template | ✅ |
| `architecture_governance.md` | Architecture governance framework | ✅ |
| `ownership_matrix.md` | Module ownership matrix | ✅ |
| `technical_debt.md` | Technical debt register | ✅ |
| `dead_code_register.md` | Dead code register | ✅ |
| `duplicate_code_register.md` | Duplicate code register | ✅ |
| `config_drift_register.md` | Configuration drift register | ✅ |
| `doc_drift_register.md` | Documentation drift register | ✅ |
| `constitution_scoring_framework.md` | 23-category scoring criteria | ✅ |

---

## 4. Configuration Files

| File | Purpose | Status |
|------|---------|--------|
| `index_config.defaults.json` | Single source of truth for defaults | ✅ |
| `config.json` | User config (gitignored) | ✅ |
| `config.template.json` | Config template | ✅ |
| `stock_config.defaults.json` | Stock config defaults | ✅ |
| `stock_config.json` | Stock config | ✅ |
| `schemas/index_config.schema.json` | Config JSON schema | ✅ |
| `dashboard_config.json` | Dashboard layout config | ✅ |
| `launcher_settings.json` | Launcher settings | ✅ |
| `.env.example` | Environment variables template | ✅ |
| `pyproject.toml` | Python project metadata | ✅ |

---

## 5. Infrastructure & Deployment

| Artifact | Purpose | Status |
|----------|---------|--------|
| `Dockerfile` | Multi-stage Docker build | ✅ |
| `docker-compose.yml` | Orchestrated Docker services | ✅ |
| `supervisord.conf` | Process manager config | ✅ |
| `bitbucket-pipelines.yml` | CI/CD pipeline | ✅ |
| `.pre-commit-config.yaml` | Pre-commit hooks | ✅ |
| `Makefile` | Build automation | ✅ |

---

## 6. Test Suite (`tests/`)

| Metric | Value |
|--------|-------|
| Total test files | 200+ |
| Total tests | ~2,670 |
| Coverage | >90% (modules with tests) |
| Governance tests | 227 (constitution, AI gate, scoring, pre-impl, release) |
| Chaos tests | 24+ |
| Integration tests | 15+ (trading loop flow) |
| Performance tests | Included in main suite |

---

## 7. Dependency Summary

| Category | Count | Key Libraries |
|----------|-------|---------------|
| Trading | 3 | yfinance, kiteconnect, smartapi-python |
| ML | 3 | lightgbm, scikit-learn, shap |
| Web | 2 | FastAPI, uvicorn |
| Reporting | 1 | reportlab |
| Database | 1 | sqlite3 (stdlib) |
| Security | 2 | bcrypt, pyjwt |
| Infrastructure | 3 | cloudscraper, psutil, redis |
| **Total** | **~15 production deps** | (all in requirements.txt) |
