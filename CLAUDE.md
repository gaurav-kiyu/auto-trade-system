# NSE Index Options Buying Bot — Claude Code Context

## Project Identity
- **Name:** OPB Index Options Buying Bot v2.53.0
- **Purpose:** Automated NSE index options buying (NIFTY / BANKNIFTY / FINNIFTY)
- **Python:** 3.10–3.19 (enforced at startup)
- **Platform:** Windows (primary); Linux / Docker compatible

## Entry Points
| Script | Purpose |
|--------|---------|
| `index_app/index_trader.py` | Main trading brain (~1,640 lines) |
| `launcher.py` | GUI launcher wrapper |
| `core/enterprise_dashboard.py` | Enterprise web dashboard (FastAPI + Jinja2 + RBAC) |
| `run_backtest.py` | Offline backtest runner |
| `run_analysis.py` | Simulation / analysis runner |

## Stack
- **Data:** Yahoo Finance (`yfinance`), NSE API, WebSocket feeds
- **Broker:** Zerodha Kite, Angel Broking — via `core/adapters/broker_adapters.py`
- **DB:** SQLite — `trades.db` (trade log), `trade_journal.db` (execution quality), `ml_tracker.db` (ML predictions), `oi_snapshots.db` (OI history)
- **State:** `trader_state.json` (capital, PnL, flags — survives restarts)
- **Config:** JSON (3-layer merge: defaults → config.json → config.local.json → OPBUYING_* env)
- **Notifications:** Telegram Bot API
- **ML:** LightGBM + scikit-learn (`core/ml_classifier.py`) + SHAP explainability
- **Reporting:** ReportLab PDF (`core/report_generator.py`) with Monte Carlo section
- **GUI:** Tkinter (bundled in launcher)
- **Web Dashboard:** FastAPI + uvicorn (`core/web_dashboard.py`, disabled by default)
- **Docker:** Multi-stage Dockerfile + docker-compose.yml + supervisord

## Test Command
```bash
python -m pytest tests/ -q          # full suite (~2670 tests, ~4.5 min)
python -m pytest tests/ -v          # verbose
python -m pytest tests/test_X.py    # single file
```
All tests must pass before committing any change.

### Key Test Files (Modified/Fixed Recently)
```bash
# Core fixes tested
python -m pytest tests/test_nse_option_recorder.py tests/test_smoke.py tests/test_live_readiness.py -q

# Pre-existing test fixes (Exception→ValueError in orchestrator)
python -m pytest tests/integration/orchestrator/test_trading_orchestrator.py -q

# New 9-phase integration test (trading loop flow)
python -m pytest tests/integration/test_trading_loop_flow.py -v
```

### Governance/Constitution Tests
```bash
# Constitution & AI governance (227 tests)
python -m pytest tests/test_constitution.py -q                  # 66 tests
python -m pytest tests/test_constitution_ai_gate.py -q          # 50 tests
python -m pytest tests/test_score_system.py -q                  # 39 tests
python -m pytest tests/test_pre_implementation_check.py -q      # 34 tests
python -m pytest tests/test_release_governance.py -q            # 38 tests
# Run all governance tests together
python -m pytest tests/test_constitution.py tests/test_constitution_ai_gate.py tests/test_score_system.py tests/test_pre_implementation_check.py tests/test_release_governance.py -q
```

## Config System — Critical Rules
- **`index_config.defaults.json`** is the single source of truth for all default values
- Every new config key MUST have a safe default in this file
- After adding any key to defaults, run: `python scripts/generate_config_schemas.py`
- Config is 3-layer merged: defaults ← config.json ← config.local.json ← `OPBUYING_*` env vars
- Never hardcode a value that belongs in config
- All config keys must be backward-compatible (new keys with safe defaults only)

## Risk Management — Never Touch Without Explicit Instruction
- `MAX_DAILY_LOSS`, `MAX_DRAWDOWN` — hard halt thresholds
- `SL_PCT`, `TARGET_PCT`, `TRAIL_PCT` — exit price multipliers
- `PORTFOLIO_MAX_SL_RISK_PCT` — portfolio-level SL cap
- `_trip_hard_halt()` — the kill-switch function; never bypass or weaken
- `expiry_entry_allowed()` — expiry gate; never remove
- Position sizing logic in `get_position_size()` and `core/services/risk_service.py`

## Broker Abstraction — Strict Rule
All broker API calls MUST go through `core/adapters/broker_adapters.py`.
Never call Kite/Angel SDK directly from `index_trader.py` or any core module.
Paper mode (`PAPER_MODE=True`) must NEVER reach any real broker API method.

## Paper Mode Invariant
When `EXECUTION_MODE=PAPER` or `--paper` CLI flag is set:
- `PaperBrokerAdapter` (from `core/adapters/broker_adapters.py`) handles all fills
- Real broker SDK is never instantiated
- Fill = mid-price ± slippage% with OI/volume liquidity filter
- This invariant is safety-critical — never break it

## Market Hours (IST)
- Session open: 09:15 — Session close: 15:20
- Continuous trading window: 09:20 – 15:20
- No new entries after `NSE_BLOCK_NEW_ENTRIES_FROM_HOUR:MINUTE` (default 15:00)
- Expiry cutoff: `EXPIRY_CUTOFF_HOUR:MIN` (default 13:30) on expiry day
- All time checks use `core/datetime_ist.py` — never use `datetime.now()` directly

## Module Conventions
- New optional features: wrap in `try/except` lazy import blocks (see session_classifier wiring in `adaptive_signal.py` for the pattern)
- New modules go in `core/` with type hints on all public functions
- Every new module needs a corresponding `tests/test_<module>.py`
- SQLite migrations: use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` with `OperationalError` catch
- Never use `datetime.now()` — use `from core.datetime_ist import now_ist`

## Governance & Compliance Modules
| Module | Role |
|--------|------|
| `core/environment.py` | Environment separation — DEV/QA/PAPER/SHADOW/STAGING/PRODUCTION with guard rails |
| `core/db_migration.py` | Schema versioning via PRAGMA user_version + migration registry + decorator |
| `core/data_governance.py` | Retention policies per category (logs/audit/models/reports/telemetry) + cleanup scheduler |
| `core/constitution.py` | Constitution Validation Engine — 23-category scoring, change pipeline (10-step), pre-implementation checklist, evidence-based scoring enforcement |
| `core/constitution_ai_gate.py` | AI Governance Gate — pre-implementation validation for AI agents, forbidden action detection, risk-control keyword scanning |
| `core/ai/governance.py` | AI model governance — model metadata, registry, approval workflow |
| `docs/adr/0010-architecture-governance.md` | Architecture governance framework — ADR chain, ownership, boundary rules |
| `docs/ownership_matrix.md` | Module ownership matrix — every module has a named owner |
| `docs/technical_debt.md` | Technical debt register — 16 items tracked by severity |
| `docs/dead_code_register.md` | Dead Code Register — auto-generated by scan_dead_code.py |
| `docs/duplicate_code_register.md` | Duplicate Code Register — auto-generated by scan_dead_code.py |
| `docs/config_drift_register.md` | Configuration Drift Register — config sync tracking |
| `docs/doc_drift_register.md` | Documentation Drift Register — doc-to-code sync tracking |
| `docs/constitution_scoring_framework.md` | 23-category scoring criteria with objective evidence rules and audit requirements |
| `docs/AI_GOVERNANCE_GUIDE.md` | AI agent constitution acknowledgment protocol and pre-implementation checklist |
| `scripts/score_system.py` | Automated constitution scoring CLI — evaluates 23 categories, evidence collection, CI mode |
| `scripts/pre_implementation_check.py` | Mandatory pre-change compliance validator — architecture, risk controls, blocked files, release state |
| `scripts/release_governance.py` | Release pipeline automation — branch creation, release notes, changelog, audit records, tagging |
| `scripts/sync_artifacts.py` | Script & Artifact Synchronization checker — scripts, docs, configs, env.example sync |
| `scripts/institutional_challenge.py` | Adversarial certification framework — risk bypass, bug scan, race conditions, data leakage |
| `scripts/hygiene_check.py` | Repository Hygiene — scans for forbidden artifacts, stale reports, .gitignore gaps |
| `scripts/scan_dead_code.py` | Dead Code Scanner — unused imports, orphaned symbols, duplicate implementations |
| `docs/runbooks/` | Incident runbooks — broker outage, auth expiry, DB corruption, stale feed |
| `docs/operations/runbook_template.md` | Runbook template for new scenarios |
| `docs/operations/postmortem_template.md` | Postmortem template for incident analysis |

## Key Core Modules
| Module | Role |
|--------|------|
| `core/adaptive_signal.py` | Signal scoring pipeline (IV rank → session → ML → tier) |
| `core/pure_index_signal.py` | Base signal generation (RSI, MACD, ADX, PCR, breakout…) |
| `core/strike_selector.py` | ATM / OTM / DELTA strike selection (Phase 4) |
| `core/session_classifier.py` | Time-of-day session bands + score adjustment (Phase 3) |
| `core/iv_rank.py` | IV Rank / IV Percentile via VIX (Phase 1) |
| `core/ml_classifier.py` | LightGBM win-prob classifier, 14 features, SHAP explainability |
| `core/ml_performance_tracker.py` | SQLite-backed prediction calibration + Brier score |
| `core/concept_drift_detector.py` | PSI + KS feature drift detection on ml_tracker.db |
| `core/oi_snapshot_store.py` | Point-in-time OI recorder (no look-ahead bias) |
| `core/monte_carlo.py` | Trade P&L shuffle simulation — drawdown percentiles |
| `core/signal_autopsy.py` | Win-rate breakdown by score/regime/direction/session |
| `core/spread_strategy.py` | Debit spread engine (disabled by default) |
| `core/walkforward_engine.py` | Rolling + anchored walk-forward validation |
| `core/web_dashboard.py` | FastAPI dashboard — signals, metrics, autopsy, Monte Carlo |
| `core/correlation_guard.py` | Cross-index correlation block (Phase 8) |
| `core/event_calendar.py` | Budget/RBI/FOMC event day filter (Phase 7D) |
| `core/report_generator.py` | PDF trade report + Monte Carlo section via ReportLab |
| `core/config_bootstrap.py` | Config merge + OPBUYING_* env override (Phase 7B) |
| `core/performance_metrics.py` | Trade analytics — win rate, Sharpe, drawdown, insights |
| `core/trade_journal.py` | Execution quality journal (slippage, delay, fill tracking) |
| `core/services/risk_service.py` | Position sizing, VIX scaling, drawdown sizing |
| `core/adapters/broker_adapters.py` | Broker abstraction + PaperBrokerAdapter |
| `core/liquidity_guard.py` | Pre-entry bid-ask spread + OI + volume filter (v2.44 Item 1) |
| `core/reentry_evaluator.py` | Per-index cooldown + score gate after stop-loss (v2.44 Item 2) |
| `core/intraday_performance_monitor.py` | Adaptive position size / score on session win rate (v2.44 Item 9) |
| `core/benchmark.py` | Buy-and-hold ^NSEI benchmark + alpha metrics (v2.44 Item 10) |
| `core/news_sentinel.py` | Background RSS risk scanner — NONE/ELEVATED/HIGH/EXTREME (v2.44 Item 12) |
| `core/telegram_queue.py` | Min-heap priority queue for Telegram dispatch (v2.44 Item 7) |
| `core/trade_replayer.py` | ASCII bar-chart replay of any closed trade; CLI + web endpoint (v2.44 Item 14) |
| `core/sensitivity_analyzer.py` | One-param sweep → ROBUST/SENSITIVE/FRAGILE; CLI + web endpoint (v2.44 Item 15) |
| `core/health_checker.py` | DB/ML/perf/config/disk health check; Sunday EOD + CLI + web endpoint (v2.44 Item 17) |
| `core/live_readiness_checker.py` | Paper scorecard gates LIVE execution; 5 blocking criteria (v2.44 Item 19) |
| `core/ab_strategy_tester.py` | CONTROL vs VARIANT paper A/B with Mann-Whitney significance (v2.44 Item 20) |
| `core/fii_dii_tracker.py` | FII/DII institutional flow tracker + score adjustment (v2.45 Item 1) |
| `core/implied_move.py` | ATM straddle implied move calculator + entry gate (v2.45 Item 2) |
| `core/gex_analyzer.py` | Gamma Exposure (GEX) with Black-Scholes gamma + gamma flip level (v2.45 Item 3) |
| `core/regime_transition_detector.py` | ADX/MACD/VIX regime transition detection + score bonus (v2.45 Item 4) |
| `core/kelly_sizer.py` | Half-Kelly position sizing from historical win/loss record (v2.45 Item 6) |
| `core/var_calculator.py` | Parametric VaR at 95/99 confidence levels (v2.45 Item 7) |
| `core/stress_tester.py` | 4-scenario stress test engine: FLASH_CRASH / SLOW_GRIND / GAP_UP / EXPIRY_CRUSH (v2.45 Item 8) |
| `core/scalein_manager.py` | Two-legged scale-in entry: leg1 at signal, leg2 on pullback or timeout (v2.45 Item 9) |
| `core/straddle_strategy.py` | Straddle/Strangle debit strategy engine (v2.45 Item 10) |
| `core/iron_condor_strategy.py` | Iron Condor credit spread engine with inverted P&L logic (v2.45 Item 11) |
| `core/limit_order_engine.py` | Limit order pricing (AGGRESSIVE/PASSIVE/ADAPTIVE) + paper fill simulation (v2.45 Item 12) |
| `core/pnl_attribution.py` | P&L breakdown by direction/regime/session/score/day (v2.45 Item 13) |
| `core/slippage_model.py` | Linear regression slippage auto-calibration from trade journal (v2.45 Item 14) |
| `core/underlying_analyzer.py` | BANKNIFTY constituent stock breadth analyzer (v2.45 Item 16) |
| `core/nlp_journal.py` | Post-trade narrative generation via Claude API (v2.45 Item 17) |
| `core/param_optimizer.py` | Walk-forward parameter sweep optimizer with CLI (v2.45 Item 18) |
| `core/metrics_exporter.py` | Prometheus metrics export on configurable HTTP port (v2.45 Item 19) |
| `core/wal/journal.py` | Write-Ahead Intent Journal with cached SQLite connection + close() (v2.45 Item 20) |
| `core/execution/idempotency/certifier.py` | Exactly-Once Execution Certifier with cached SQLite connection + close() (v2.45 Item 20) |
| `core/broker_failover.py` | Thread-safe broker failover manager with recovery window (v2.45 Item 20) |

## Enhancement Phases — All Complete
| Phase | Feature | Status |
|-------|---------|--------|
| 1 | IV Rank / IV Percentile | ✅ |
| 2 | Realistic Paper Fill Simulation | ✅ |
| 3 | Time-of-Day Session Classifier | ✅ |
| 4 | Greeks-Aware Strike Selection | ✅ |
| 5 | ML Signal Classifier (LightGBM) | ✅ |
| 6 | PDF Report Generator (ReportLab) | ✅ |
| 7A | Heartbeat | ✅ |
| 7B | OPBUYING_* env prefix secrets | ✅ |
| 7C | Package refactor | ✅ |
| 7D | Event Calendar filter | ✅ |
| 8 | Multi-Instrument Correlation Guard | ✅ |
| A1 | OI Snapshot Store (point-in-time, no look-ahead) | ✅ |
| A2 | Realistic Paper Fill with OI liquidity filter | ✅ |
| A3–A6 | Monte Carlo simulation + config keys | ✅ |
| A7–A9 | Tests for OI store + Monte Carlo; schema regen | ✅ |
| B | SHAP explainability + ML Performance Tracker | ✅ |
| C | Concept Drift Detector (PSI + KS) | ✅ |
| D | Debit Spread Strategy engine (opt-in) | ✅ |
| E | Anchored Walk-Forward validation mode | ✅ |
| F | Signal Autopsy (win-rate diagnostics) | ✅ |
| G | Web Dashboard (FastAPI, opt-in) | ✅ |
| H | Docker / docker-compose / supervisord | ✅ |
| I | FEATURE_COLS 9→14, ML tracker wiring end-to-end | ✅ |
| v2.44-1 | Liquidity Guard (bid-ask + OI + volume filter) | ✅ |
| v2.44-2 | Re-entry Evaluator (cooldown + score gate) | ✅ |
| v2.44-3 | Spread Partial Exit + theta decay | ✅ |
| v2.44-4 | Expiry Day Sessions (MORNING/MIDDAY/CAUTION/BLOCKED) | ✅ |
| v2.44-5 | Market Day Check (sleep on holidays, wake at open) | ✅ |
| v2.44-6 | Config Audit Trail (JSONL + CRITICAL/HIGH/NORMAL alerts) | ✅ |
| v2.44-7 | Telegram Priority Queue (CRITICAL<HIGH<NORMAL<LOW heap) | ✅ |
| v2.44-8 | Log Rotation Upgrade (50 MB, gzip, error-only handler) | ✅ |
| v2.44-9 | Intraday Performance Monitor (NORMAL→CAUTIOUS→DEFENSIVE) | ✅ |
| v2.44-10 | Benchmark Comparison (buy-and-hold alpha metrics) | ✅ |
| v2.44-11 | IV Skew (25-delta put/call skew + EXTREME CALL penalty) | ✅ |
| v2.44-12 | News Sentinel (background RSS risk scanner) | ✅ |
| v2.44-14 | Trade Replay Visualizer (ASCII bar-chart, CLI + web) | ✅ |
| v2.44-15 | Parameter Sensitivity Analyzer (ROBUST/SENSITIVE/FRAGILE) | ✅ |
| v2.44-16 | Position Heatmap (win% by hour×day in EOD + web) | ✅ |
| v2.44-17 | Automated Weekly Health Check (Sunday EOD, CLI + web) | ✅ |
| v2.44-18 | Signal Confidence Interval (Wilson 95% CI win-rate band) | ✅ |
| v2.44-19 | Live Readiness Checker (5 blocking criteria, startup gate) | ✅ |
| v2.44-20 | A/B Strategy Tester (Mann-Whitney, JSON state, paper only) | ✅ |
| v2.45-1  | FII/DII Institutional Flow Tracker | ✅ |
| v2.45-2  | Implied Move Calculator (ATM straddle gate) | ✅ |
| v2.45-3  | GEX Analyzer (Black-Scholes gamma + gamma flip) | ✅ |
| v2.45-4  | Regime Transition Detector (ADX/MACD/VIX signals) | ✅ |
| v2.45-5  | Timeframe Divergence Alerts (1m/5m/15m agreement) | ✅ |
| v2.45-6  | Kelly Criterion Half-Kelly Position Sizer | ✅ |
| v2.45-7  | Parametric VaR Calculator (95/99 CI) | ✅ |
| v2.45-8  | Stress Test Engine (4 scenarios + custom) | ✅ |
| v2.45-9  | Scale-In Manager (two-legged pullback entry) | ✅ |
| v2.45-10 | Straddle/Strangle Strategy Engine (debit) | ✅ |
| v2.45-11 | Iron Condor Strategy Engine (credit, inverted P&L) | ✅ |
| v2.45-12 | Limit Order Engine (AGGRESSIVE/PASSIVE/ADAPTIVE) | ✅ |
| v2.45-13 | P&L Attribution Analysis (multi-dimension breakdown) | ✅ |
| v2.45-14 | Slippage Auto-Calibration (linear regression) | ✅ |
| v2.45-15 | Corporate Action Calendar (dividend/split/bonus) | ✅ |
| v2.45-16 | Underlying Stock Analyzer (BANKNIFTY breadth) | ✅ |
| v2.45-17 | NLP Trade Journal (Claude API post-trade narrative) | ✅ |
| v2.45-18 | Walk-Forward Parameter Optimizer (CLI) | ✅ |
| v2.45-19 | Prometheus Metrics Exporter (:9090/metrics) | ✅ |
| v2.45-20 | Broker Failover Manager (threshold + recovery) | ✅ |
| v2.45-21 | Webhook Signal Receiver (POST /signals/inject) | ✅ |
| v2.45-22 | Options Chain Visualization (GET /chain/{index}) | ✅ |

## ML Classifier Features (v2.44)
14 features total: `score`, `confidence`, `direction_call`, `is_strong`, `is_moderate`,
`is_weak`, `has_soft_blocks`, `day_of_week`, `hour_of_entry`, `iv_rank`, `vix`, `pcr`,
`regime_code`, `session_code`

Existing 9-feature models load and predict safely (predict_win_prob returns 0.5 on mismatch).
Retrain with new data to activate the extended feature set.

## Correlated Index Pairs (Phase 8)
NIFTY ↔ BANKNIFTY, NIFTY ↔ FINNIFTY, BANKNIFTY ↔ FINNIFTY
Correlation guard blocks same-direction simultaneous entries when Pearson r ≥ 0.85 over last 20 bars.

## Schema Regeneration
Must run after any change to `index_config.defaults.json`:
```bash
python scripts/generate_config_schemas.py
```
Failure to run this breaks `test_config_schema.py`.

## Safety Systems (Never Disable)
- `_HARD_HALT` event — trips on loss breach; blocks all entries
- `_shutdown` event — graceful stop; allows position monitoring to continue
- Circuit breaker — NSE + YF failure rate gate
- Watchdog thread — kills hung scan loop
- Kill file — drop `STOP_TRADING` in project root to halt immediately
- Capital reservation lock — prevents double-spend in concurrent entries
- LTP sanity check — rejects outlier fill prices

## Running the Bot
```bash
# Paper mode (safe, no real orders)
python index_app/index_trader.py --paper
python index_app/index_trader.py --paper --debug  # verbose debug logging

# Launcher GUI (double-click friendly EXE)
./OPBuying_INDEX_Launcher.exe
# Launcher supports: PAPER (simulation) and MANUAL (signals only) modes
# Launcher installs missing packages automatically

# Docker (paper mode default)
docker compose up -d
docker compose logs -f opb

# Custom config via env
OPBUYING_INDEX_CONFIG=config.dev.json python index_app/index_trader.py --paper

# Generate PDF report
python -m core.report_generator --days 30 --mode PAPER

# Regenerate JSON schemas
python scripts/generate_config_schemas.py
```

## Enterprise Dashboard (opt-in)
Set `web_dashboard_enabled: true` in config.json to activate the enterprise dashboard.
- **FastAPI + Jinja2 + RBAC auth** — runs on port 8765
- Full admin UI: config editor, user management, kill switch, audit log
- Auth routes: `/login`, `/register`, `/change-password`
- API endpoints: `/api/system/state`, `/api/system/trades`, `/api/system/health`, `/api/system/signals`
- Admin API: `/api/config/*`, `/api/auth/users/*`, `/api/system/kill`
- Docker health: `GET /api/system/health/docker` (no auth)

## CLI Tools
```bash
# Replay a closed trade bar-by-bar in the terminal
python -m core.trade_replayer --id 42
python -m core.trade_replayer --last 5
python -m core.trade_replayer --worst 3 --db trades.db

# Parameter sensitivity analysis (ROBUST/SENSITIVE/FRAGILE)
python -m core.sensitivity_analyzer --param SL_PCT --days 60
python -m core.sensitivity_analyzer          # all params

# System health check
python -m core.health_checker
python -m core.health_checker --format json

# Live readiness check (paper→live gate)
python -m core.live_readiness_checker
python -m core.live_readiness_checker --format json

# A/B strategy tester state
python -m core.ab_strategy_tester
python -m core.ab_strategy_tester --reset

# Constitution scoring & governance
python scripts/score_system.py                          # Full report
python scripts/score_system.py --category RSK-01        # Single category
python scripts/score_system.py --json --check-min 6.0   # CI mode
python scripts/pre_implementation_check.py --files core/foo.py
python scripts/pre_implementation_check.py --check-risk
python scripts/release_governance.py --check             # Pre-release check
python scripts/release_governance.py --version 2.54.0    # Full release pipeline
python scripts/release_governance.py --generate-notes    # Release notes only

# AI governance gate (import into AI agents)
python -c "from core.constitution_ai_gate import get_gate; g=get_gate(); print(g.acknowledge_constitution())"

# Constitution validation engine
python -c "from core.constitution import validate_and_report; validate_and_report()"
```

## Governance Config Keys (v2.53+)
Added to `index_config.defaults.json` (now ~860 keys total):
- `ENVIRONMENT` — Deployment environment (dev/qa/paper/shadow/staging/production)
- `environment_block_on_violation` — Block startup when prod config has placeholder values
- `db_migration_enabled` — Enable automatic schema version migration on startup
- `data_retention_*` — Per-category retention policies (logs/audit/models/reports/telemetry)
- `cleanup_scheduler_enabled`, `cleanup_scheduler_interval_hours` — Background cleanup scheduler
- `data_dir`, `models_dir`, `reports_dir`, `log_dir` — Directory paths for data governance

## OI Snapshot Cold-Start
`oi_snapshots.db` accumulates live OI history during each session.
Needs ~90 days before `strict_oi=true` backtest results are reliable.
Bot logs a warning at startup if the DB is younger than 90 days.

## Recent Bug Fixes (All Rounds)

| # | File | Fix | Status |
|---|------|-----|--------|
| 1 | `index_app/index_trader.py` | `.tolist()` → `.to_list()` (pandas API compatibility) | ✅ |
| 2 | `index_app/index_trader.py` (16×) | `_log` → `log` (was `NameError` at runtime) | ✅ |
| 3 | `infra/adapters/market_data/nse/adapter.py` | Added `_init_nse_session()` — homepage cookie init for NSE auth | ✅ |
| 4 | Same file | 403/404 retry with automatic session re-init | ✅ |
| 5 | Same file | Fixed `LoggingService.info()` printf-style crash: `"...%d", code` → `f"...{code}..."` | ✅ |
| 6 | Same file | Multi-strategy HTTP session: `cloudscraper` > `requests` > `urllib` | ✅ |
| 7 | `core/nse_option_recorder.py` | Module-level adapter cache for session persistence across scan cycles | ✅ |
| 8 | `tests/test_nse_option_recorder.py` | Test isolation via `reset_nse_adapter_cache()` | ✅ |
| 9 | `tests/integration/test_trading_loop_flow.py` | **New** — 15-test integration suite (9 original + 6 edge case gates) | ✅ |
| 10 | `launcher.py` | Single-instance lock — prevents duplicate EXE launches | ✅ |
| 11 | `launcher.py` | Thread-safe Tkinter — queue-based `_poll_updates()`, safe messagebox | ✅ |
| 12 | `tests/.../test_trading_orchestrator.py` | `Exception()` → `ValueError()` in 2 test methods (pre-existing) | ✅ |
| 13 | `dist/OPBuying_INDEX_Launcher.exe` | Rebuilt with all fixes (11.6 MB) | ✅ |
| 14  | `index_app/index_trader.py` | Added missing `PositionSizingInput` import — fixes `NameError` in `get_position_size()` | ✅ |
| 15  | `infra/adapters/market_data/nse/adapter.py` | Enhanced `_make_request_with_retry()` logging with `_session_type` and exception type | ✅ |
| 16  | `tests/integration/test_trading_loop_flow.py` | Added 6 edge case integration tests (expiry gate, news block, max-age exit, auction, correlation guard, reentry evaluator) | ✅ |

### NSE 403 (Akamai) — Known External Limitation
NSE India uses **Akamai App & API Protector** which blocks all automated scraping
(requests, cloudscraper, curl_cffi, nselib all return 403). The system gracefully
degrades to **yfinance** for LTP and OHLCV data (confirmed working: NIFTY 23363.35).
The NSE option chain (OI/PCR) is a **nice-to-have enhancement**, not a hard dependency
— signal generation works from index price/volume data alone.

### Data Source Priority (Free Tier)
1. **yfinance** (✅ working) — LTP, intraday 1m/5m/15m, daily OHLCV, Volume
2. **Broker API** (optional, requires account) — Kite Connect can provide live WebSocket feeds
3. **NSE direct** (⚠️ blocked by Akamai) — option chain data not available without license
