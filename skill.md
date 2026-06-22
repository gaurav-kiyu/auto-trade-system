# OPB Index Options Buying Bot — Skills & Capabilities

## Project Identity
- **Name:** OPB Index Options Buying Bot v2.53.0
- **Purpose:** Automated NSE index options buying (NIFTY / BANKNIFTY / FINNIFTY)
- **Python:** 3.10–3.19
- **Platform:** Windows (primary); Linux / Docker compatible

## Core Capabilities

### Trading & Execution
- Multi-index options buying with configurable strategies
- Paper mode (`PAPER_MODE=True`) with realistic fill simulation
- Live execution through Zerodha Kite / Angel Broking adapters
- Exactly-once execution certifier prevents duplicate orders
- WAL journal for write-ahead intent logging

### Signal Generation Pipeline
- IV Rank / IV Percentile scoring (Phase 1)
- Session classifier — time-of-day score adjustment (Phase 3)
- ML LightGBM classifier — 14 features, SHAP explainability (Phase 5)
- Concept drift detection — PSI + KS with auto-retraining
- Multi-factor signal approval workflow with auto-escalation

### Risk Management
- RiskService is final authority — no component bypasses it
- Hard halt (`_trip_hard_halt()`) — kill switch on loss breach
- Maximum daily loss, drawdown, consecutive loss controls
- Kelly sizer, VaR calculator, stress tests, VIX scaling
- Position sizing through configurable rules

### Analytics
- **Factor Models:** Fama-French 3-factor + Carhart 4-factor attribution
- **Max Pain:** Option chain max pain calculation with pain index
- **IV Surface:** Implied volatility surface builder with interpolation
- **P&L Attribution:** Multi-dimension performance breakdown
- **Monte Carlo:** Trade P&L shuffle simulation with drawdown percentiles
- **Sensitivity Analysis:** One-param sweep → ROBUST/SENSITIVE/FRAGILE
- **Walk-Forward:** Rolling + anchored walk-forward validation

### Observability & SRE
- Prometheus metrics on :9090/metrics (24+ gauge/counter metrics)
- **MTTR/MTBF Tracker:** Incident resolution tracking with P50/P90/P99
- **Error Budgets:** Burn rate alerts with dual-window detection
- SLO/SLA governance — 15 tracked SLOs with release gating
- System health checker with 50+ check categories
- Self-healing orchestrator — 13 failure patterns with auto-remediation

### Security
- RBAC — admin/operator/viewer roles with API enforcement
- CSRF token protection with per-request nonces
- Rate limiting — 60 RPM API, 20 RPM admin
- Security headers — HSTS, CSP, X-Frame-Options
- TLS enforcement — SSL cert/key configurable via config
- Secrets management — OPBUYING_* env prefix, no secrets in repo

### Infrastructure
- Docker multi-stage build + docker-compose + supervisord
- Enterprise dashboard — FastAPI + Jinja2 + Tailwind
- SQLite databases — trades.db, trade_journal.db, ml_tracker.db
- Telegram notification system with priority queue

### Governance
- 23-category constitution scoring with evidence enforcement
- Pre-implementation compliance checks
- Release governance pipeline — branch, notes, changelog, tagging
- 11 operational runbooks with auto-execution via RunbookExecutor
- ADR documents — architecture decision records
- Change management — full lifecycle (propose→approve→apply→rollback)

## Architectural Constraints
1. RiskService is the **final authority** — never bypass
2. All broker calls through `core/adapters/broker_adapters.py`
3. No `datetime.now()` — use `core.datetime_ist.now_ist()`
4. Paper mode must NEVER reach a real broker API
5. Config is 3-layer merged: defaults ← config.json ← env vars
6. New features need `try/except` lazy imports and corresponding tests
7. Tests required for every new module in `tests/test_<module>.py`
