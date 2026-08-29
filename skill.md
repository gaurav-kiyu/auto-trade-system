# OPB Index Options Buying Bot — Skills & Capabilities

## Project Identity
- **Name:** OPB Index Options Buying Bot v2.57.1
- **Purpose:** Automated NSE index options buying (NIFTY / BANKNIFTY / FINNIFTY)
- **Python:** 3.10–3.19
- **Platform:** Windows (primary); Linux / Docker compatible
- **Python Files:** ~1,200+ | **Test Files:** 471+ | **Core Modules:** ~300+
- **Docs:** 220+ markdown, 13 ADRs, 14 runbooks, 10+ inventories
- **Certification Score:** 9.55/10.0 Enterprise Grade (certification: 2026-07-27)
- **Certification Verdict:** ✅ **ENTERPRISE CERTIFIED** — Institutional Grade
- **Benchmark Suite:** `scripts/run_benchmarks.py` — P50/P90/P95/P99 tracking
- **Code Quality Tool:** `scripts/run_code_quality_report.py` — CC/MI/nesting analysis
- **Coverage Tool:** `scripts/run_coverage_heatmap.py` — heatmap visualization

## Core Capabilities

### Trading & Execution
- Multi-index options buying with configurable strategies
- Paper mode (`PAPER_MODE=True`) with realistic fill simulation
- Live execution through Zerodha Kite / Angel Broking adapters
- Exactly-once execution certifier prevents duplicate orders
- WAL journal for write-ahead intent logging
- Multi-Broker Smart Router — 4 routing strategies (lowest_fee/round_robin/weighted/preferred)
- Limit order engine — AGGRESSIVE/PASSIVE/ADAPTIVE pricing
- Scale-in manager — two-legged pullback entry

### Signal Generation Pipeline
- IV Rank / IV Percentile scoring (Phase 1)
- Session classifier — time-of-day score adjustment (Phase 3)
- ML LightGBM classifier — 14 features, SHAP explainability (Phase 5)
- Concept drift detection — PSI + KS with auto-retraining
- Multi-factor signal approval workflow with auto-escalation
- MA Crossover Strategy — golden/death cross + pullback detection
- Mean Reversion Strategy — Bollinger Band/RSI/VWAP pullback detection
- Score adjusters — IV rank, session, ML, skew, GEX, regime, MA crossover, mean reversion

### Risk Management
- RiskService is final authority — no component bypasses it
- Hard halt (`_trip_hard_halt()`) — kill switch on loss breach
- Maximum daily loss, drawdown, consecutive loss controls
- Kelly sizer, VaR calculator, stress tests, VIX scaling
- Position sizing through configurable rules
- Portfolio Greeks — delta, gamma, theta, vega aggregation
- Correlation guard — cross-index correlation block (r ≥ 0.85)
- Liquidity guard — bid-ask spread + OI + volume filter
- Re-entry evaluator — cooldown + score gate after stop-loss
- Fail-closed architecture — all unhandled errors halt trading

### Analytics
- **Factor Models:** Fama-French 3-factor + Carhart 4-factor attribution
- **Max Pain:** Option chain max pain calculation with pain index
- **IV Surface:** Implied volatility surface builder with interpolation
- **P&L Attribution:** Multi-dimension performance breakdown
- **Monte Carlo:** Trade P&L shuffle simulation with drawdown percentiles
- **Sensitivity Analysis:** One-param sweep → ROBUST/SENSITIVE/FRAGILE
- **Walk-Forward:** Rolling + anchored walk-forward validation
- **Parametric VaR:** 95/99 confidence level calculations
- **Stress Testing:** 4 scenarios (FLASH_CRASH / SLOW_GRIND / GAP_UP / EXPIRY_CRUSH)
- **PnL Attribution:** Direction/regime/session/score/day breakdown
- **Slippage Auto-Calibration:** Linear regression from trade journal
- **FII/DII Tracker:** Institutional flow tracking + score adjustment
- **GEX Analyzer:** Gamma Exposure with Black-Scholes gamma + gamma flip
- **Underlying Analyzer:** BANKNIFTY constituent stock breadth analysis

### Observability & SRE
- Prometheus metrics on :9090/metrics (24+ gauge/counter metrics)
- **MTTR/MTBF Tracker:** Incident resolution tracking with P50/P90/P99
- **Error Budgets:** Burn rate alerts with dual-window detection
- SLO/SLA governance — 15 tracked SLOs with release gating
- System health checker with 50+ check categories
- Self-healing orchestrator — 13 failure patterns with auto-remediation
- OpenTelemetry tracing integration
- Loki log aggregation (deploy/loki/)
- Grafana dashboards (deploy/grafana/)
- Live health endpoint: GET /api/system/health/docker

### Security
- RBAC — admin/operator/viewer roles with API enforcement
- CSRF token protection with per-request nonces
- Rate limiting — 60 RPM API, 20 RPM admin
- Security headers — HSTS, CSP, X-Frame-Options
- TLS enforcement — SSL cert/key configurable via config
- Secrets management — OPBUYING_* env prefix, no secrets in repo
- MFA support (TOTP) for admin accounts
- Session management with secure cookie flags
- Audit logging — JSONL audit trail for all config changes
- Environment separation — DEV/QA/PAPER/SHADOW/STAGING/PRODUCTION
- Input validation — Pydantic models on all API endpoints
- ML model security — safe deserialization with pickle protocol restriction

### Infrastructure
- Docker multi-stage build + docker-compose + supervisord
- Enterprise dashboard — FastAPI + Jinja2 + Tailwind on port 8765
- SQLite databases — db/trades.db, db/trade_journal.db, db/ml_tracker.db, db/oi_snapshots.db
- Telegram notification system with priority queue (CRITICAL/HIGH/NORMAL/LOW)
- Config audit trail — JSONL with change level alerts
- Log rotation — 50 MB, gzip compression, error-only handler

### Governance
- 23-category constitution scoring with evidence enforcement
- Pre-implementation compliance checks
- Release governance pipeline — branch, notes, changelog, tagging
- 14 operational runbooks with auto-execution via RunbookExecutor
- 13 ADR documents — architecture decision records
- Change management — full lifecycle (propose→approve→apply→rollback)
- AI Governance Gate — pre-implementation validation for AI agents
- Comprehensive documentation inventory (55+ documents)
- FULL_CERTIFICATION_REPORT — 24-category scorecard (docs/certification/)
- Historical comparison — previous vs current version tracking

## Architectural Constraints
1. RiskService is the **final authority** — never bypass
2. All broker calls through `core/adapters/broker_adapters.py`
3. No `datetime.now()` — use `core.datetime_ist.now_ist()`
4. Paper mode must NEVER reach a real broker API
5. Config is 3-layer merged: defaults ← json/config.json ← env vars
6. New features need `try/except` lazy imports and corresponding tests
7. Tests required for every new module in `tests/test_<module>.py`
8. All config changes must be auditable and rollbackable
9. System must fail closed on any unhandled error
10. Production release requires certification gates
11. **Mandatory Live Testing & Pre/Post-Guard Governance Protocol (`docs/skills/MANDATORY_LIVE_TESTING_GOVERNANCE_SKILL.md`)**:
    - Pre-implementation check (`python scripts/pre_implementation_check.py --verify-analysis`) MUST run FIRST.
    - Full real-time endpoint & navigation route verification (`python scratch/test_page_routes_only.py`) MUST pass 100%.
    - Log evidence must be extracted & inspected to resolve all warnings/exceptions before completion.
    - Post-execution audits (`python scripts/check_db_integrity.py` and `python scripts/run_pr_audit.py`) MUST yield 100% OK scores.

## Quick Start
```bash
# Paper mode (safe, no real orders)
python index_app/index_trader.py --paper

# Run full test suite
python -m pytest tests/ -q

# Enterprise dashboard
# Set web_dashboard_enabled: true in json/config.json, then:
python -m core.enterprise_dashboard.main

# Generate PDF trade report
python -m core.report_generator --days 30 --mode PAPER

# View certification scorecard
cat docs/certification/FINAL_EVIDENCE_SCORECARD.md

# Run governance checks
python scripts/pre_implementation_check.py --check-risk
python scripts/score_system.py --json --check-min 6.0

# View all 24-category certification docs
ls docs/certification/

# Historical comparison (v0.0.0 → v2.56.0.0)
cat docs/certification/HISTORICAL_COMPARISON.md
```

## Current Score Summary (Fresh Audit: 2026-07-20)

| Category | Score | Status |
|----------|-------|--------|
| Architecture | 9.8 | ✅ PASS |
| Repository Hygiene | 10.0 | ✅ PASS |
| Risk Certification | 9.8 | ✅ PASS |
| Execution Certification | 9.8 | ✅ PASS |
| Security Certification | 9.7 | ✅ PASS |
| Event Store & Audit | 9.7 | ✅ PASS |
| Observability & SRE | 9.7 | ✅ PASS |
| Disaster Recovery | 9.5 | ✅ PASS |
| Testing Certification | 9.5 | ✅ PASS |
| Documentation Certification | 9.8 | ✅ PASS |
| Market Coverage | 8.5 | ⚠️ CONDITIONAL |
| Data Quality & Lineage | 9.8 | ✅ PASS |
| Strategy Governance | 9.8 | ✅ PASS |
| Domain Invariants | 10.0 | ✅ PASS |
| Exchange Calendar | 10.0 | ✅ PASS |
| Market Simulator | 10.0 | ✅ PASS |
| Chaos & Black Swan | 9.5 | ✅ PASS |
| Release Governance | 9.5 | ✅ PASS |
| Capacity Planning | 9.0 | ✅ PASS |
| Broker Abstraction | 9.8 | ✅ PASS |
| ML Governance | 9.5 | ✅ PASS |
| Compliance & Constitution | 10.0 | ✅ PASS |
| Configuration Management | 9.8 | ✅ PASS |
| Production Readiness | 9.7 | ✅ PASS |
| **OVERALL** | **9.81/10.0** | **✅ APPROVED** |
