# Repository Inventory Report — OPB v2.53.0

**Generated:** 2026-06-03
**Version:** 2.53.0
**Total Files:** ~500+ Python modules, ~200 config/docs/scripts

---

## 1. Source Code

### Entry Points
| File | Purpose | Lines |
|------|---------|-------|
| `index_app/index_trader.py` | Main trading brain | ~8,200 |
| `launcher.py` | GUI launcher wrapper | ~200 |
| `core/enterprise_dashboard.py` | Enterprise web dashboard (FastAPI) | ~2,500 |
| `run_backtest.py` | Offline backtest runner | ~500 |
| `run_analysis.py` | Simulation / analysis runner | ~300 |
| `signal_engine.py` | Root-level signal engine (deprecated) | ~500 |
| `telegram_engine.py` | Root-level Telegram engine (deprecated) | ~400 |

### Core Services (`core/`)
| Module | Purpose |
|--------|---------|
| `core/services/risk_service.py` | **Canonical risk engine** — position sizing, limits, VIX adjustment |
| `core/services/execution_service.py` | Order execution with reconciliation |
| `core/services/notification_service.py` | Telegram/alert dispatch |
| `core/services/persistence_service.py` | State persistence |
| `core/services/portfolio_service.py` | Portfolio tracking |
| `core/services/rate_limiting_service.py` | API rate limiting |
| `core/services/circuit_breaker_service.py` | Circuit breaker state |
| `core/services/broker_health_service.py` | Broker health monitoring |
| `core/services/signal_orchestrator.py` | Signal pipeline orchestration |

### Execution (`core/execution/`)
| Module | Purpose |
|--------|---------|
| `core/execution/order_manager.py` | Order state machine |
| `core/execution/continuous_reconciliation.py` | Background reconciliation |
| `core/execution/deterministic_state_machine.py` | State transition validation |
| `core/execution/durable_state.py` | SQLite crash recovery |
| `core/execution/idempotency/certifier.py` | SHA-256 idempotency |
| `core/execution/idempotency/manager.py` | Duplicate prevention |
| `core/execution/reconciliation/service.py` | Broker-vs-internal sync |
| `core/execution/broker_truth_reconciliation.py` | Authoritative broker state |
| `core/execution/broker_gateway.py` | Broker abstraction |
| `core/execution/shadow_mode.py` | A/B comparison mode |

### Risk (`core/`)
| Module | Purpose |
|--------|---------|
| `core/risk/margin_validator.py` | Margin validation with actual quantity |
| `core/risk/sizing/manager.py` | Position sizing |
| `core/risk/limits/manager.py` | Risk limits |
| `core/risk/greeks_engine.py` | Greeks risk computation |
| `core/risk/legacy_adapter.py` | Backward compatibility adapter |
| `core/safety_state.py` | Centralized kill switch / hard halt |
| `core/kelly_sizer.py` | Half-Kelly position sizing |
| `core/var_calculator.py` | Parametric VaR |
| `core/stress_tester.py` | 4-scenario stress testing |
| `core/capital_manager.py` | Capital tracking |

### Signal Generation
| Module | Purpose |
|--------|---------|
| `core/adaptive_signal.py` | Signal scoring pipeline |
| `core/pure_index_signal.py` | Base signal (RSI, MACD, ADX, PCR) |
| `core/strike_selector.py` | ATM/OTM strike selection |
| `core/iv_rank.py` | IV Rank / IV Percentile |
| `core/ml_classifier.py` | LightGBM win-prob classifier |
| `core/session_classifier.py` | Time-of-day session bands |
| `core/gex_analyzer.py` | Gamma Exposure |
| `core/fii_dii_tracker.py` | Institutional flow |
| `core/implied_move.py` | ATM straddle implied move |

### Governance
| Module | Purpose |
|--------|---------|
| `core/constitution.py` | Constitution Validation Engine |
| `core/constitution_ai_gate.py` | AI Governance Gate |
| `core/constitution_evidence_data.py` | Evidence data for scoring |
| `core/ai/safety_gate.py` | AI action restriction gate |
| `core/ai/governance.py` | AI model governance |
| `core/ai/model_registry.py` | Model metadata registry |
| `core/auditor/auditor.py` | System auditor |
| `core/audit_mode.py` | Audit mode controller |

### Ports (Port/Adapter Pattern)
| Port | Adapter |
|------|---------|
| `broker/broker_port.py` | `infrastructure/adapters/brokers/kite/adapter.py` |
| `market_data.py` | `infrastructure/adapters/market_data/yahoofinance/adapter.py` |
| `persistence/persistence_port.py` | `infrastructure/adapters/persistence/sqlite_adapter.py` |
| `notification/notification_port.py` | `infrastructure/adapters/notifications/telegram_adapter.py` |
| `risk/risk_port.py` | `core/services/risk_service.py` |
| `execution/execution_port.py` | `core/services/execution_service.py` |
| `config/config_port.py` | `infrastructure/config/secure_config_adapter.py` |
| `ml_model/ml_model_port.py` | `infrastructure/adapters/ml_model/ml_model_adapter.py` |
| `circuit_breaker/circuit_breaker_port.py` | `core/services/circuit_breaker_service.py` |

### Strategy
| Module | Purpose |
|--------|---------|
| `core/spread_strategy.py` | Debit spread engine |
| `core/straddle_strategy.py` | Straddle/Strangle engine |
| `core/iron_condor_strategy.py` | Iron Condor credit spread |
| `core/scalein_manager.py` | Two-legged scale-in |
| `core/limit_order_engine.py` | Limit order pricing |
| `core/strategy/strategies.py` | Strategy registry |
| `core/strategy/orchestrator.py` | Strategy orchestration |
| `core/strategy/plugin_framework.py` | Plugin architecture |
| `core/strategy/sandbox.py` | Strategy sandbox |

---

## 2. Testing

| Suite | Files | Count |
|-------|-------|-------|
| Unit tests | `tests/unit/` | 4 files |
| Integration tests | `tests/integration/` | 2 files |
| Chaos tests | `tests/chaos/` | 10 files |
| Broker contract tests | `tests/contract/broker/` | 10 files |
| Core tests | `tests/test_*.py` | ~200 files |
| Acceptance tests | `tests/acceptance/` | 1 file |
| **Total tests** | | **~2670 tests** |

### Test Coverage Areas
- ✅ Smoke tests (8 tests)
- ✅ Constitution & governance (227 tests)
- ✅ Risk controls
- ✅ Execution reconciliation
- ✅ Broker failover
- ✅ Chaos scenarios (ack timeout, broker outage, DB corruption, reconnect storm, stale feed)
- ✅ Certification (paper, replay, strategy)
- ✅ ML classifier & SHAP
- ✅ Greeks engine
- ✅ Config validation & schema
- ✅ Performance metrics
- ✅ Stress testing

---

## 3. Configuration

| File | Purpose |
|------|---------|
| `index_config.defaults.json` | **Single source of truth** — ~860 config keys |
| `config.json` | User config (gitignored) |
| `config.template.json` | Template with documentation |
| `config.dev.json` | Development overrides |
| `config.paper.json` | Paper mode overrides |
| `config.lowcap.json` | Low capital overrides |
| `config.starter.json` | Starter config |
| `stock_config.defaults.json` | Stock defaults |
| `stock_config.template.json` | Stock template |
| `dashboard_config.json` | Dashboard config |
| `schemas/index_config.schema.json` | JSON schema |
| `schemas/stock_config.schema.json` | Stock schema |
| `.env.example` | Environment template |

---

## 4. Documentation

### User Guides
| File | Purpose |
|------|---------|
| `README.md` | Project overview |
| `SETUP_AND_TRADING_GUIDE.md` | Full setup guide |
| `QUICK_START_GUIDE.md` | Quick start |
| `SYSTEM_SETUP_GUIDE.md` | System setup |
| `CONFIG_EXPLANATIONS.md` | Config key explanations |
| `SECRETS_MIGRATION_GUIDE.md` | Secrets migration |
| `RELEASE_NOTES.md` | Release notes |
| `CHANGELOG.md` | Change log |

### Certification Reports
| File | Score |
|------|-------|
| `docs/ARCHITECTURE_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/RISK_CERTIFICATION_REPORT.md` | 9.4/10 |
| `docs/EXECUTION_CERTIFICATION_REPORT.md` | 9.5/10 |
| `docs/SECURITY_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/AI_GOVERNANCE_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/BLACK_SWAN_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/CHAOS_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/DOCUMENTATION_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/MARKET_REGIME_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/OPTIONS_GREEKS_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/PAPER_TRADING_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/PRODUCTION_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/RELEASE_GOVERNANCE_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/REPLAY_CERTIFICATION_REPORT.md` | ✅ PASS |
| `docs/STRATEGY_CERTIFICATION_REPORT.md` | ✅ PASS |

### Architecture & Design
| File | Purpose |
|------|---------|
| `docs/adr/` | 10 Architecture Decision Records |
| `docs/ARCHITECTURE_SUMMARY.pdf` | Architecture summary PDF |
| `docs/ARCHITECTURE_PRESENTATION.pptx` | Architecture presentation |
| `docs/ownership_matrix.md` | Module ownership |
| `docs/technical_debt.md` | Technical debt register |
| `docs/constitution_scoring_framework.md` | Scoring criteria |
| `docs/AI_GOVERNANCE_GUIDE.md` | AI governance protocol |
| `docs/AI_ENGINE_GUIDE.md` | AI engine documentation |

### Operations
| File | Purpose |
|------|---------|
| `docs/deployment/DEPLOYMENT_GUIDE.md` | Deployment guide |
| `docs/deployment/disaster_recovery_plan.md` | DR plan |
| `docs/runbooks/auth_expiry.md` | Auth expiry runbook |
| `docs/runbooks/broker_outage.md` | Broker outage runbook |
| `docs/runbooks/config_corruption.md` | Config corruption runbook |
| `docs/runbooks/db_corruption.md` | DB corruption runbook |
| `docs/runbooks/disk_pressure.md` | Disk pressure runbook |
| `docs/runbooks/network_jitter.md` | Network jitter runbook |
| `docs/runbooks/simultaneous_failover.md` | Simultaneous failover runbook |
| `docs/runbooks/split_brain.md` | Split-brain runbook |
| `docs/runbooks/stale_feed.md` | Stale feed runbook |
| `docs/operator_sop.md` | Standard operating procedures |
| `docs/incident_response_sop.md` | Incident response SOP |

### Registers
| File | Findings |
|------|----------|
| `docs/dead_code_register.md` | 17,128 findings |
| `docs/duplicate_code_register.md` | 5,122 findings |
| `docs/config_drift_register.md` | Config sync tracking |
| `docs/doc_drift_register.md` | Doc-to-code sync tracking |
| `docs/BACKTESTING_REPORT.md` | Backtest results |

---

## 5. Scripts

| Script | Purpose |
|--------|---------|
| `scripts/release_governance.py` | Release pipeline |
| `scripts/score_system.py` | Constitution scoring |
| `scripts/pre_implementation_check.py` | Pre-change validator |
| `scripts/sync_artifacts.py` | Artifact sync checker |
| `scripts/hygiene_check.py` | Repository hygiene |
| `scripts/scan_dead_code.py` | Dead code scanner |
| `scripts/institutional_challenge.py` | Adversarial certification |
| `scripts/generate_config_schemas.py` | Schema generation |
| `scripts/generate_architecture_pdf.py` | PDF report generation |
| `scripts/generate_architecture_pptx.py` | PPTX generation |
| `scripts/archive_artifacts.py` | Artifact archiving |
| `scripts/run_backtest_suite.py` | Multi-index backtesting |
| `scripts/run_regression.py` | Regression testing |

---

## 6. Infrastructure

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage Docker build |
| `docker-compose.yml` | Docker Compose orchestration |
| `supervisord.conf` | Process manager |
| `Makefile` | Build automation |
| `pyproject.toml` | Project metadata |
| `bitbucket-pipelines.yml` | CI/CD pipeline |
| `.github/workflows/ci.yml` | GitHub CI |
| `.github/workflows/prod-release.yml` | Prod release |
| `.github/workflows/weekly-deps.yml` | Weekly dependency check |
| `build_exe.bat` | PyInstaller EXE build |

---

## 7. Known Gaps

| Category | Issue | Severity |
|----------|-------|----------|
| Testing | Smoke tests pass (8/8) but 5 were previously failing due to relative imports — **now fixed** | ✅ RESOLVED |
| Testing | Full test suite (~2670 tests) needs re-evaluation | MEDIUM |
| Config | `CONFIG_VERSION` mismatch: integer (1) in config.json vs string ("2.53.0") in defaults.json | LOW |
| Config | Multiple config files (dev, paper, lowcap, starter) — potential drift | MEDIUM |
| Documentation | Audit logs reference v0.0.0-test and v1.0.0 — needs cleanup | LOW |
| Documentation | Dead code register (17,128 findings) — needs triage | HIGH |
| Security | No stale account detector (per Risk Certification Report) | MEDIUM |
| CI/CD | No pre-commit hooks | MEDIUM |
| CI/CD | build_exe.bat needs automated pipeline integration | LOW |

---

*End of Repository Inventory — v2.53.0*
