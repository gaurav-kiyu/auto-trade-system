# Risk Migration Plan v1.0
## AD-KIYU: Monolithic → Modular Risk Architecture

**Document ID:** RMP-001
**Version:** 1.0
**Last Updated:** 2026-05-21
**Authority:** Principal Production Validation Engineer

---

## 1. Executive Summary

The current AD-KIYU codebase has approximately **10 risk-related classes/engines** spread across the codebase with fragmented responsibilities. This plan outlines a controlled, phased migration to a **single authoritative `RiskAuthority`** while preserving all safety guarantees and maintaining zero capital risk at each step.

### Current State (Risk Architecture)
```
Risk Engines: ~10 scattered across the codebase
├── core/risk_engine.py          — Primary risk config + engine
├── core/risk/risk_policy_engine.py — Policy-based risk
├── core/services/risk_service.py   — Canonical risk evaluation
├── core/mandate_enforcer.py       — Trade mandate enforcement
├── core/predictive_risk.py        — Dead (0 importers)
├── core/trading_risk.py           — Dead (0 importers)
├── core/reentry_evaluator.py      — Re-entry risk gating
├── core/liquidity_guard.py        — Pre-entry liquidity filter
├── core/kelly_sizer.py            — Kelly position sizing
├── core/var_calculator.py         — VaR analytics
├── core/stress_tester.py          — Stress test scenarios
└── Scattered inline risk checks in index_trader.py
```

### Target State (Risk Architecture)
```
Risk Authority (Single Entry Point)
└── RiskService (canonical evaluation)
    ├── RiskConfig (configuration)
    ├── RiskVerdict (decision + reasoning)
    ├── RiskPolicyEngine (plugin)
    ├── InvariantEngine (runtime checks)
    └── Specialized modules (called by, not calling, RiskAuthority)
        ├── reentry_evaluator.py → consulted before approval
        ├── liquidity_guard.py   → consulted before approval
        ├── kelly_sizer.py       → invoked after approval
        ├── var_calculator.py    → reporting/analytics
        └── stress_tester.py     → reporting/analytics
```

---

## 2. Migration Principles

### 2.1 Core Rules

1. **Zero capital at risk** — Never migrate risk logic while live positions exist
2. **Single source of truth** — Only one risk engine makes approve/reject decisions at any time
3. **Dual-run validation** — New and old engines run in parallel during migration
4. **Rollback first** — Every phase must have a tested rollback procedure before proceeding
5. **Gate progression** — Each phase has explicit entry/exit criteria; no skipping

### 2.2 Safety Invariants (Never Violated)

| Invariant | Description | Enforcement |
|-----------|-------------|-------------|
| I-001 | Only one RiskAuthority makes approve/reject decisions | Startup assertion |
| I-002 | All broker calls precede with WAL intent journal entry | Runtime check |
| I-003 | Every order has a matching risk verdict | Post-execution audit |
| I-004 | Hard halt cannot be bypassed by any risk engine | Code review + test |
| I-005 | MAX_DAILY_LOSS and MAX_DRAWDOWN always honored | InvariantEngine heartbeat |

---

## 3. Migration Phases

### Phase 0: Audit & Instrumentation (Weeks 1-2)
**Risk Level:** Minimal — No code changes to runtime risk logic

#### Activities

1. **Complete risk engine inventory**
   - Audit every file that touches risk decisions
   - Document all risk entry points in `index_trader.py`
   - Identify dead code for removal

2. **Instrument existing risk engines**
   - Add logging to every risk approve/reject decision
   - Record: `{timestamp, caller, decision, params, result}`
   - Output: structured JSONL audit trail

3. **Create decision test harness**
   - Capture 1000+ risk decisions from paper trading
   - Store as test fixtures for regression validation

4. **Establish baseline metrics**
   - Win rate, Sharpe ratio, max drawdown
   - Risk decision latency (p50/p95/p99)
   - False positive/negative rates

#### Entry Criteria
- [ ] Complete inventory of all risk-related code
- [ ] Instrumentation deployed on paper trading instance
- [ ] Baseline hazard metrics established

#### Exit Criteria
- [ ] 7+ days of instrumented risk decisions logged
- [ ] No unexpected behavior from instrumentation
- [ ] Test fixtures validated against paper trading output

#### Rollback
- Remove instrumentation logging
- No functional change to risk logic — trivial rollback

---

### Phase 1: Dead Code Removal (Week 3)
**Risk Level:** Low — Removing confirmed-dead code

#### Activities

1. **Remove confirmed-dead risk engines**
   - `core/predictive_risk.py` — 0 importers confirmed
   - `core/trading_risk.py` — 0 importers confirmed
   - Remove from `core/__init__.py` exports

2. **Verify removal**
   - Run full test suite (2397 tests)
   - Scan for any residual imports with `rg "predictive_risk|trading_risk"`

#### Entry Criteria
- [ ] Phase 0 exit criteria met
- [ ] Dead code confirmed zero importers via ripgrep

#### Exit Criteria
- [ ] Both modules deleted
- [ ] All tests passing
- [ ] No residual references

#### Rollback
- `git checkout` the deleted files
- Verify tests pass

---

### Phase 2: RiskService Canonicalization (Weeks 4-5)
**Risk Level:** Medium — Wrapping existing risk logic under a single facade

#### Activities

1. **Create RiskAuthority facade**
   - Single class in `core/risk/authoritative_engine.py`
   - Wraps existing `RiskService` as the canonical evaluator
   - Provides: `approve_trade(capital, pnl, vix, positions) -> RiskVerdict`

2. **Create adapter wrappers for existing specialized modules**
   - `ReentryEvaluatorAdapter` — wraps `core/reentry_evaluator.py`
   - `LiquidityGuardAdapter` — wraps `core/liquidity_guard.py`
   - `KellySizerAdapter` — wraps `core/kelly_sizer.py`
   - These adapters are *consulted by* RiskAuthority, not bypassing it

3. **Dual-run mode**
   - Deploy RiskAuthority alongside existing risk paths
   - Both evaluate every trade decision independently
   - Log both results; flag discrepancies for review
   - Existing risk path makes the actual decision

4. **Build discrepancy analysis**
   - Compare RiskAuthority decision vs existing path
   - Track: agreement rate, severity of disagreement, direction

#### Entry Criteria
- [ ] RiskAuthority implemented and tested in isolation
- [ ] Adapter wrappers implemented
- [ ] Dual-run logger connected to audit trail

#### Exit Criteria
- [ ] 5+ trading days of dual-run data collected
- [ ] >99.9% agreement rate between old path and RiskAuthority
- [ ] All 100% agreed decisions match expected outcomes
- [ ] All discrepancies analyzed and resolved (either fix RiskAuthority or fix old path)

#### Rollback
- Disable RiskAuthority facade
- Restore original risk decision path
- All existing risk modules unchanged — safe rollback

---

### Phase 3: RiskAuthority Cutover (Weeks 6-7)
**Risk Level:** High — RiskAuthority becomes the sole decision maker

#### Activities

1. **Switch RiskAuthority to active mode**
   - RiskAuthority's decision becomes binding
   - Old risk path becomes read-only observer
   - All trade entry/exit gated through `RiskAuthority.approve_trade()`

2. **Update index_trader.py entry points**
   - Replace `_MANDATE_ENFORCER.can_trade()` → `_risk_authority.approve_trade()`
   - Replace inline risk checks with RiskAuthority calls
   - Remove duplicate risk evaluations

3. **Add InvariantEngine runtime checks**
   - `SingleRiskEngineOnly` — only RiskAuthority imported
   - `RiskApprovalRequired` — every order has matching risk verdict
   - `ModePreventsExecution` — current mode allows trade

4. **Update startup validation**
   - `validate_risk_engine()` asserts only RiskAuthority loaded
   - Fail-fast at startup if multiple risk engines detected

#### Entry Criteria
- [ ] Phase 2 dual-run >99.9% agreement for 5+ trading days
- [ ] All discrepancies resolved
- [ ] InvariantEngine implemented and tested

#### Exit Criteria
- [ ] RiskAuthority is the sole decision maker
- [ ] All tests passing (2397)
- [ ] InvariantEngine checks GREEN for 3+ sessions
- [ ] Zero capital loss during paper trading under RiskAuthority

#### Rollback (Critical Path)
1. Set `USE_RISK_AUTHORITY = False` in config
2. Restore original risk decision path
3. Restore `index_trader.py` entry points from git tag
4. Run full test suite
5. Verify no positions open before resuming

---

### Phase 4: Risk Module Consolidation (Weeks 8-9)
**Risk Level:** Medium — Physical code reorganization, no behavioral change

#### Activities

1. **Mark old engines deprecated**
   - `core/risk_engine.py` — Mark as deprecated, keep only `RiskConfig` / `RiskDecision` data classes
   - Add deprecation warning on import

2. **Fold mandate_enforcer logic into RiskService**
   - Migrate remaining logic from `core/mandate_enforcer.py`
   - Verify all callers updated to use RiskService directly

3. **Reorganize risk directory**
   ```
   core/risk/
   ├── __init__.py
   ├── authoritative_engine.py   → RiskAuthority (single entry point)
   ├── risk_policy_engine.py     → Plugin under RiskAuthority
   ├── adapters/
   │   ├── reentry.py            → Wraps reentry_evaluator
   │   ├── liquidity.py          → Wraps liquidity_guard
   │   └── kelly.py              → Wraps kelly_sizer
   ├── models.py                 → RiskConfig, RiskDecision, RiskVerdict
   └── invariants/
       ├── engine.py             → InvariantEngine
       └── checks.py             → Standard invariant checks
   ```

4. **Update all imports across codebase**
   - `from core.risk import RiskAuthority` (new)
   - `from core.risk_engine import RiskEngine` → deprecated import (warning)

#### Entry Criteria
- [ ] Phase 3 exit criteria met
- [ ] All callers of old risk engines identified via code search

#### Exit Criteria
- [ ] All old risk engines either deleted or marked deprecated
- [ ] All imports updated to use `core.risk` package
- [ ] Full test suite passing
- [ ] No regression in risk behavior

#### Rollback
- Revert import changes via `git revert`
- Verify tests pass
- RiskAuthority continues to function as decider

---

### Phase 5: Policy Engine Cleanup (Week 10)
**Risk Level:** Low — Final cleanup of deprecation warnings

#### Activities

1. **Remove deprecated risk modules**
   - `core/risk_engine.py` (keep RiskConfig/RiskDecision if used elsewhere)
   - Any other risk files fully migrated

2. **Run final audit**
   - Verify no risk engine imports outside `core/risk/`
   - Verify InvariantEngine `SingleRiskEngineOnly` check passes

3. **Update documentation**
   - `CLAUDE.md` — update risk module references
   - `DEPENDENCY_MAP.md` — update risk dependencies

#### Entry Criteria
- [ ] Phase 4 exit criteria met
- [ ] All deprecation warnings active for 2+ weeks

#### Exit Criteria
- [ ] Clean import tree — only `core.risk` risk modules
- [ ] InvariantEngine checks pass
- [ ] All tests passing

#### Rollback
- Restore deleted modules from git history
- Verify tests pass

---

### Phase 6: Validation & Freeze (Week 11+)
**Risk Level:** Minimal — Monitoring and tuning

#### Activities

1. **Extended paper trading under RiskAuthority**
   - 20+ trading sessions
   - Compare performance against baseline (Phase 0)

2. **Parameter tuning**
   - Adjust RiskConfig parameters based on accumulated data
   - Run sensitivity analysis on key risk parameters

3. **Documentation freeze**
   - Finalize risk architecture documentation
   - Update runbooks for new risk system

#### Entry Criteria
- [ ] Phase 5 exit criteria met

#### Exit Criteria
- [ ] 20+ paper trading sessions with zero incidents
- [ ] Risk performance metrics at or above baseline
- [ ] All documentation updated

---

## 4. Verification & Testing Strategy

### 4.1 Automated Checks Per Phase

| Check | Phase 0 | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 | Phase 6 |
|-------|---------|---------|---------|---------|---------|---------|---------|
| Full test suite | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Risk-specific tests | - | - | ✓ | ✓ | ✓ | ✓ | ✓ |
| InvariantEngine | - | - | - | ✓ | ✓ | ✓ | ✓ |
| Dual-run comparison | - | - | ✓ | - | - | - | - |
| Import scanner | - | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Vulnerability scan | - | - | - | - | - | ✓ | ✓ |

### 4.2 Risk Regression Test Suite

All risk migration phases must pass these regression tests:

```python
# tests/risk/test_risk_migration.py (conceptual)
def test_risk_authority_approves_valid_trade(): ...
def test_risk_authority_rejects_over_limit(): ...
def test_risk_authority_rejects_drawdown_breach(): ...
def test_risk_authority_respects_hard_halt(): ...
def test_invariant_single_risk_engine(): ...
def test_risk_verdict_contains_full_reasoning(): ...
def test_risk_authority_consulted_reentry_evaluator(): ...
def test_risk_authority_consulted_liquidity_guard(): ...
def test_dual_run_mode_agreement_above_threshold(): ...
def test_rollback_restores_original_behavior(): ...
```

### 4.3 Manual Verification Steps

1. **Before each phase:**
   - Review git diff for unintended changes
   - Run full test suite
   - Verify no open positions

2. **During dual-run (Phase 2):**
   - Review daily discrepancy report
   - Investigate any disagreement > 0.1%

3. **After cutover (Phase 3+):**
   - Monitor InvariantEngine dashboard for 3 sessions
   - Verify all GREEN before proceeding

---

## 5. Rollback Procedures

### 5.1 Quick Rollback (Any Phase)

If a critical issue is detected during any phase:

```bash
# 1. Stop trading immediately
echo "STOP_TRADING" > STOP_TRADING

# 2. Verify no open positions
python -c "
from core.execution.broker_truth_reconciliation import reconcile_broker_truth
report = reconcile_broker_truth()
print(f'Status: {report[\"status\"]}')
print(f'Message: {report[\"message\"]}')
"

# 3. Restore previous risk configuration
git checkout <previous-stable-tag> -- core/risk/
git checkout <previous-stable-tag> -- core/services/risk_service.py

# 4. Run verification
python -m pytest tests/ -q
python -m core.health_checker

# 5. Resume trading
# Clear STOP_TRADING file first
```

### 5.2 Phase-Specific Rollback

| Phase | Rollback Time | Complexity | Data Loss Risk |
|-------|--------------|------------|----------------|
| 0 | < 5 min | Low | None |
| 1 | < 10 min | Low | None |
| 2 | < 15 min | Medium | Audit trail only |
| 3 | < 30 min | High | None (config toggle) |
| 4 | < 20 min | Medium | None (git revert) |
| 5 | < 15 min | Medium | None (git restore) |
| 6 | < 10 min | Low | None |

### 5.3 Full System Rollback (Catastrophic)

If RiskAuthority causes systemic issues:

1. Restore `index_app/index_trader.py` from v2.42 baseline
2. Restore all risk modules from pre-migration git tag
3. Disable RiskAuthority config flag
4. Run full certification check before resuming

---

## 6. Risk Matrix

### 6.1 Migration Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Undetected dead risk code dependency | Low | Medium | Phase 0 thorough audit + import scanner |
| Dual-run disagreement not investigated | Medium | Medium | Automated discrepancy alerting |
| RiskAuthority miss (false approve) | Low | High | Dual-run comparison + test harness |
| RiskAuthority false reject (missed trade) | Medium | Low | Discrepancy review session each day |
| Config parameter drift during migration | Low | Medium | Config hash validation + git tag per phase |
| Performance regression from facade layer | Low | Low | Latency benchmarks in Phase 0 |
| Incomplete import migration (Phase 4) | Medium | Medium | Import scanner in CI |

### 6.2 Business Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Migration extends beyond planned timeline | Medium | Low | Time-boxed phases with hard cutoffs |
| Developer bandwidth competition | Medium | Low | Dedicated migration sprint |
| Knowledge loss if migration incomplete | Low | Medium | Documentation-first approach |

---

## 7. Success Criteria

### 7.1 Quantitative Metrics

| Metric | Baseline (Phase 0) | Target (Phase 6) | Measurement |
|--------|-------------------|-------------------|-------------|
| Risk engines count | ~10 | 1 (RiskAuthority) | `rg -l "class.*Risk" core/` |
| Risk decision latency (p50) | TBD | Within 10% of baseline | Instrumented logging |
| False positive rate | TBD | Not increased | Decision comparison |
| Missed trade rate | TBD | Not increased | Decision comparison |
| Test count | 2397 | 2397+ | pytest count |

### 7.2 Qualitative Metrics

- Single entry point for all risk decisions
- Clear audit trail for every approve/reject
- InvariantEngine runtime verification
- All risk tests passing
- Zero dead risk code in codebase
- All documentation updated

---

## 8. Timeline

| Phase | Duration | Weeks | Target Completion |
|-------|----------|-------|-------------------|
| Phase 0: Audit & Instrumentation | 2 weeks | 1-2 | Week 2 |
| Phase 1: Dead Code Removal | 1 week | 3 | Week 3 |
| Phase 2: RiskService Canonicalization | 2 weeks | 4-5 | Week 5 |
| Phase 3: RiskAuthority Cutover | 2 weeks | 6-7 | Week 7 |
| Phase 4: Risk Module Consolidation | 2 weeks | 8-9 | Week 9 |
| Phase 5: Policy Engine Cleanup | 1 week | 10 | Week 10 |
| Phase 6: Validation & Freeze | 2 weeks | 11-12 | Week 12 |

**Total estimated duration: 12 weeks**

---

## 9. Appendices

### A. Risk Engine Inventory Template

```json
{
  "module": "core/risk_engine.py",
  "classes": ["RiskEngine", "RiskConfig", "RiskDecision"],
  "importers": ["index_trader.py", "execution_engine.py"],
  "risk_type": "primary",
  "status": "active",
  "migration_target": "fold into RiskService",
  "notes": "RiskConfig + RiskDecision data classes to keep"
}
```

### B. Dual-Run Discrepancy Report Template

```json
{
  "session_date": "2026-05-21",
  "total_decisions": 127,
  "agreements": 127,
  "disagreements": 0,
  "agreement_rate": 1.0,
  "missed_trades": 0,
  "false_positives": 0,
  "risk_authority_approvals": 42,
  "existing_path_approvals": 42,
  "avg_latency_ms_authority": 1.2,
  "avg_latency_ms_existing": 1.1
}
```

### C. Phase Transition Sign-Off Template

```markdown
## Phase [N] Sign-Off

**Date:** YYYY-MM-DD
**Phase:** Phase [N]: [Name]
**Duration:** [X] days (planned [Y] days)

### Entry Criteria Met
- [ ] All entry criteria checked and signed off

### Activities Completed
- [ ] [Activity 1]
- [ ] [Activity 2]
- [ ] [Activity 3]

### Exit Criteria Met
- [ ] [Exit criterion 1]
- [ ] [Exit criterion 2]

### Rollback Tested
- [ ] Rollback procedure tested and verified

### Sign-Off
- [ ] Lead Engineer: __________
- [ ] Principal Engineer: __________
- [ ] Operator (if applicable): __________
```

---

*End of Risk Migration Plan — AD-KIYU v2.53*
*This document must be reviewed and updated before proceeding to each phase.*
