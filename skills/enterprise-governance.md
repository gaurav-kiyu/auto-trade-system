# Enterprise Governance + Implementation Prompt

## Purpose
This is the ULTIMATE FINAL CONSOLIDATED MASTER GOVERNANCE directive for the OPB (Options Buying Bot) enterprise-grade Indian market AI trading platform. Load this skill to enforce the complete production transformation governance framework.

## When to Load
Load this skill whenever performing:
- Major architecture changes or refactoring
- Security hardening or audit
- Production readiness assessment
- Full forensic codebase review
- Release preparation
- New feature integration governance
- Risk system modifications
- Enterprise dashboard enhancements
- Broker adapter changes or additions
- ML model governance changes

## Core Governance Rules

### System Identity
- **Name:** OPB Index Options Buying Bot v2.53.0+
- **Purpose:** Automated NSE index options buying (NIFTY / BANKNIFTY / FINNIFTY)
- **Python:** 3.10–3.19
- **Platform:** Windows (primary); Linux / Docker compatible

### Absolute System Law
DO NOT implement, patch, refactor, or modify ANYTHING before FULL forensic review and architecture understanding.
NO blind coding. NO shallow modifications. NO unsafe assumptions. NO temporary hacks. NO hidden shortcuts. NO silent fallbacks.

### Phase 0 — Mandatory Forensic System Understanding
Before ANY implementation, perform COMPLETE LINE-BY-LINE REVIEW of ALL files, modules, packages, configs, dependencies, startup paths, shutdown paths, exception boundaries, shared-state boundaries, concurrent execution boundaries, API contracts, state machines, route protection paths, and auth/session lifecycles.

### Mandatory Phase 0 Deliverables
Before implementation, produce:
1. FULL ARCHITECTURE MAP
2. FULL IMPLEMENTATION MODEL
3. HISTORICAL DIFFERENTIAL ANALYSIS
4. DEAD CODE REPORT
5. DUPLICATE CODE REPORT
6. STALE FILE REPORT
7. SECURITY GAP REPORT
8. RELIABILITY GAP REPORT
9. TEST GAP REPORT
10. FUTURE-READINESS GAP REPORT
11. TARGET FINAL ARCHITECTURE BLUEPRINT

### Repository Sanitization
Final repository MUST be PRISTINE. DELETE:
- temp files, cache, stale logs, orphan assets, duplicate modules, dead code, backup files, broken experiments, generated residue, stale reports, stale databases, runtime artifacts
- `.venv`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `build`, `dist`, `tmp`, `temp`, `*.log`, `*.tmp`, `*.bak`, `*.old`

### Git/Source Control Discipline
Final repo MUST have: clean git working tree, zero uncommitted changes, deterministic release artifact, GitHub sync-ready, release-ready, immutable release snapshot.
After every finalized implementation cycle:
1. Create NEW date-wise branch: `feature/YYYY-MM-DD-description`, `release/YYYY-MM-DD`, or `hotfix/YYYY-MM-DD-description`
2. Commit ALL finalized validated changes
3. Push ALL finalized code to GitHub
4. Ensure deterministic clean repo state
5. Tag stable releases where applicable

### Broker-Independent Architecture
System MUST support ANY broker through adapters. NO hardcoded broker assumptions.
Implement: standardized broker contracts, broker adapter interfaces, capability registry, reconciliation, timeout handling, auth-expiry handling, malformed response handling, duplicate prevention.

### Signal-First → Auto-Trading Later
Initial behavior: SIGNAL-FIRST. Later configurable modes: disabled, paper mode, semi-auto, full-auto. Admin MUST fully control execution behavior.

### Multi-Strategy Enterprise Engine
Strategies MUST be: modular, independently configurable, independently enabled/disabled, independently risk-managed, independently backtestable, independently observable.
Supported: TREND (EMA crossover, VWAP trend, Supertrend, Donchian breakout, Momentum breakout), MEAN REVERSION (RSI reversal, Bollinger reversion, VWAP mean reversion), OPTIONS (straddle, strangle, iron condor, gamma breakout, IV expansion/contraction), SCALPING (opening range breakout, liquidity sweep, momentum scalp), INTRADAY (breakout, pullback continuation, VWAP reclaim, range breakout), SWING (ATR breakout, trend continuation, momentum rotation), AI/ML (adaptive signal weighting, strategy scoring, confidence learning, market regime adaptation, parameter optimization).

### Auto-Learning / Adaptive Engine
System MUST support: historical learning, replay learning, adaptive scoring, regime detection, confidence evolution, parameter optimization, historical optimization.
ML MUST NEVER bypass risk engine, config governance, or security controls. ML MUST remain fully explainable and auditable.

### Risk Engine — FAIL CLOSED
Mandatory: leverage caps, exposure caps, drawdown limits, capital protection, stale account protection, stale market-data protection, strategy-wise limits, symbol-wise limits, kill switch, emergency stop, daily loss limits. Drawdown MUST include realized + unrealized PnL.

### Execution Engine
Mandatory: deterministic order lifecycle, deterministic `client_order_id`, idempotency, deduplication, timeout handling, reconciliation, partial-fill handling, cancel safety, unknown-state handling. NO duplicate execution risk.

### Market Data Integrity
Mandatory: stale-data detection, duplicate candle detection, malformed payload rejection, missing OHLCV rejection, NaN rejection, outlier handling, timezone normalization, freshness SLAs. NO signals from uncertain data.

### Failure Semantics — Critical
Eliminate silent failures. FORBIDDEN: `except Exception: pass`, `except Exception: return None`, `except: continue`. Target: `<20` controlled supervisor boundaries only.

### Enterprise Admin Dashboard
Build WORLD-CLASS dashboard quality comparable to TradingView, Stripe, Datadog, Vercel, Linear. MUST include: AUTH (login, logout, password reset, secure sessions), USER MANAGEMENT (RBAC, enable/disable users, session revoke), SYSTEM (health, logs, alerts, uptime, services), TRADING (signals, positions, PnL, exposure, executions, orders), STRATEGIES (enable/disable, weights, configs, confidence thresholds), RISK (leverage, limits, exposure, kill switch), BROKERS (auth state, broker configs, reconciliation state), ML (model versions, confidence, learning metrics), REPLAY (replay controls, analytics), CONFIG GOVERNANCE (diff viewer, rollback, preview, version history, audit trail, atomic apply).

### Auth / Security — Enterprise Grade
Implement: RBAC, secure sessions, CSRF, brute-force protection, secure cookies, anti-session fixation, privilege enforcement, immutable audit trails, secret governance, API hardening, rate limiting. Roles: ADMIN, OPERATOR, VIEWER. NO loopholes. NO unsafe trust assumptions.

### Observability
Mandatory: structured logs, metrics, tracing, alerts, health checks, readiness checks, liveness checks, immutable audit trails.

### Database / Persistence Governance
Mandatory: schema versioning, migration governance, rollback support, transaction integrity, connection pooling, corruption detection, backup validation, restore validation, idempotent writes, locking discipline.

### API Contract Hardening
Mandatory: request validation, response schemas, typed contracts, auth enforcement, RBAC enforcement, timeout boundaries, correlation IDs, versioning, safe errors, pagination.

### Concurrency / Thread Safety
Audit and harden: shared mutable state, execution registries, config races, dashboard concurrency, replay concurrency, broker callbacks, signal/risk/execution races. Implement: locks, atomic transitions, async safety, race prevention.

### Disaster Recovery / Failure Containment
Mandatory: circuit breakers, degraded mode, crash recovery, interrupted execution recovery, broker reconnect recovery, replay recovery, config rollback recovery.

### Feature Flag Governance
Mandatory: feature registry, safe defaults, rollback support, staged rollout, environment-aware rollout, auditability.

### Time Governance
Mandatory: UTC normalization, clock-skew detection, replay determinism, broker timestamp validation, session expiry correctness.

### Dependency Governance
Mandatory: remove abandoned dependencies, remove vulnerable dependencies, deterministic pinning, license validation.

### Testing / Validation
Mandatory: `>=90%` meaningful CRITICAL-PATH coverage. Test: auth, RBAC, replay, execution, reconciliation, risk engine, broker failures, admin controls, config safety, concurrency, security, startup/shutdown, performance, API contracts, strategy isolation. NO fake green tests. NO flaky tests.

### Live Market Validation
After implementation: Perform SAFE live-market validation using paper mode OR protected minimal-risk mode. Validate: signal accuracy, reconciliation, execution latency, broker behavior, dashboard stability, risk protections, alerting, replay consistency.

### 6-Month Backtest Validation
Run full replay/backtesting: LAST 6 MONTHS → TODAY. Use realistic slippage, commissions, latency assumptions. Generate: Sharpe, Sortino, max drawdown, win rate, PnL curves, recovery factor, strategy-wise analytics. Compare against historical versions.

### Mandatory AI Governance Protocol
ALL future AI models, agents, automation systems, and contributors MUST FIRST:
1. Read this ENTIRE governance specification
2. Understand the ENTIRE architecture deeply
3. Review all operational rules
4. Review all security rules
5. Review all risk controls
6. Review all replay determinism rules
7. Review all admin/config governance rules
8. Review all release/testing rules
NO AI model may bypass this protocol. This governance layer is considered CORE SYSTEM LAW.

### Mandatory Feature Acceptance / Integration Governance
NO new feature may be merged directly without STRICT validation through:
1. Architecture Review
2. Isolated Feature Branch Implementation
3. Full Testing & Validation
4. Performance & Benefit Analysis
5. Safe Live Validation
6. Final Acceptance Review
Feature may ONLY be integrated if fully tested, fully validated, beneficial, architecturally safe, replay deterministic, security approved, operationally stable.
Feature quality is MORE important than feature quantity.

### Documentation
Mandatory: architecture docs, deployment guide, admin guide, config guide, runbook, incident guide, recovery guide, release guide, testing guide, security guide.

### Final Forensic Revalidation
After implementation: Repeat COMPLETE LINE-BY-LINE FORENSIC REVIEW.
Confirm: no regressions, no junk, no dead code, no stale configs, no unsafe defaults, no hidden failures, deterministic release artifact, deterministic replay, clean git state, GitHub sync-ready state.

### Final Completion Rule
Implementation is NOT complete until: every unsafe gap is fixed, every critical path validated, repository is pristine, release artifact deterministic, all tests green, replay deterministic, live validation successful, ALL categories exceed `>9.0` with evidence.

### Final Scorecard Thresholds
ALL MUST EXCEED `>9.0`: Architecture, Reliability, Execution Safety, Risk Controls, Security, Authentication, Authorization, UI Quality, UX Quality, Admin Experience, Observability, Test Maturity, Release Engineering, Scalability, Maintainability, Operational Resilience, Broker Robustness, Replay Determinism, ML Governance, Config Governance, Future Readiness, Production Readiness, Repository Hygiene, Deployment Readiness.
If ANY category `<=9.0`: continue remediation automatically. FINAL DELIVERY ONLY.
