# NSE Index Options Buying Bot — Claude Code Context

## Project Identity
- **Name:** OPB Index Options Buying Bot v2.59.0 (see `/VERSION`, the single source of truth for the current version)
- **Purpose:** Automated NSE index options buying (NIFTY / BANKNIFTY / FINNIFTY)
- **Python:** 3.10–3.19 (enforced at startup)
- **Platform:** Windows (primary); Linux / Docker compatible

## Entry Points
| Script | Purpose |
|--------|---------|
| `index_app/index_trader.py` | Main trading brain (1,433 lines) |
| `launcher.py` | GUI launcher wrapper |
| `core/enterprise_dashboard/__init__.py` | Enterprise web dashboard (FastAPI + Jinja2 + RBAC) |
| `run_backtest.py` | Offline backtest runner |
| `run_analysis.py` | Simulation / analysis runner |

## Stack
- **Data:** Yahoo Finance (`yfinance`), NSE API, WebSocket feeds
- **Broker:** Zerodha Kite, Angel Broking — via `core/adapters/broker_adapters.py`
- **DB:** SQLite — `db/trades.db` (trade log), `db/trade_journal.db` (execution quality), `db/ml_tracker.db` (ML predictions), `db/oi_snapshots.db` (OI history)
- **State:** `json/trader_state.json` (capital, PnL, flags — survives restarts)
- **Config:** JSON (3-layer merge: defaults → json/config.json → json/config.local.json → OPBUYING_* env)
- **Notifications:** Telegram Bot API
- **ML:** LightGBM + scikit-learn (`core/ml_classifier.py`) + SHAP explainability
- **Reporting:** ReportLab PDF (`core/report_generator.py`) with Monte Carlo section
- **GUI:** Tkinter (bundled in launcher)
- **Web Dashboard:** FastAPI + uvicorn (`core/web_dashboard.py`, disabled by default)
- **Docker:** Multi-stage Dockerfile + docker-compose.yml + supervisord

## Pre-commit Hook (AI Governance)
- The project has a pre-commit hook (`pre-implementation-governance` in
  `.pre-commit-config.yaml`, backed by `scripts/pre_implementation_check.py`)
  that runs on staged Python files. Activate it once per clone with
  `make install-hooks` (or `pip install pre-commit && pre-commit install`).
- The hook enforces risk-control checks (e.g., modifying SL_PCT, MAX_DRAWDOWN,
  PAPER_MODE, or blocked test files).
- The same check is also enforced in CI as a blocking step (not advisory) —
  `.github/workflows/ci.yml`'s `governance` job and `bitbucket-pipelines.yml`'s
  `&governance-step` reconstruct the PR/push diff and run
  `pre_implementation_check.py --files <changed .py files>`, failing the build
  on a real violation.
- **Reviewed-change allowlist**: a reviewed change to a risk-sensitive pattern
  (e.g. the `--paper` CLI flag wiring that legitimately references `PAPER_MODE`)
  is added to `json/pre_implementation_allowlist.json` instead of bypassing the hook:
  ```bash
  python scripts/pre_implementation_check.py --allow-add index_app/index_trader.py \
      --pattern PAPER_MODE --reason "wire documented --paper CLI flag" --reviewer operator
  python scripts/pre_implementation_check.py --list-allowlist   # audit view
  ```
  The allowlist suppresses only the exact (file, pattern) pair for the risk-pattern
  check — it never covers BLOCKED_CHANGES (test certification files) and is not a
  blanket bypass. Scope note: an entry auto-allows ANY future diff matching the
  same (file, pattern); re-review if risk logic in that file later changes. Entries
  are added only via `--allow-add` (hand-editing the JSON bypasses validation and
  breaks the audit trail). Commit the allowlist JSON along with the change.
- Only genuinely non-risk changes may use `--no-verify` as a documented bypass.
## Test Command
```bash
python -m pytest tests/ -q          # full suite (~14,700 tests)
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
- **`json/index_config.defaults.json`** is the single source of truth for all default values
- Every new config key MUST have a safe default in this file
- After adding any key to defaults, run: `python scripts/generate_config_schemas.py`
- Config is 3-layer merged: defaults ← json/config.json ← json/config.local.json ← `OPBUYING_*` env vars
- Never hardcode a value that belongs in config
- All config keys must be backward-compatible (new keys with safe defaults only)

### OPBUYING_* Env Bridge — Canonical Semantics
`core/config_loader.py` and `index_app/domains/config/loader.py` implement the
**same** env-bridge contract (aligned; keep both in sync):

- **Case-insensitive matching.** `OPBUYING_<KEY>` overrides `<KEY>` in the
  merged config regardless of env-var case (`opbuying_<key>` works too).
- **Type coercion to the existing value.** The env string is coerced to the
  type of the key already present in config — bool (`true/1/yes/on` → `True`),
  int, float, else kept as string.
- **Unknown keys are ignored.** `OPBUYING_*` vars for keys NOT present in the
  config are silently skipped — they never add new config keys. Do not rely on
  env vars to introduce new settings; declare a default first.
- **Broker credential bridge.** `BROKER_CONFIG.<field>_env` names the env var
  that supplies `<field>` (e.g. `api_key_env: "OPBUYING_BROKER_API_KEY"`).
  The plain field is only filled while empty — **explicit config values win**
  over env.
- **Caching.** Env overrides are applied at first `load()` and the result is
  cached; later env changes require a fresh loader instance.

Examples:
```bash
OPBUYING_EXECUTION_MODE=PAPER      # overrides EXECUTION_MODE (string)
OPBUYING_BROKER_API_ENABLED=true   # coerced to bool True
OPBUYING_SOME_UNKNOWN_KEY=x        # IGNORED (key not in config)
OPBUYING_BROKER_API_KEY=secret     # fills BROKER_CONFIG.api_key only if api_key_env declares it
```

Tests: `tests/test_config_loader.py` (`TestBrokerCredentialBridge`, parity
with `tests/test_config_domain_loader.py`).

## Risk Management — Never Touch Without Explicit Instruction
- `MAX_DAILY_LOSS`, `MAX_DRAWDOWN` — hard halt thresholds
- `SL_PCT`, `TARGET_PCT`, `TRAIL_PCT` — exit price multipliers
- `PORTFOLIO_MAX_SL_RISK_PCT` — portfolio-level SL cap
- `_trip_hard_halt()` — the kill-switch function; never bypass or weaken
- `ExpiryDayController.can_enter_position()` (`core/expiry_day_controller.py`,
  called from `PositionService.enter_trade`) — expiry gate; never remove
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
| `core/constitution/__init__.py` | Constitution Validation Engine — 23-category scoring, change pipeline (10-step), pre-implementation checklist, evidence-based scoring enforcement |
| `core/constitution_ai_gate.py` | AI Governance Gate — pre-implementation validation for AI agents, forbidden action detection, risk-control keyword scanning |
| `core/ai/governance.py` | AI model governance — model metadata, registry, approval workflow |
| `docs/adr/0010-architecture-governance.md` | Architecture governance framework — ADR chain, ownership, boundary rules |
| `docs/adr/0011-ml-classifier-architecture.md` | ML Classifier ADR — LightGBM architecture, 14 features, SHAP, drift detection |
| `docs/adr/0012-config-system-architecture.md` | Config System ADR — 3-layer merge, secrets, drift detection, audit trail |
| `docs/adr/0013-monitoring-observability-stack.md` | Monitoring ADR — Prometheus/Loki/Grafana/OpenTelemetry stack |
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
| `docs/runbooks/telegram_outage.md` | Runbook RB-013 — Telegram notification outage recovery procedure |
| `docs/runbooks/yfinance_outage.md` | Runbook RB-014 — yfinance/data provider outage recovery procedure |
| `docs/api_reference.md` | REST API Reference — all 30+ dashboard endpoints, auth, rate limits |
| `docs/GETTING_STARTED_NO_CODE.md` | Click-only walkthrough for non-technical users (v2.59) — no terminal/config editing required, covers `setup.bat`/`open_app.bat`/`open_admin.bat`, the first-run admin login, a dashboard tour, and Telegram/mobile alerts. Complements the CLI-first `docs/HOW_TO_USE_SYSTEM.md`/`USER_GUIDE.md`, doesn't replace them. |
| `docs/MOBILE_APP_PWA_GUIDE.md` | Installable PWA guide (v2.59) — the dashboard is installable to a phone home screen (Android Chrome / iOS Safari, no Play Store/App Store) via `static/dashboard-manifest.json` + `static/opb-icon-*.svg` (new) plus the pre-existing `_pwa_head.html`/`_pwa_sw_reg.html`/`dashboard-sw.js`/`/dashboard-sw.js` route, now wired into all 34 authenticated page templates. Documents the one real caveat: full installability needs HTTPS (or localhost), not a plain LAN IP — two workarounds (Tailscale, local reverse proxy) are given. Condensed version also shown in-app via a collapsible card on `dashboard.html`. |
| `docs/COMPETITIVE_ANALYSIS.md` | Market comparison vs. Streak, Sensibull, Tradetron, AlgoTest, QuantMan, uTrade Algos (compiled 2026-08-21, cited sources) — feature/pricing table, honest strengths/gaps both ways, and SEBI's 2026 retail algo-trading framework's relevance to a future live-execution phase. Re-verify pricing/feature claims before quoting externally, since SaaS details drift. |
| `SECURITY.md` | Security Policy — vulnerability reporting, architecture, data protection |
| `docs/runbooks/runbook_template.md` | Runbook template for new scenarios |
| `docs/runbooks/postmortem_template.md` | Postmortem template for incident analysis |

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
| `core/concept_drift_detector.py` | PSI + KS feature drift detection on db/ml_tracker.db |
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
| `core/services/risk_service.py` | Position sizing, VIX scaling, drawdown sizing; imports `CapitalManager` from `core/capital_manager.py` |
| `core/adapters/broker_adapters.py` | Broker abstraction + PaperBrokerAdapter |
| `core/services/paper_trader.py` | Paper order execution & fill simulation (extracted from ExecutionService) |
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
| `core/strategy/ma_crossover.py` | MA Crossover Strategy — golden/death cross + pullback detection with ADX/volume filtering (v2.54) |
| `core/strategy/mean_reversion.py` | Mean Reversion Strategy — Bollinger Band/RSI/VWAP pullback detection (v2.54) |
| `core/adaptive_signal_score_adjusters.py` | Score adjusters extracted from adaptive_signal.py — IV rank, session, ML, skew, GEX, regime, MA crossover, mean reversion (v2.54) |
| `core/etf_trader.py` | ETF Trader (v2.57.0) — NSE/BSE ETF trading engine, config-driven ETF_MAP; wired via `core/strategy/multi_asset_dispatcher.py` |
| `core/reit_trader.py` | REIT & InvIT Trader (v2.57.0) — NSE/BSE REIT/InvIT trading engine; wired via `multi_asset_dispatcher.py` |
| `core/ipo_trader.py` | IPO/FPO/OFS/QIP Trader (v2.57.0) — primary-market issue subscription/allocation tracking; wired via `multi_asset_dispatcher.py` |
| `core/multi_tenant.py` | Multi-tenant readiness — tenant isolation for institutional deployments, built on the RBAC system; used by the enterprise dashboard |
| `core/positions/bridge.py` | Position Bridge — converts trader position types to domain model types |
| `core/risk/auto_hedger.py` | Portfolio auto-hedging & tail-risk mitigation — scans holdings for Delta/Gamma imbalance, generates 1-click hedge orders; exposed via `/api/v1/admin/auto-hedge` |
| `core/risk/tax_loss_harvester.py` | Tax-loss harvesting opportunity scanner; exposed via `/api/v1/admin/tax-loss-harvest` |
| `core/ai/report_generator.py` | `GenAIReportBuilder` — Gemini/GenAI-based report generation; exposed via `/api/v1/admin/generate-report` |
| `core/ai/agentic_sentiment.py` | Agentic LLM sentiment ingestion/analysis |
| `core/execution/redis_pubsub.py` | Redis pub/sub market-data bus (requires `redis` package) |
| `core/telegram/interactive_approvals.py` | `TelegramInteractiveGate` — interactive Telegram approval flow (e.g. for auto-hedger actions) |
| `core/trading/smart_order_router.py` | Multi-broker smart order router + failover engine — **implemented but not wired into the live trading loop** (no import site found outside its own tests as of this audit) |
| `core/trading/option_strategy_builder.py` | Multi-leg option strategy builder & payoff calculator — **implemented but not wired into the live trading loop** |
| `core/persistence/timeseries_db.py` | `TimeSeriesDataLake` — DuckDB-backed timeseries store — **implemented but not wired into the live trading loop** |
| `infrastructure/security/input_validator.py` | Comprehensive input validation (injection/malformed-data prevention) for external inputs — **implemented but not wired anywhere** (no import site found repo-wide as of this audit, v2.59 dead-code sweep); the enterprise dashboard's FastAPI routes don't use Pydantic `BaseModel` request validation today, so this remains a real, closeable gap rather than a redundant duplicate |
| `core/portfolio/collateral_manager.py` | `CollateralManager`/`SweepAction` — ETF/cash collateral sweep automation — **implemented but not wired anywhere** (no import site found repo-wide as of this audit, v2.59 dead-code sweep); no existing module covers this functionality |
| `core/loop_watchdog.py` | Scan-loop stall detector (v2.59, opt-in `loop_watchdog_enabled`) — detect-and-alert only, wired into `TradingLoopService.run()` |
| `core/config_drift_reloader.py` | Config-drift hot-reload (v2.59, opt-in `config_drift_auto_reload_enabled`) — re-reads `config.json`, hot-applies only a small non-risk-sensitive key allowlist |
| `core/notification_filters.py` | Telegram notification filtering + heartbeat/periodic-summary scheduling (v2.59, opt-in `notification_filters_enabled`/`TG_HEARTBEAT_ENABLED`) |
| `core/signals/signal_tracker.py` | `SignalTracker` — SQLite-backed signal history/delivery tracker (`db/signals_history.db`). `update_active_signal_outcomes()` (v2.59, opt-in `signal_outcome_tracking_enabled`, wired into `TradingLoopService`) grades ACTIVE signals against real price action — the only track record that accumulates in pure `SIGNAL_ONLY` mode, distinct from `live_readiness_checker`'s real-fill-based gate. `mark_order_placed(signal_id, placed, username)` (v2.59) records the admin's own "I actually placed an order off this signal" flag for historical reporting; reachable from both the admin dashboard (`templates/enterprise/admin_signals.html` checkbox → `POST /api/auth/signals/{id}/mark-order-placed`) and Telegram (`/placed`/`/unplaced` in `core/telegram_commander.py`) — one persisted record, not two. `prune_old_signals(max_age_days, archive_dir)` (v2.59, wired into `core/data_governance.py`'s `CleanupScheduler` via `data_retention_signals_*` config keys, default 365 days) is this table's row-level retention — since the file-glob `DataGovernor` categories can't reach into a database and the 2,500+ stock scanner would otherwise grow it forever. Archive-before-delete: aged-out, already-resolved rows are zipped to `backups/signal_archives/` first, deleted only once that write succeeds; `ACTIVE` rows are never touched. |
| `core/telegram_commander.py` | `TelegramCommander` — the one REAL, live Telegram bot in this repo: a background **polling** thread (`getUpdates`, no webhook, so no public HTTPS is needed for an on-prem/local bot) with chat-id + user-id allowlists, rate limiting, and an audit log. Ships `/signal`, `/approve`, `/reject`, `/pending` (all act on `ManualSignalQueue` — new trade *submissions*, not the system-generated signal history) plus `/status`, `/positions`, `/pnl`, `/balance`, and (v2.59) `/placed {signal_id}` / `/unplaced {signal_id}` which call `SignalTracker.mark_order_placed()` directly. **Separate from this**: `all_nse_scanner.py`'s inline "1-Click" Telegram buttons (`callback_data` like `paper:`/`exec:`) and the `/api/telegram/webhook` receiver in `core/enterprise_dashboard/routes/monitoring.py` are DEAD in practice — `setWebhook` is never called anywhere in the codebase, so Telegram never has anywhere to deliver a button tap, and webhook mode would be mutually exclusive with this polling bot's `getUpdates` calls anyway. Don't build on those buttons without first registering a real webhook and giving up polling. |
| `core/live_option_quotes.py` | Live option bid/ask/OI/volume quote feed (v2.59, opt-in `live_option_quotes_enabled`) — builds the real Kite NFO tradingsymbol and fetches a live quote via `KiteBrokerAdapter.get_quote(symbol, exchange="NFO")`; requires `strike_selector_enabled=true` and a real Kite connection (fails open otherwise). NFO symbol format needs live-account validation — see the module docstring. |
| `core/enterprise_dashboard/routes/whats_new.py` | "What's New" page (v2.59) — `/whats-new`, linked from the nav. Parses the newest `## vX.Y.Z (date)` section of the root `CHANGELOG.md` into HTML (minimal purpose-built bold/code/nested-bullet renderer, no new markdown dependency) so admins can discover new features from inside the running dashboard instead of reading repo files by hand. Fails open ("unavailable") on a missing/malformed changelog — never crashes the page. |
| `core/enterprise_dashboard/routes/payoff_calculator.py` | Option strategy payoff-curve calculator (v2.59) — `POST /api/payoff-calculator/compute` + `/payoff-calculator` page. Closes a real gap vs. Sensibull/uTrade Algos found in `docs/COMPETITIVE_ANALYSIS.md`. Read-only decision support: uses only `core/trading/option_strategy_builder.py`'s generic `add_leg()`/`calculate_payoff_profile()` primitives — deliberately never `build_straddle()`/`build_iron_condor()`, which that module's own docstring flags as duplicates of the real, live `core/straddle_strategy.py`/`core/iron_condor_strategy.py` engines. Never places, sizes, or influences a real order. |
| `core/execution/smart_router.py` | Multi-broker order-routing failover (v2.54, opt-in via a `SmartRouter` passed to `ExecutionService`) — as of v2.59, genuinely wired into `ExecutionService._attempt_order_execution()` (previously constructed but never consulted for real order placement). Reachable only once a second real broker is configured (`SECONDARY_BROKER_DRIVER`, currently a placeholder key — automatic secondary-broker construction at startup is not yet connected). |


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
Must run after any change to `json/index_config.defaults.json`:
```bash
python scripts/generate_config_schemas.py
```
Failure to run this breaks `test_config_schema.py`.

## Safety Systems (Never Disable)
- `_HARD_HALT` event — trips on loss breach; blocks all entries
- `_shutdown` event — graceful stop; allows position monitoring to continue
- Circuit breaker — NSE + YF failure rate gate
- Loop watchdog (`core/loop_watchdog.py`, opt-in via `loop_watchdog_enabled`,
  default `false`) — **detect-and-alert only**, wired into
  `TradingLoopService.run()`. Corrects prior doc drift here: no code in this
  repo autonomously kills or restarts a hung scan loop (an operator must act
  on the CRITICAL log / notification it raises).
- Kill file — drop `STOP_TRADING` in project root to halt immediately
- Capital reservation lock — prevents double-spend in concurrent entries
- LTP sanity check — rejects outlier fill prices
- **Master live-trading lockout** (`live_trading_lockout_enabled`, default
  `true`) — enforced in `core/adapters/broker_adapters.py::create_broker_adapter()`,
  the single real choke point every broker construction path (index options,
  ETF/REIT/IPO, stocks) goes through. While enabled, a real `BROKER_DRIVER`
  (Kite/Angel/etc.) is always forced to `PaperBrokerAdapter`, regardless of
  `PAPER_MODE`/`BROKER_API_ENABLED`/`MANUAL_SIGNALS_ONLY`. Only disable after
  a genuinely validated paper-trading track record — do not flip this to
  `false` casually.
- **Automatic live-readiness gate** — even with the lockout above manually
  disabled, `create_broker_adapter()` calls `core.live_readiness_checker.check_live_readiness()`
  before honoring a real driver; if the paper scorecard's 5 blocking criteria
  don't pass (or the check errors for any reason), it still forces
  `PaperBrokerAdapter` (fail-closed). Previously this checker only produced
  an advisory report in the morning checklist with nothing enforcing it —
  that gap is now closed. `live_readiness_min_trading_days` defaults to 20
  (≈1 month of NSE trading days) over a `live_readiness_days_window` of 60
  (≈2 months) — raise `live_readiness_min_trading_days` further if you want
  a longer mandatory validation period before your first live trade.

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
OPBUYING_INDEX_CONFIG=json/config.dev.json python index_app/index_trader.py --paper

# Generate PDF report
python -m core.report_generator --days 30 --mode PAPER

# Regenerate JSON schemas
python scripts/generate_config_schemas.py
```

## Enterprise Dashboard (opt-in)
Set `web_dashboard_enabled: true` in json/config.json to activate the enterprise dashboard.
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
python -m core.trade_replayer --worst 3 --db db/trades.db

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
python scripts/release_governance.py --version 2.59.0    # Full release pipeline (use the current /VERSION)
python scripts/release_governance.py --generate-notes    # Release notes only

# AI governance gate (import into AI agents)
python -c "from core.constitution_ai_gate import get_gate; g=get_gate(); print(g.acknowledge_constitution())"

# Constitution validation engine
python -c "from core.constitution import validate_and_report; validate_and_report()"
```

## Governance Config Keys (v2.54+)
Added to `json/index_config.defaults.json` (now **1,058 keys** total):
- `ENVIRONMENT` — Deployment environment (dev/qa/paper/shadow/staging/production)
- `environment_block_on_violation` — Block startup when prod config has placeholder values
- `db_migration_enabled` — Enable automatic schema version migration on startup
- `data_retention_*` — Per-category retention policies (logs/audit/models/reports/telemetry)
- `cleanup_scheduler_enabled`, `cleanup_scheduler_interval_hours` — Background cleanup scheduler
- `data_dir`, `models_dir`, `reports_dir`, `log_dir` — Directory paths for data governance

## OI Snapshot Cold-Start
`db/oi_snapshots.db` accumulates live OI history during each session.
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
| 17 | `core/services/execution_service.py` + `core/services/paper_trader.py` | **NEW** `PaperTrader` class extracted (~120 lines) | ✅ |
| 18 | `tests/test_paper_trader.py` | **NEW** — 28 unit tests | ✅ |
| 19 | `core/services/risk_service.py` | ~~`CapitalManager` inlined; `core.capital_manager` deleted~~ — **correction:** `core/capital_manager.py` still exists and is imported by `risk_service.py`; this row's original claim was stale documentation, not completed work | ⚠️ |
| 20 | `core/legacy/decision_engine.py` | Deprecation warning → DELETED in v2.54 Phase 3 | ✅ |
| 21 | `docs/README.md` + stale certification files | 10 stale reports deleted | ✅ |
| 22 | **Root cleanup** | 354 files deleted/archived (9 .bak, 1 paper_trading.log, 308 test_recon_*.db, 3 ephemeral commit files, 2 one-time scripts, 31 stale reports) | ✅ |
| 23 | `json/config.template.json` | **140 keys** merged from defaults — **0 missing**, 29 duplicate keys fixed | ✅ |
| 24 | `infrastructure/adapters/brokers/kite/adapter.py` | `datetime.now()` → `now_ist()` at line 406 (Quote timestamp) | ✅ |
| 25 | `docs/AI_GOVERNANCE_GUIDE.md`, `docs/constitution_scoring_framework.md` | Stale version refs updated (v2.44→v2.54.0, v1.0→v2.54.0) | ✅ |

### v2.54 Phase 3 — Legacy Module Deletions

| Module | Modern Replacement | Status |
|--------|-------------------|--------|
| `core/services/use_cases/trading_orchestrator.py` | `core.services.use_cases.trading_orchestrator.TradingOrchestrator` | ✅ BACKWARD-COMPAT WRAPPER |
| `core/strategy/orchestrator.py` | `core.strategy.orchestrator.StrategyOrchestrator` | ✅ BACKWARD-COMPAT WRAPPER |
| `core/capital_manager.py` | N/A — still exists; imported by `core.services.risk_service` | ⚠️ NOT DELETED (doc previously claimed otherwise) |
| `core/legacy/signal_engine.py` | → `core.signal_utils` (extracted to `core.signal_utils` in v2.54) | ✅ DELETED |
| `core/legacy/decision_engine.py` | → `core.tier_engine` (DELETED in v2.54) | ✅ DELETED |
| `core/legacy/telegram_engine.py` | `infra.adapters.notifications.telegram_adapter` | ✅ DELETED |
| `core/legacy/__init__.py` | (DEPRECATED — **DELETED in v2.54**) All imports migrated to `core.signal_utils` |

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
