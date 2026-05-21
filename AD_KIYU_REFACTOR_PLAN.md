# AD-KIYU Refactor Plan

## Current State (v2.50.5)
- **478 Python files, 110,183 lines**
- **99 risk-related classes across ~10 engines** (critical)
- **41 strategy/signal-related files** (fragmented)
- **204 test artifact databases** leaked into repo root
- **0 formal invariants**
- **0 RBAC**
- **0 CI/CD production governance**
- **0 operating mode enforcement** (SystemMode exists but is broker-outage focused, not execution-mode focused)
- **Floating dependency versions**
- **Audit journal exists but no pre-execution WAL**
- **Partial idempotency fragmented across 3+ managers**
- **Broker abstraction exists but only Kite is real**
- **No chaos certification**

## 17-Gap Implementation Plan (6 Phases, ordered by risk/criticality)

---

## PHASE 1 — Safety Foundation (WEEKS 1-2)
*Target: Prevent capital loss on first real deployment*

### 1A — Formal Operating Mode Enforcement
**Files to CREATE:**
- `core/operating_mode.py` — Enum + ModeManager with strict transitions
  - Modes: `SIGNAL_ONLY` (default) → `BACKTEST` → `PAPER` → `SHADOW` → `LIVE_MANUAL_CONFIRM` → `FULL_AUTO`
  - `FULL_AUTO` requires explicit config + startup flag `--enable-full-auto`
  - Every `execute_order()` call checks `mode_manager.allows_execution()`
- `core/modes/__init__.py` — package

**Files to MODIFY:**
- `core/system_mode.py` — Add reference to operating_mode for `can_enter_new_trade()`
- `core/services/execution_service.py` — Gate all broker calls through mode check
- `index_app/index_trader.py` — Init mode manager at startup, enforce at entry points

**Gate check pattern:**
```python
if not operating_mode_manager.can_execute():
    raise ModeViolationError(f"Blocked by mode: {operating_mode_manager.current_mode}")
```

### 1B — Unified Risk Engine
**Files to CREATE:**
- `core/risk/authoritative_engine.py` — Single `RiskAuthority` class
  - Wraps: `RiskService` (canonical risk evaluation)
  - Deprecated list: `mandate_enforcer` → delegate to RiskService
  - Provides: `approve_trade(capital, pnl, vix, positions) -> RiskVerdict`
  - Startup validation: verifies no other risk engine imported

**Files to DELETE:**
- `core/predictive_risk.py` — Dead (0 importers in code)
- `core/trading_risk.py` — Dead (0 importers)
- `core/risk_engine.py` — Mark as deprecated, keep only `RiskConfig` / `RiskDecision` data classes, remove `RiskEngine`
- `core/mandate_enforcer.py` — Already partially fixed in v2.50.5, fold remaining logic into RiskService

**Files to MODIFY:**
- `core/risk/risk_policy_engine.py` — Wire as plugin under RiskAuthority
- `core/services/risk_service.py` — Expose `approve_trade()` as canonical single entry point
- `index_app/index_trader.py` — Replace `_MANDATE_ENFORCER.can_trade()` -> `_risk_authority.approve_trade()`
- `core/__init__.py` — Remove old risk engine exports
- `core/startup_validation.py` — `validate_risk_engine()` asserts only RiskAuthority loaded

### 1C — Strategy Orchestration Consolidation
**Files to CREATE:**
- `core/strategy/orchestrator.py` — Single `StrategyOrchestrator`
  - Routes signal → risk → execution through one pipeline
  - Prevents duplicate signal paths

**Files to DELETE or MERGE:**
- `core/signal_router.py` — Merge into orchestrator
- `core/signal_approval_workflow.py` — Merge into orchestrator
- `core/strategy_engine.py` → Delegate to orchestrator
- `core/strategy_engine_v2.py` → Delegate to orchestrator

### 1D — Formal Invariants Engine
**Files to CREATE:**
- `core/invariants/engine.py` — `InvariantEngine`
  - Runtime-assertable invariants checked on heartbeat loop (every 5s)
  - On violation: AUDIT_WARN → HARD_HALT escalation path

- `core/invariants/checks.py` — Standard invariants:
  1. `BrokerPositionsMatchLocal` — reconciler reports zero mismatch
  2. `SingleRiskEngineOnly` — only RiskAuthority imported
  3. `SingleStrategyOrchestratorOnly` — only StrategyOrchestrator active
  4. `NoDuplicateSubmissions` — idempotency cache consistent
  5. `NoStaleDataTrading` — LTP timestamp ≤ 5s old
  6. `RiskApprovalRequired` — every order has matching risk decision
  7. `ModePreventsExecution` — current mode allows trade
  8. `NoRetryAfterUnknown` — deterministic state machine never retries UNKNOWN

### 1E — Artifact Cleanup
- `git rm` all `test_recon_*.db` (97 files, ~1.9 MB)
- `git rm` runtime `.db` files from root (trades.db, execution_state.db, etc.)
- `git rm` `.pytest_cache/`
- Add `data/`, `logs/`, `backups/`, `*.db` to `.gitignore` with comment
- Script `scripts/clean_artifacts.py` — removes all runtime artifacts before release

---

## PHASE 2 — Execution Hardening (WEEKS 3-4)

### 2A — Write-Ahead Intent Journal
**Files to CREATE:**
- `core/wal/journal.py` — `WriteAheadJournal`
  - Before ANY broker call: append intent record with `{intent_id, action, params, risk_verdict, config_snapshot_hash, correlation_id, timestamp}`
  - On crash recovery: replay uncommitted intents
  - Storage: SQLite with WAL mode (atomic append)
  - No broker side-effect without prior WAL entry

**Integration points:**
```python
# Before broker.submit_order(...):
wal.append(Intent(action="SUBMIT_ORDER", params=order, risk_verdict=verdict))
# After broker confirms:
wal.commit(intent_id)  # marks as COMMITTED
# On UNKNOWN:
wal.get_intent(intent_id)  # returns the full intent for replay
```

### 2B — Exactly-Once Execution Certification
**Files to CREATE:**
- `core/execution/idempotency/certifier.py` — `IdempotencyCertifier`
  - Generates deterministic `execution_id = hash(order_params + timestamp_slot)`
  - Tracks three states: `PENDING→COMMITTED→SETTLED`
  - Crash recovery: queries broker open orders, matches by execution_id tag

**Files to MODIFY:**
- `core/execution/idempotency/manager.py` — Add `verify_no_duplicate()` method
- `core/services/execution_service.py` — Insert `execution_id` into `order_tag` field
- `core/adapters/broker_adapters.py` — Pass `execution_id` as broker order tag

### 2C — Broker Contract Certification Suite
**Files to CREATE:**
- `tests/contract/broker/test_place.py`
- `tests/contract/broker/test_reject.py`
- `tests/contract/broker/test_cancel.py`
- `tests/contract/broker/test_partial_fill.py`
- `tests/contract/broker/test_timeout.py`
- `tests/contract/broker/test_auth_expiry.py`
- `tests/contract/broker/test_reconnect.py`
- `tests/contract/broker/test_malformed.py`
- `tests/contract/broker/test_stale_status.py`
- `tests/contract/broker/__init__.py`

**Implementation:**
- `BrokerContractTestBase` — abstract base with `place_order()`, `cancel_order()`, etc.
- Each broker adapter must pass the full suite before certification
- `scripts/run_broker_contract_tests.py` — CLI runner

---

## PHASE 3 — Production Controls (WEEKS 5-6)

### 3A — Multi-Broker Production Switching
**Files to CREATE:**
- `infrastructure/adapters/brokers/iifl/adapter.py` — IIFL adapter
- `infrastructure/adapters/brokers/mstock/adapter.py` — mStock adapter
- `infrastructure/adapters/brokers/groww/adapter.py` — Groww adapter
- `infrastructure/adapters/brokers/angel/adapter.py` — Angel adapter
- `infrastructure/adapters/brokers/dhan/adapter.py` — Dhan adapter
- `infrastructure/adapters/brokers/ibkr/adapter.py` — IBKR adapter

**Files to MODIFY:**
- `core/adapters/broker_adapters.py` — Remove hardcoded Kite import; use config-driven `broker_name` to load adapter via importlib
- `core/broker_failover.py` — Wire to switch adapter on failure
- `config.json` — `"active_broker": "kite"` with adapter config per broker

### 3B — Safe Admin Control Plane
**Files to CREATE:**
- `core/control_plane/server.py` — FastAPI server on dedicated port (default 7080)
  - Auth: `AdminAuth` with JWT tokens + RBAC
  - Endpoints:
    - `POST /control/strategy/{name}/{action}` — enable/disable per strategy
    - `POST /control/asset_class/{class}/{action}` — enable/disable per asset class
    - `POST /control/kill` — emergency kill
    - `POST /control/capital/{amount}` — set capital allocation
    - `POST /control/risk_limit/{name}/{value}` — hot-set risk limits
    - `POST /control/ai_model/{name}/{action}` — select/rollback AI model
    - `POST /control/feature_flag/{name}/{value}` — toggle feature flags
    - `GET /control/state` — full system state
    - `GET /control/audit` — control action history
  - All mutations: `validate() + audit_log() + version() + reversible()`

- `core/control_plane/rbac.py` — `Role` enum: `ADMIN`, `OPERATOR`, `OBSERVER`, `DEVELOPER`
- `core/control_plane/__init__.py`

### 3C — RBAC + Operator Governance
**Files to CREATE:**
- `core/auth/role_manager.py` — `RoleManager`
- `core/auth/permissions.py` — Permission matrix
- `core/auth/__init__.py`
- `core/auth/session_store.py` — Session tracking with TTL

**Permission Matrix:**
| Action | ADMIN | OPERATOR | OBSERVER | DEVELOPER |
|--------|-------|----------|----------|-----------|
| View state | ✓ | ✓ | ✓ | ✓ |
| Halt trading | ✓ | ✓ | | |
| Modify risk limits | ✓ | | | |
| Toggle strategies | ✓ | ✓ | | ✓ |
| Deploy models | ✓ | | | ✓ |
| Modify code | ✓ | | | ✓ |
| View logs | ✓ | ✓ | ✓ | ✓ |
| Add brokers | ✓ | | | |
| Modify config | ✓ | | | ✓ |

---

## PHASE 4 — AI & Portfolio Governance (WEEKS 7-8)

### 4A — AI Governance Completion
**Required pipeline:**
```
Historical Data → Feature Engineering → Training →
Backtest → Walk-Forward → Paper Mode → Shadow Mode →
Approval → Canary Rollout → Production
```

**Files to CREATE:**
- `core/ai/governance.py` — `AIGovernanceBoard`
  - Model registry (SQLite)
  - Versioning (semver per model)
  - Rollback capability
  - Drift response automation
  - Performance tracking
  - Explainability (SHAP reports)
- `core/ai/model_registry.py` — `ModelRegistry`
- `core/ai/canary_manager.py` — `CanaryManager`
- `core/ai/rollback_controller.py` — `RollbackController`
- `core/ai/__init__.py`

**Governance rules:**
```
- AI must NOT self-mutate live execution logic directly
- Every model requires approved A/B test in paper mode first
- Canary deployments: 10% → 50% → 100% over 5 trading days
- Drift detection auto-triggers rollback within 15 minutes
```

### 4B — Portfolio Engine Completion
**Files to CREATE:**
- `core/portfolio/authoritative.py` — `PortfolioAuthority`
  - Exposure aggregation across broker accounts
  - Capital allocation per strategy
  - Margin-aware position sizing
  - Correlation controls
  - Strategy budgets

**Files to MODIFY:**
- `core/domains/portfolio/service.py` — Wire as data source
- `core/domains/portfolio/model.py` — Add exposure, margin models

---

## PHASE 5 — Production Readiness (WEEKS 9-10)

### 5A — Observability Hardening
**Files to CREATE:**
- `core/telemetry/metrics.py` — SRE-grade metrics
  - Execution: submit/ACK/fill latencies, retry count, reject %
  - Market: freshness, feed gaps, stale incidents
  - Risk: throttle activations, violations, current exposure
  - AI: drift alerts, model degradation scores
  - Ops: reconciliation lag, broker uptime, incident frequency
- `core/telemetry/exporters.py` — Prometheus + JSON log exporters
- `core/telemetry/__init__.py`

### 5B — CI/CD Production Governance
**GitHub Actions workflow: `prod-release.yml`**
```
Stages:
  1. compile-validation — py_compile all files
  2. lint — ruff check with strict rules
  3. unit-tests — pytest tests/unit
  4. contract-tests — pytest tests/contract/broker
  5. replay-regression — run_backtest.py --compare-to-baseline
  6. chaos-smoke — chaos test suite (5 min)
  7. packaging — python -m build
  8. release-artifact-verification — checksum, size, import test
```

### 5C — Dependency Governance
- Create `requirements-lock.txt` with `pip freeze` exact pins
- `pip-audit` in CI
- Dependabot configuration
- Weekly dependency review automation

---

## PHASE 6 — Resilience Certification (WEEKS 11-12)

### 6A — Chaos / Resilience Certification
**Files to CREATE:**
- `tests/chaos/broker_outage.py` — Simulate broker unreachable
- `tests/chaos/ack_timeout.py` — ACK never arrives
- `tests/chaos/stale_feed.py` — Market data freezes for 60s
- `tests/chaos/reconnect_storm.py` — 10 disconnects in 60s
- `tests/chaos/partial_fill_disconnect.py` — Fill arrives after WS disconnect
- `tests/chaos/db_corruption.py` — SQLite WAL corruption
- `tests/chaos/auth_expiry.py` — Token expires mid-session
- `tests/chaos/restart_mid_session.py` — Process kill -9 + restart
- `tests/chaos/runner.py` — Orchestrated chaos runner
- `tests/chaos/__init__.py`

**Pass criteria:**
- No capital loss in any scenario
- Clean reconciliation after restart
- No duplicate submissions
- Correct position tracking post-recovery

### 6B — Architecture Simplification (Code Ownership Map)
```
ad_kiyu/
  strategy/     StrategyOrchestrator — one orchestrator
  risk/         RiskAuthority — one risk engine
  execution/    ExecutionService — one execution path
  portfolio/    PortfolioAuthority — one portfolio engine
  market/       DataEngine — one data layer
  persistence/  PersistenceService — one persistence layer
  ops/          SystemMode + OperatingMode + ControlPlane
  ai/           AIGovernanceBoard
```

---

## CRITICAL SUCCESS METRICS

| Metric | Current | Target |
|--------|---------|--------|
| Risk engines | ~10 | 1 (RiskAuthority) |
| Signal paths | ~8 | 1 (StrategyOrchestrator) |
| Invariant checks | 2 files | 8+ runtime checks |
| Test artifacts in repo | 204 | 0 |
| Dependency pins | None | All exact |
| CI stages | 4 | 8 |
| Chaos scenarios | 0 | 8 |
| Operating modes | 0 enforced | 6 with gates |
| RBAC | 0 | 4 roles |
| Broker adapters | 3 (1 real) | 8 (6 real) |
| WAL journal | None | Append-before-execute |
| AI governance | None | Full lifecycle |
