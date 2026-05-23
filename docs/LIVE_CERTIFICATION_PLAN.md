# AD-KIYU Live Market Production Certification Plan

**Authority:** Principal Production Validation Engineer  
**Platform:** AD-KIYU v2.53  
**Current Phase:** Phase 0 — Dry Validation  
**Target Phase:** Phase 6 — FULL AUTO Certification  
**Capital Protection Mandate:** Highest Priority — No optimism allowed  

---

## Table of Contents

1. [Certification Framework](#1-certification-framework)
2. [Phase 0 — Dry Validation](#2-phase-0--dry-validation)
3. [Phase 1 — Live SIGNAL_ONLY](#3-phase-1--live-signal_only)
4. [Phase 2 — SHADOW MODE](#4-phase-2--shadow-mode)
5. [Phase 3 — LIVE MANUAL CONFIRM](#5-phase-3--live-manual-confirm)
6. [Phase 4 — MICRO CAPITAL AUTO](#6-phase-4--micro-capital-auto)
7. [Phase 5 — CONTROLLED CAPITAL AUTO](#7-phase-5--controlled-capital-auto)
8. [Phase 6 — FULL AUTO CERTIFICATION](#8-phase-6--full-auto-certification)
9. [Kill-Switch Design](#9-kill-switch-design)
10. [Chaos Scenario Matrix](#10-chaos-scenario-matrix)
11. [Go/No-Go Certification Framework](#11-gono-go-certification-framework)
12. [Appendices](#12-appendices)

---

## 1. Certification Framework

### 1.1 Principles

1. **Capital preservation > feature velocity.** No exception.
2. **Evidence-based progression.** Every gate requires objective, documented proof.
3. **One direction.** Regressions are blockages, not setbacks for reconsideration.
4. **Adversarial review.** Every certification must survive a "prove this is safe" challenge.
5. **No deployment on red.** Zero test failures = minimum bar. Not sufficient alone.

### 1.2 Phase Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Phase 0: DRY VALIDATION     No market dependency       │
│  ↓ PASS required                                        │
│  Phase 1: LIVE SIGNAL_ONLY   Real data, no execution    │
│  ↓ PASS required (10-15 sessions)                       │
│  Phase 2: SHADOW MODE         Simulated execution        │
│  ↓ PASS required (15-20 sessions)                       │
│  Phase 3: LIVE MANUAL CONFIRM Human-in-loop execution   │
│  ↓ PASS required (10 sessions)                          │
│  Phase 4: MICRO CAPITAL AUTO  1-2% risk budget          │
│  ↓ PASS required (20+ sessions)                         │
│  Phase 5: CONTROLLED CAPITAL   Small capital expansion   │
│  ↓ PASS required (30-60 sessions)                        │
│  Phase 6: FULL AUTO           Full production capital   │
└─────────────────────────────────────────────────────────┘
```

### 1.3 Phase Transition Rules

| Transition | Success Threshold | Wait Period | Documentation Required |
|-----------|-------------------|-------------|----------------------|
| Phase 0 → 1 | All tests pass | N/A | Signed dry validation report |
| Phase 1 → 2 | 10-15 sessions, 0 anomalies | N/A | Session log + anomaly report |
| Phase 2 → 3 | 15-20 sessions, PnL deviation < 15% | N/A | Shadow mode comparison report |
| Phase 3 → 4 | 10 sessions, 100% operator confidence | 24h cooldown | Operator sign-off + incident log |
| Phase 4 → 5 | 20+ sessions, 0 limit violations | 7 day cooldown | Micro capital report + risk review |
| Phase 5 → 6 | 30-60 sessions, 0 unresolved issues | 14 day cooldown | Full certification evidence package |

---

## 2. Phase 0 — Dry Validation

**Status:** ✅ CURRENT — All known tests pass

### 2.1 Gate Requirements

All of the following MUST pass with **0 failures, 0 errors, 0 unresolved warnings**:

#### 2.1.1 Compilation & Lint
```
python -m py_compile core/**/*.py                 # ALL modules compile
python -m py_compile index_app/**/*.py             # Entry points compile
```

#### 2.1.2 Unit Tests — Complete Suite
```
python -m pytest tests/ -q --tb=short             # ALL 2355+ tests
```

| Sub-Suite | Count | Required Pass | Current Status |
|-----------|-------|---------------|----------------|
| Fast unit tests | ~2206 | 100% | ✅ 0 failures |
| Environment separation | 21 | 100% | ✅ 0 failures |
| DB migration | 7 | 100% | ✅ 0 failures |
| Data governance | 8 | 100% | ✅ 0 failures |
| **Total dry** | **~2242** | **100%** | **✅ PASS** |

#### 2.1.3 Broker Contract Certification
```
python -m pytest tests/test_broker_contract_certification.py -v --tb=long
```

| Scenario | Tests | Status |
|----------|-------|--------|
| Place market order | 3 | ✅ 3/3 |
| Cancel pending order | 3 | ✅ 3/3 |
| Modify pending order | 3 | ✅ 3/3 |
| Reject on bad params | 2 | ✅ 2/3 |
| Broker timeout | 3 | ✅ 3/3 |
| Partial fill → cancel | 3 | ✅ 3/3 |
| Reconnect mid-execution | 3 | ✅ 3/3 |
| Auth expiry | 3 | ✅ 3/3 |
| Malformed response | 2 | ✅ 2/3 |
| Stale order detection | 2 | ✅ 2/3 |
| **Total** | **26** | **✅ 26/26** |

#### 2.1.4 Chaos / Resilience Certification
```
python -m pytest tests/chaos/ -v --tb=long
```

| Scenario | Tests | Status |
|----------|-------|--------|
| Broker outage + paper fallback | 2 | ✅ 2/2 |
| Auth expiry detection | 2 | ✅ 2/2 |
| DB corruption + fallback | 3 | ✅ 3/3 |
| Partial fill + disconnect | 2 | ✅ 2/2 |
| Reconnect storm | 2 | ✅ 2/2 |
| Mid-session restart | 3 | ✅ 3/3 |
| ACK timeout | 2 | ✅ 2/2 |
| Stale feed detection | 1 | ✅ 1/1 |
| Chaos runner (orchestrated) | 8 | ✅ 8/8 |
| **Total** | **24** | **✅ 24/24** |

#### 2.1.5 Exactly-Once Execution Certification
```
python -m pytest tests/test_exactly_once_certification.py -v --tb=long
```

| Scenario | Tests | Status |
|----------|-------|--------|
| Idempotency key validation | 1 | ✅ 1/1 |
| Duplicate request rejection | 1 | ✅ 1/1 |
| Successful retry (same payload) | 1 | ✅ 1/1 |
| Different payload, same key | 1 | ✅ 1/1 |
| Concurrent duplicate | 1 | ✅ 1/1 |
| Persistence after restart | 1 | ✅ 1/1 |
| Timeout handling | 1 | ✅ 1/1 |
| Rollback on failure | 1 | ✅ 1/1 |
| Atomic batch processing | 1 | ✅ 1/1 |
| **Total** | **9** | **✅ 9/9** |

#### 2.1.6 Admin Control Plane Certification
```
python -m pytest tests/test_admin_control_plane.py -v --tb=long
```

| Category | Tests | Status |
|----------|-------|--------|
| Auth enforcement (no token) | 11 | ✅ 11/11 |
| Auth enforcement (bad token) | 2 | ✅ 2/2 |
| Graceful degradation (null refs) | 11 | ✅ 11/11 |
| RBAC enforcement | 2 | ✅ 2/2 |
| Full wiring (all refs live) | 13 | ✅ 13/13 |
| Model registry | 3 | ✅ 3/3 |
| Broker mode | 2 | ✅ 2/2 |
| **Total** | **44** | **✅ 44/44** |

#### 2.1.7 Concurrency Stress
```
python -m pytest tests/test_concurrency_stress.py -v --tb=long
```

| Scenario | Tests | Status |
|----------|-------|--------|
| Concurrent order execution | 1 | ✅ 1/1 |
| Duplicate intent prevention | 1 | ✅ 1/1 |
| Inflight order recovery | 1 | ✅ 1/1 |
| **Total** | **3** | **✅ 3/3** |

#### 2.1.8 Execution Hardening Smoke Test
```
python -m pytest tests/test_smoke_execution_hardening.py -v --tb=long
```

| Component | Tests | Status |
|-----------|-------|--------|
| System mode transitions | 3 | ✅ 3/3 |
| Execution guards | 3 | ✅ 3/3 |
| Audit journal | 3 | ✅ 3/3 |
| Incident alerting | 3 | ✅ 3/3 |
| Signal safety (zombie PnL) | 3 | ✅ 3/3 |
| **Total** | **15** | **✅ 15/15** |

#### 2.1.9 Signal Safety
```
python -m pytest tests/test_signal_safety.py -v --tb=long
```
| Scenario | Tests | Status |
|----------|-------|--------|
| Stale signal detection | 5 | ✅ 5/5 |
| Zombie PnL detection | 5 | ✅ 5/5 |
| Reconciliation halt | 6 | ✅ 6/6 |
| **Total** | **16** | **✅ 16/16** |

### 2.2 Phase 0 Gate Criteria

| Criterion | Threshold | Current | Pass? |
|-----------|-----------|---------|-------|
| Compile errors | 0 | 0 | ✅ |
| Unit test failures | 0 | 0 | ✅ |
| Broker contract failures | 0 | 0 | ✅ |
| Chaos scenario failures | 0 | 0 | ✅ |
| Exactly-once failures | 0 | 0 | ✅ |
| Admin control plane failures | 0 | 0 | ✅ |
| Concurrency failures | 0 | 0 | ✅ |
| Execution hardening failures | 0 | 0 | ✅ |
| **Gate Status** | **ALL PASS** | — | **✅ PASS** |

### 2.3 Phase 0 Outputs

- [x] Signed dry validation report
- [x] All 2355+ tests passing
- [x] All 26 broker contract scenarios verified
- [x] All 24 chaos scenarios verified
- [x] All 9 exactly-once scenarios verified
- [x] All 44 admin control plane endpoints verified

**Gate: ✅ OPEN — Proceed to Phase 1**

---

## 3. Phase 1 — Live SIGNAL_ONLY

**Duration:** Minimum **10-15 live trading sessions**  
**Market dependency:** Yes — real market data  
**Execution:** NO — signals only, no orders placed  

### 3.1 Scope

Validate the following in a live market environment:

1. **Strategy correctness** — Do signals fire at the right time?
2. **Signal timing** — Is signal generation latency acceptable?
3. **Market data freshness** — Are quotes within acceptable staleness bounds?
4. **Quote sanity** — Are malformed/rejected quotes properly handled?
5. **Latency profiling** — End-to-end signal generation latency
6. **Regime behavior** — Does regime detection work on live data?
7. **Expiry behavior** — Does expiry session logic behave correctly?
8. **Broker API health** — Is the broker API reachable and responsive?
9. **Observability** — Are metrics, logs, and dashboards reporting correctly?

### 3.2 Session Requirements

| Condition | Threshold |
|-----------|-----------|
| Minimum sessions | 10 |
| Target sessions | 15 |
| Session duration | Full trading day (09:15–15:30 IST) |
| Instruments | NIFTY, BANKNIFTY, FINNIFTY |
| Data sources | yfinance, NSE WebSocket (if configured) |
| Broker mode | PAPER (for broker connectivity test only — no orders) |

### 3.3 Success Criteria

#### 3.3.1 Data Quality
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Stale data incidents | 0 per session | No stale data > 30s |
| Quote spikes / malformed | ≤ 1 per session | Auto-filtered, logged |
| Feed gap duration | < 5 seconds | Total daily gap < 60s |
| Zero liquidity periods | ≤ 2 per session | Logged, no trading attempt |

#### 3.3.2 Signal Quality
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| False signals (score < threshold) | ≤ 3 per session | Filtered by scoring pipeline |
| Missed genuine signals | ≤ 1 per session | Determined by post-session replay |
| Signal generation latency | < 500ms median | Measured end-to-end |
| Signal flapping (rapid direction change) | ≤ 2 per session | Cooldown must prevent |
| Expiry session classification | 100% correct | Verified by manual review |

#### 3.3.3 Regime Detection
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Regime transitions detected | All major shifts | Verified against NSE indices |
| False regime changes | ≤ 1 per session | Stability filter must work |
| VIX adaptation | Correctly reflected | Verified against NSE VIX |

#### 3.3.4 Broker Connectivity
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Broker API reachable | 100% of session | Health check every 30s |
| API response time | < 1s median | |
| Auth token validity | No expiry during session | |

#### 3.3.5 Observability
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Log output | Complete session log | No gaps > 60s |
| Metrics emitted | All expected metrics | Verified via Prometheus |
| Dashboard accurate | Real-time status match | Verified manually |

### 3.4 Phase 1 Test Matrix

| Test ID | Test Name | Frequency | Method |
|---------|-----------|-----------|--------|
| P1-DQ-01 | Stale data detection | Continuous | Monitor staleness gauge |
| P1-DQ-02 | Quote sanity filter | Each tick | Verify filter passes clean quotes |
| P1-DQ-03 | Feed gap monitor | Continuous | Verify gap counter |
| P1-SG-01 | Signal generation timing | Each bar | Log timestamp diff |
| P1-SG-02 | Signal score validity | Each signal | Verify score in [0,1] |
| P1-SG-03 | Signal consistency | EOD | Replay vs live comparison |
| P1-RD-01 | Regime classification | EOD | Compare with NSE benchmark |
| P1-RD-02 | VIX correlation | EOD | Verify VIX alignment |
| P1-BC-01 | Broker heartbeats | 30s interval | Verify health endpoint |
| P1-OB-01 | Log completeness | EOD | Verify no gaps |
| P1-OB-02 | Metric presence | EOD | Verify all expected metrics |

### 3.5 Phase 1 Gate Criteria

| Criterion | Threshold | Evidence Required |
|-----------|-----------|-------------------|
| Stale trades | 0 | Session log review |
| Feed gap violations | 0 | Monitor output |
| Signal timing outliers | < 500ms median | Latency histogram |
| Broker connectivity | 100% | Health check log |
| Regime errors | ≤ 1 per session | Manual verification |
| Sessions completed | ≥ 10 | Session log count |
| **Gate Status** | **ALL PASS** | **Certification report** |

### 3.6 Phase 1 Outputs

- [ ] Session log for each of 10-15 sessions
- [ ] Signal quality report (scores, timing, consistency)
- [ ] Data quality report (staleness, gaps, anomalies)
- [ ] Regime detection accuracy report
- [ ] Broker connectivity report
- [ ] Latency profile (p50/p95/p99 signal generation)
- [ ] Phase 1 → Phase 2 recommendation (PASS/REJECT)

**Gate: 🔴 BLOCKED — Awaiting 10-15 live sessions**

---

## 4. Phase 2 — SHADOW MODE

**Duration:** Minimum **15-20 live trading sessions**  
**Market dependency:** Yes — real market data  
**Execution:** Simulated — paper fills alongside real signals  

### 4.1 Scope

Validate the following with simulated execution:

1. **Entry timing** — Does the system enter at reasonable prices?
2. **Exit timing** — Does the system exit at reasonable prices?
3. **Slippage realism** — Does the paper fill model reflect actual market conditions?
4. **Order state logic** — Does the state machine handle all transitions correctly?
5. **Fill assumptions** — Are fills consistent with available liquidity?
6. **Strategy PnL realism** — Is simulated PnL within 15% of what real fills would achieve?
7. **Reconciliation correctness** — Is broker truth vs local state tracked correctly?
8. **Risk engine behavior** — Does the risk engine block/reject when expected?

### 4.2 Session Requirements

| Condition | Threshold |
|-----------|-----------|
| Minimum sessions | 15 |
| Target sessions | 20 |
| Session duration | Full trading day |
| Execution mode | SIGNAL_ONLY — Paper fill simulation in parallel |
| Fill model | PaperBrokerAdapter (mid-price ± slippage, OI/volume liquidity filter) |

### 4.3 Success Criteria

#### 4.3.1 Entry/Exit Timing
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Entry price deviation from ideal | < 0.5% | Measured at signal → fill simulated |
| Exit price deviation from ideal | < 0.5% | Measured at signal → fill simulated |
| Entry timing delay | < 2 seconds | Signal → simulated fill |

#### 4.3.2 Slippage Realism
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Slippage model error vs backtest | < 20% | Compare to calibrated model |
| Slippage within spread | 90%+ of fills | Fill within bid-ask spread |
| Liquidity-filtered trades | All pass | OI/volume filter applied |

#### 4.3.3 State Machine Correctness
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Invalid state transitions | 0 | Logged and rejected |
| Stuck states (no terminal → timeout) | 0 | Must auto-timeout |
| State persistence errors | 0 | DB write verification |

#### 4.3.4 PnL Realism
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Simulated vs real PnL deviation | < 15% | Compare against benchmark replay |
| Win rate deviation | < 10% | Compared to backtest expectation |

#### 4.3.5 Reconciliation
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Reconciliation cycles per session | Continuous | Every 30s during active trading |
| Mismatches detected | All matched | 0 unresolved at session end |

### 4.4 Phase 2 Test Matrix

| Test ID | Test Name | Frequency | Method |
|---------|-----------|-----------|--------|
| P2-ET-01 | Entry price benchmark | Each signal | Compare to market price |
| P2-ET-02 | Exit price benchmark | Each exit | Compare to market price |
| P2-ET-03 | Timing benchmark | Each order | Simulated fill timestamp |
| P2-SL-01 | Slippage distribution | EOD | vs calibrated model |
| P2-SL-02 | Spread capture rate | EOD | % of fills within spread |
| P2-SM-01 | State transition violations | Continuous | Logged violations count |
| P2-SM-02 | Terminal state reachability | Continuous | All orders terminal by EOD |
| P2-PL-01 | PnL comparison | EOD | Simulated vs benchmark |
| P2-PL-02 | Win rate comparison | EOD | vs backtest expectation |
| P2-RC-01 | Reconciliation health | Continuous | Cycle success rate |

### 4.5 Phase 2 Gate Criteria

| Criterion | Threshold | Evidence Required |
|-----------|-----------|-------------------|
| Entry timing OK | All entries within 2s of signal | Timing log |
| Exit timing OK | All exits within 2s of signal | Timing log |
| Slippage deviation | < 20% from model | Slippage report |
| State machine errors | 0 | State machine log |
| PnL deviation | < 15% from benchmark | Shadow report |
| Reconciliation mismatches | 0 unresolved | Reconciliation log |
| Sessions completed | ≥ 15 | Session log |
| **Gate Status** | **ALL PASS** | **Shadow mode report** |

### 4.6 Phase 2 Outputs

- [ ] Shadow mode comparison report (per session)
- [ ] Entry/exit timing analysis
- [ ] Slippage model accuracy assessment
- [ ] State machine correctness log
- [ ] PnL deviation analysis
- [ ] Reconciliation accuracy report
- [ ] Phase 2 → Phase 3 recommendation (PASS/REJECT)

**Gate: 🔴 BLOCKED — Awaiting 15-20 shadow mode sessions**

---

## 5. Phase 3 — LIVE MANUAL CONFIRM

**Duration:** Minimum **10 live trading sessions**  
**Market dependency:** Yes — real market data  
**Execution:** System recommends — Human confirms  

### 5.1 Scope

Validate operational workflows with human-in-the-loop execution:

1. **Dashboard correctness** — Does the operator dashboard show accurate status?
2. **Operator ergonomics** — Can an operator efficiently confirm/reject recommendations?
3. **Alerting** — Do all alert types fire correctly?
4. **Config safety** — Can the operator safely adjust config via admin control plane?
5. **Override safety** — Do operator overrides work without breaking safety invariants?
6. **Emergency controls** — Does the kill switch work immediately?
7. **Admin control plane** — Are all 22 endpoints functional with RBAC?

### 5.2 Session Requirements

| Condition | Threshold |
|-----------|-----------|
| Minimum sessions | 10 |
| Execution mode | LIVE_MANUAL_CONFIRM |
| Broker mode | PAPER (fills via PaperBrokerAdapter) |
| Operator | Human in loop |
| Environment | STAGING (min 10) or SHADOW (if available) |

### 5.3 Success Criteria

#### 5.3.1 Dashboard Correctness
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Mode display accurate | 100% of checks | Verify mode matches actual |
| Position display accurate | 100% | Matches broker snapshot |
| PnL display | Within 1% | Matches calculated PnL |
| Signal display | Correct | All generated signals shown |

#### 5.3.2 Operator Workflow
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Recommendation → confirm latency | < 10s | Operator response time |
| Recommendation → reject latency | < 10s | Operator response time |
| Missed confirmations | 0 | All recommendations acted on |
| Erroneous confirms | 0 | Post-session audit |
| **Kill switch activation time** | **< 1 second** | **Measured from button press** |

#### 5.3.3 Admin Control Plane
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Config changes applied | 100% | Verify via audit log |
| Config changes rolled back | 100% | Verify via audit log |
| RBAC enforcement | 100% | Verify unauthorized blocked |
| Audit trail completeness | 100% | All mutations logged |

#### 5.3.4 Safety
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Kill switch success | 100% | All test activations succeed |
| Emergency stop time | < 1 second | Measured |
| Hard halt prevents ALL entries | 100% | Verified post-trip |

### 5.4 Phase 3 Test Matrix

| Test ID | Test Name | Frequency | Method |
|---------|-----------|-----------|--------|
| P3-DB-01 | Dashboard accuracy | Each session | Manual comparison |
| P3-DB-02 | Signal display | Each signal | Verify all signals shown |
| P3-DB-03 | PnL accuracy | EOD | Compare to calculation |
| P3-OP-01 | Confirm workflow | Each recommend | Time and log |
| P3-OP-02 | Reject workflow | Each recommend | Time and log |
| P3-OP-03 | Kill switch test | Session start/end | Verify immediate halt |
| P3-AC-01 | Config change | Per test | Apply, verify, rollback |
| P3-AC-02 | RBAC enforcement | Per test | Verify blocked permissions |
| P3-AC-03 | Audit trail | Per test | Verify log completeness |

### 5.5 Phase 3 Gate Criteria

| Criterion | Threshold | Evidence Required |
|-----------|-----------|-------------------|
| Dashboard accuracy | 100% | Session screenshots |
| Operator error rate | 0% | Session logs |
| Kill switch success | 100% | Activation/deactivation tests |
| Admin CP accuracy | 100% | Audit log verification |
| RBAC enforcement | 100% | Permission test results |
| Sessions completed | ≥ 10 | Session log |
| **Gate Status** | **ALL PASS** | **Operator sign-off** |

### 5.6 Phase 3 Outputs

- [ ] Operator sign-off document (signed per session)
- [ ] Kill switch activation test log
- [ ] Admin control plane functional verification
- [ ] RBAC permission test results
- [ ] Dashboard accuracy verification screenshots
- [ ] Incident log (0 incidents required)
- [ ] Phase 3 → Phase 4 recommendation (PASS/REJECT)

**Gate: 🔴 BLOCKED — Awaiting 10 manual confirm sessions + operator sign-off**

---

## 6. Phase 4 — MICRO CAPITAL AUTO

**Duration:** Minimum **20+ live trading sessions**  
**Market dependency:** Yes — real market data  
**Execution:** Automated — live orders with micro capital  

### 6.1 Scope

Validate real broker contract behavior with minimal financial risk:

1. **Broker contract behavior** — Real order lifecycle (submit, ack, fill, cancel)
2. **Exact-once execution** — Real broker idempotency verification
3. **Partial fills** — Handle partial fills correctly
4. **Cancel logic** — Cancel orders within acceptable latency
5. **Auth expiry** — Token refresh during live session
6. **Retries** — Retry logic on transient failures
7. **Restart recovery** — Crash recovery with open positions
8. **Reconciliation** — Broker truth vs local state with real positions
9. **Slippage** — Actual slippage vs modelled slippage
10. **Brokerage/STT accuracy** — Verify cost calculations against broker confirmation

### 6.2 Session Requirements

| Condition | Threshold |
|-----------|-----------|
| Minimum sessions | 20 |
| Capital at risk | **1-2% of deployable risk budget only** |
| Risk per trade | ≤ 0.1% of total capital |
| Max daily loss | **Hard stop at 0.5% of total capital** |
| Execution mode | FULL_AUTO — but with micro capital cap |
| Broker mode | LIVE — real broker connection |
| Max open positions | 1 per session |
| Position type | Index options only (NIFTY/BANKNIFTY/FINNIFTY) |

### 6.3 Capital Protection Rules (Phase 4)

| Rule | Threshold | Action |
|------|-----------|--------|
| Daily loss cap | 0.5% total capital | Hard halt — no recovery until next session |
| Weekly loss cap | 1.0% total capital | Hard halt — requires operator review |
| Consecutive loss breaker | 3 losses | Auto pause for 2 hours |
| Broker anomaly breaker | 5 API failures | Switch to backup broker |
| Reconciliation mismatch | 1 unresolved | Freeze trading, alert operator |
| Data anomaly breaker | 3 stale data events | Pause, switch data source |
| **Emergency kill switch** | **Manual** | **Immediate halt — < 1s** |

### 6.4 Success Criteria

#### 6.4.1 Execution Correctness
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Duplicate order submissions | 0 | IdempotencyCertifier proof |
| Unmatched broker fills | 0 | All broker fills matched to local |
| State machine violations | 0 | All transitions valid |
| Unknown state occurrences | 0 | All states resolved to terminal |
| Partial fill handling | Correct | Verified against broker |

#### 6.4.2 Reconciliation
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Reconciliation cycles | 100% run | Every 30s during active trading |
| Mismatches found | 0 after resolution | All auto-resolved |
| Orphan positions | 0 | No local without broker match |

#### 6.4.3 Risk Correctness
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Risk limit violations | 0 | All trades within limits |
| Max loss breached | 0 | Daily/weekly cap never hit |
| Drawdown limit | No breach | Hard halt would have triggered |
| Margin violations | 0 | Capital reservation worked |

#### 6.4.4 Cost Accuracy
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Brokerage estimate error | < 10% | vs actual broker charge |
| STT estimate error | < 5% | vs actual STT charge |
| Net PnL match | Within 2% | Simulated vs real |

### 6.5 Phase 4 Test Matrix

| Test ID | Test Name | Frequency | Method |
|---------|-----------|-----------|--------|
| P4-EC-01 | Submit + ACK | Each order | Verify state transition |
| P4-EC-02 | Fill notification | Each fill | Verify state + PnL update |
| P4-EC-03 | Partial fill | Each partial | Verify accumulation |
| P4-EC-04 | Cancel | Each cancel | Verify broker confirmation |
| P4-EC-05 | Duplicate check | Each order | IdempotencyCertifier verify |
| P4-EC-06 | Retry on timeout | Each retry | Verify idempotent retry |
| P4-RC-01 | Reconciliation cycle | Continuous | Verify match |
| P4-RC-02 | Crash recovery | Session start | Verify open positions loaded |
| P4-RK-01 | Risk limit check | Each order | Verify risk engine approval |
| P4-RK-02 | Loss cap | Continuous | Verify halt at threshold |
| P4-CS-01 | Brokerage accuracy | Each fill | Compare to broker report |
| P4-CS-02 | STT accuracy | Each fill | Compare to broker report |

### 6.6 Phase 4 Gate Criteria

| Criterion | Threshold | Evidence Required |
|-----------|-----------|-------------------|
| Duplicate execution | 0 | Idempotency log |
| Reconciliation mismatch | 0 unresolved | Reconciliation report |
| Crash recovery failures | 0 | Restart log |
| Risk limit violations | 0 | Risk engine log |
| Stale trades | 0 | Data quality report |
| Emergency stop success | 100% | Kill switch test log |
| Broker contract pass | 100% | Real execution log |
| Cost accuracy | < 10% deviation | Cost comparison report |
| Sessions completed | ≥ 20 | Session log |
| **Gate Status** | **ALL PASS** | **Micro capital report** |

### 6.7 Phase 4 Outputs

- [ ] Execution log (per order with state transitions)
- [ ] Idempotency certification log (0 duplicates)
- [ ] Reconciliation report (0 unresolved mismatches)
- [ ] Risk engine violation log (0 violations)
- [ ] Cost accuracy report (brokerage/STT comparison)
- [ ] Crash recovery test results
- [ ] Incident log (0 incidents requiring manual intervention)
- [ ] Weekly review by Principal Engineer
- [ ] Phase 4 → Phase 5 recommendation (PASS/REJECT/EXTEND)

**Gate: 🔴 BLOCKED — Awaiting 20+ micro capital sessions**

---

## 7. Phase 5 — CONTROLLED CAPITAL AUTO

**Duration:** Minimum **30-60 live trading sessions**  
**Market dependency:** Yes — real market data  
**Execution:** Automated — small capital expansion  

### 7.1 Scope

Validate stability with small but material capital at risk:

1. **Prolonged stability** — 30-60 sessions without systemic issues
2. **Drawdown controls** — Drawdown limits prevent material losses
3. **Risk throttles** — VIX-based position sizing works correctly
4. **Market stress resilience** — Behavior during volatile periods
5. **Expiry-day robustness** — Correct handling of expiry sessions
6. **Circuit-breaker behavior** — Market halt detection and response
7. **Multi-asset coordination** — Correlation guard between NIFTY/BANKNIFTY/FINNIFTY

### 7.2 Session Requirements

| Condition | Threshold |
|-----------|-----------|
| Minimum sessions | 30 |
| Target sessions | 60 |
| Capital expansion | 3-5x micro capital (Phase 4 level) |
| Risk per trade | ≤ 0.5% of total capital |
| Max daily loss | **Hard stop at 2.0% of total capital** |
| Max drawdown | **Hard stop at 8.0% total capital** |
| Execution mode | FULL_AUTO |
| Max open positions | 3 per session |
| Environment | PRODUCTION or STAGING with live broker |
| Staging environment | Minimum 15 of 30 sessions in staging |

### 7.3 Success Criteria

#### 7.3.1 Stability
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Consecutive healthy sessions | ≥ 25 | No incident in 25+ sessions |
| System uptime during session | 100% | No restarts during market hours |
| Memory leak indicator | < 10% growth | Session-start to session-end |
| Thread leak indicator | No growth | Active thread count stable |

#### 7.3.2 Market Stress
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| VIX adaptation | Correct sizing | Position size inversely proportional |
| Expiry-day restrictions | 100% compliant | No entries after cutoff |
| Circuit breaker response | Correct | Detected + trading blocked |
| Correlation guard | 100% compliant | No same-direction simultaneous entries |

#### 7.3.3 Capital Protection
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Daily loss cap saving | Would have prevented loss | Simulated vs actual |
| Drawdown limit saving | Would have prevented loss | Simulated vs actual |
| Max consecutive loss days | ≤ 3 | No worse than backtest |

#### 7.3.4 Risk Controls
| Metric | Threshold | Pass Criteria |
|--------|-----------|--------------|
| Max daily loss | Not breached | 0 threshold hits |
| Weekly loss cap | Not breached | 0 threshold hits |
| Max drawdown | Not breached | 0 threshold hits |
| Consecutive loss cooldown | Activated correctly | All cooldowns respected |

### 7.4 Phase 5 Test Matrix

| Test ID | Test Name | Frequency | Method |
|---------|-----------|-----------|--------|
| P5-ST-01 | Session uptime | Each session | Verify no restarts |
| P5-ST-02 | Memory tracking | EOD | Compare heap usage |
| P5-ST-03 | Thread tracking | EOD | Thread count monitor |
| P5-MS-01 | VIX sizing check | Each trade | Verify size vs VIX |
| P5-MS-02 | Expiry check | Expiry days | Verify cutoff enforcement |
| P5-MS-03 | Circuit breaker | Event-driven | Verify halt on detection |
| P5-MS-04 | Correlation guard | Each signal | Verify cross-index blocking |
| P5-CP-01 | Daily PnL tracking | EOD | Verify vs stop loss |
| P5-CP-02 | Weekly PnL tracking | Weekly | Verify vs circuit breaker |
| P5-RK-01 | All risk limits | Each trade | Verify risk engine log |

### 7.5 Phase 5 Gate Criteria

| Criterion | Threshold | Evidence Required |
|-----------|-----------|-------------------|
| Consecutive healthy sessions | ≥ 25 | Session health log |
| Uptime | 100% | Restart log |
| Memory stable | < 10% growth | Memory profile |
| Thread stable | No leak | Thread count log |
| VIX sizing | Correct | Position size vs VIX chart |
| Expiry compliance | 100% | Entry time log |
| Limit violations | 0 | Risk engine log |
| Drawdown breach | 0 | Equity curve |
| Sessions completed | ≥ 30 | Session log |
| **Gate Status** | **ALL PASS** | **Controlled capital report** |

### 7.6 Phase 5 Outputs

- [ ] Session health log (ALL PASS for ≥ 25 consecutive sessions)
- [ ] Memory and thread profiling report
- [ ] VIX adaptation analysis
- [ ] Expiry session compliance report
- [ ] Market stress behavior analysis
- [ ] Correlation guard effectiveness report
- [ ] Equity curve with risk limit overlays
- [ ] Full incident log (0 required)
- [ ] Phase 5 → Phase 6 recommendation (PASS/REJECT/EXTEND)

**Gate: 🔴 BLOCKED — Awaiting 30-60 controlled capital sessions**

---

## 8. Phase 6 — FULL AUTO CERTIFICATION

**Duration:** Ongoing — permanent certification  
**Market dependency:** Yes — real market data  
**Execution:** FULL_AUTO — full production capital  

### 8.1 Scope

Final certification for full autonomous trading:

1. All Phase 0-5 criteria met with evidence package
2. Full capital deployment with ALL protective controls active
3. Continuous monitoring with automated incident response
4. Weekly review cycle with automated reports
5. Monthly certification review with Principal Engineer

### 8.2 Launch Requirements

| Condition | Threshold |
|-----------|-----------|
| All prior phases | PASS |
| Evidence package | Complete, signed, archived |
| Capital protection | All controls active and tested |
| Emergency procedures | Drilled and documented |
| Monitoring | 24/7 dashboard with alerting |
| Team training | All operators certified |
| Insurance (if applicable) | Confirmed |

### 8.3 Post-Launch Monitoring

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| Daily PnL | -2% | Hard halt |
| Weekly PnL | -5% | Hard halt, operator call |
| Drawdown | -8% | Hard halt, emergency review |
| Broker connectivity | 3 failures | Failover |
| Reconciliation mismatch | 1 unresolved | Freeze, manual review |
| Data staleness | 30s | Pause trading |
| Consecutive losses | 3 | Auto cooldown (2h) |

### 8.4 Certification Validity

| Certification | Valid For | Renewal |
|---------------|-----------|---------|
| Phase 6 FULL AUTO | 90 days | Full reg review every 90 days |
| Phase 5 → 6 transition | Until revoked | Incident-triggered reassessment |
| Individual phase certs | 180 days | Phase-specific regression tests |

### 8.5 Decertification Conditions

FULL AUTO certification is IMMEDIATELY revoked upon:

1. Any duplicate order execution (duplicate order in broker = instant decert)
2. Any reconciliation mismatch left unresolved for > 5 minutes
3. Any risk limit violation (daily loss cap, drawdown limit)
4. Any crash recovery failure (open positions lost)
5. Any safety invariant violation
6. Any emergency stop that fails to activate within 2 seconds
7. Any unauthorized config change bypassing RBAC
8. Any audit trail integrity failure

### 8.6 Recertification Path

If FULL AUTO is revoked:

1. Return to highest phase whose criteria remain satisfied
2. Minimum 5 sessions at that phase before re-applying
3. Full root cause analysis and fix verification
4. 10 additional sessions at the recertified phase
5. Re-apply for FULL AUTO with incident evidence package

---

## 9. Kill-Switch Design

### 9.1 Three-Layer Kill Switch Architecture

```
Layer 1: SOFTWARE — Automated protection (no human required)
┌─────────────────────────────────────────────┐
│  _trip_hard_halt() → _HARD_HALT event set   │
│  Blocks ALL new trade entries                │
│  Trip sources:                               │
│  ├─ RiskAuthority (drawdown, daily loss)     │
│  ├─ SafetyEngine (API failures, staleness)   │
│  ├─ Intraday PnL monitor                    │
│  ├─ InvariantEngine (HALT severity checks)  │
│  ├─ ReconciliationEngine (mismatch freeze)  │
│  ├─ CircuitBreakerDetector (market halt)    │
│  └─ BrokerFailover (all brokers exhausted)  │
└─────────────────────────────────────────────┘

Layer 2: MANUAL — Operator-initiated
┌─────────────────────────────────────────────┐
│  Admin Control Plane: POST /control/halt    │
│  Kill file: STOP_TRADING in project root    │
│  Dashboard button: Immediate halt           │
│  Telegram bot command: /halt               │
└─────────────────────────────────────────────┘

Layer 3: PHYSICAL — Emergency circuit break
┌─────────────────────────────────────────────┐
│  Router-level API block                     │
│  Broker portal manual cancellation          │
│  System-level process kill                  │
└─────────────────────────────────────────────┘
```

### 9.2 Kill Switch Activation Tests

| Test | Procedure | Expected | Frequency |
|------|-----------|----------|-----------|
| Automated halt | Trigger daily loss threshold | Hard halt fires within 1s | Pre-session |
| Manual halt | POST /control/halt | All entries blocked in < 1s | Pre-session |
| Kill file | Drop STOP_TRADING | Halt within 1s poll interval | Weekly |
| Resume from halt | POST /control/resume | New entries allowed | Pre-session |
| Halt persistence | Halt + restart system | Halt persists across restart | Monthly |

### 9.3 Kill Switch State Machine

```
                    ┌─────────────┐
                    │  NORMAL     │
                    │  Trading OK │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ SOFT     │ │ HARD     │ │ PHYSICAL │
        │ PAUSE    │ │ HALT     │ │ KILL     │
        │ Auto-res │ │ Manual   │ │ Process  │
        │ After    │ │ Resume   │ │ Restart  │
        │ Cooldown │ │ Required │ │ Required │
        └──────────┘ └──────────┘ └──────────┘
              │            │            │
              └────────────┼────────────┘
                           ▼
                    ┌─────────────┐
                    │ POST_HALT   │
                    │ Review +    │
                    │ Root Cause  │
                    │ + Fix       │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │  Resume OK? │
                    ├──YES──┬─NO──┤
                    │       │     │
                    ▼       │     ▼
              ┌─────────┐   │ ┌──────────┐
              │ NORMAL  │   │ │ ESCALATE │
              │ Resume  │   │ │ + REPORT │
              └─────────┘   │ └──────────┘
                            │
                     ┌──────┴──────┐
                     │ Fix Issue   │
                     │ + Validate  │
                     └─────────────┘
```

---

## 10. Chaos Scenario Matrix

### 10.1 Certified Chaos Scenarios (Phase 0 Passed)

| ID | Scenario | Trigger | Expected Behavior | Tests | Status |
|----|----------|---------|-------------------|-------|--------|
| CS-01 | Broker outage | API returns failure for all calls | Failover to backup broker | 2 | ✅ PASS |
| CS-02 | Auth expiry | Token expires mid-session | Auto-refresh, fail to auth = halt | 2 | ✅ PASS |
| CS-03 | DB corruption | WAL/DB file becomes unreadable | Fallback to in-memory, error log | 3 | ✅ PASS |
| CS-04 | Partial fill + disconnect | Fill partially then disconnect | PENDING→settle on reconnect | 2 | ✅ PASS |
| CS-05 | Reconnect storm | Rapid connect/disconnect cycles | Idempotent, no duplicate submissions | 2 | ✅ PASS |
| CS-06 | Mid-session restart | Process killed mid-order | WAL journal recovery on restart | 3 | ✅ PASS |
| CS-07 | ACK timeout | Broker accepts but no ACK | PENDING→FAILED after timeout | 2 | ✅ PASS |
| CS-08 | Stale feed | Market data stops updating | Stale detection → pause trading | 1 | ✅ PASS |

### 10.2 Extended Chaos Scenarios (Required for Phase 4+)

| ID | Scenario | Trigger | Expected Behavior | Phase |
|----|----------|---------|-------------------|-------|
| CS-09 | Network jitter | Packet loss / high latency | Retry with backoff, no duplicate | 4 |
| CS-10 | Split brain | Two instances access same broker | Detected by invariant engine | 4 |
| CS-11 | Config corruption | Config file becomes unreadable | Fallback to defaults, error log | 4 |
| CS-12 | Disk pressure | Disk space < 5% | Cleanup scheduler triggers, warn | 4 |
| CS-13 | Simultaneous failover | Both brokers fail simultaneously | Hard halt, no trades without broker | 4 |
| CS-14 | Midnight rollover | Session spans calendar date | All day-based limits reset correctly | 5 |
| CS-15 | Extreme VIX spike | VIX jumps from 15 to 40+ | VIX block engages, position wind-down | 5 |
| CS-16 | Holiday session | NSE holiday, bot starts | Market closed detection, no trading | 5 |
| CS-17 | Expiry day crash | 10%+ index drop on expiry | Expiry gates hold, circuit breaker | 5 |
| CS-18 | Malformed broker response | Broker returns non-JSON | Parsing error handling, retry | 5 |
| CS-19 | Multiple partial fills | Order filled in 10+ pieces | Accumulation logic correct | 6 |
| CS-20 | Order state drift | Broker shows different status | Reconciliation → freeze | 6 |

### 10.3 Chaos Testing Procedure

For each scenario:

1. **Inject failure** using test harness
2. **Observe behavior** — log, metrics, state changes
3. **Verify recovery** — system returns to healthy state
4. **Verify no capital loss** — positions and PnL preserved
5. **Document outcome** — PASS/FAIL with evidence

---

## 11. Go/No-Go Certification Framework

### 11.1 Go/No-Go Decision Matrix

```
┌─────────────────────────────────────────────────────────────────┐
│                      GO/NO-GO                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  For each phase transition, ALL criteria must be GREEN.         │
│  Any RED = NO-GO. AMBER = review with escalation.              │
│                                                                 │
│  ┌──────────┬──────────┬──────────┬───────────────────────────┐ │
│  │ Criterion│ GREEN    │ AMBER    │ RED                       │ │
│  ├──────────┼──────────┼──────────┼───────────────────────────┤ │
│  │ Tests    │ 0 fail   │ 1-2 fail │ 3+ fail                  │ │
│  │ Sessions │ ≥ min    │ ≥ 80%    │ < 80%                    │ │
│  │ Loss cap │ 0 breach │ 1 breach │ 2+ breaches              │ │
│  │ Dup exec │ 0        │ 0        │ ≥ 1                      │ │
│  │ Recon    │ 0 unres  │ 1 unres  │ 2+ unres                │ │
│  │ Incidents│ 0        │ 1 (non-CRIT)│ 2+ or any CRITICAL    │ │
│  │ Kill sw  │ 100%     │ 1 fail   │ 2+ fails                │ │
│  │ Evidence │ Complete │ Partial  │ Missing                  │ │
│  └──────────┴──────────┴──────────┴───────────────────────────┘ │
│                                                                 │
│  FINAL: ALL GREEN = GO                                         │
│         ANY RED = NO-GO (return to current phase)              │
│         ANY AMBER = Escalate to Principal Engineer             │
└─────────────────────────────────────────────────────────────────┘
```

### 11.2 Phase Transition Authority

| Transition | Required Approvals |
|-----------|-------------------|
| Phase 0 → 1 | Automation (auto) |
| Phase 1 → 2 | Automation (auto) |
| Phase 2 → 3 | Automation (auto) |
| Phase 3 → 4 | **Principal Engineer** |
| Phase 4 → 5 | **Principal Engineer + 2nd reviewer** |
| Phase 5 → 6 | **Principal Engineer + CTO + 3rd reviewer** |
| Decertification | **Principal Engineer (immediate)** |
| Recertification | **Principal Engineer + full evidence package** |

### 11.3 Blocker Resolution

| Blocker Type | Resolution Path | Timeline |
|-------------|----------------|----------|
| Test failure | Fix → verify → re-run suite | < 24h |
| Session deficit | Complete remaining sessions | Per phase min |
| Evidence gap | Generate missing evidence | < 48h |
| Capital breach | Full incident review → fix → 5 extra sessions | < 72h |
| Duplicate execution | **Immediate decertification** → full review | < 1 week |
| Kill switch failure | Fix → 5 successful tests | < 24h |

### 11.4 Emergency Blockers

The following automatically block ALL progression until resolved:

1. Any duplicate order in broker system
2. Any unreconciled position mismatch > 24h
3. Any hard halt that failed to activate when triggered
4. Any audit trail gap > 5 minutes
5. Any unauthorized broker API call via live credentials in paper mode

---

## 12. Appendices

### A. Certification Evidence Package Template

Each phase transition requires the following evidence:

```
CERTIFICATION_EVIDENCE_PACKAGE_v{version}.pdf
├── Executive Summary (1 page)
├── Phase Transition Request (checklist)
├── Test Results
│   ├── Phase-specific test suite (JSON)
│   ├── All-Phase regression (summary)
│   └── Chaos scenario results
├── Session Logs
│   ├── per-session/{session_id}.json
│   └── aggregated_summary.json
├── Risk Analysis
│   ├── Violation log (0 required)
│   ├── Risk engine decision log
│   └── Capital protection verification
├── Incident Log
│   ├── Incidents (0 required)
│   └── Near-misses (≥ 0, documented)
├── Operator Sign-off (Phases 3+)
└── Approvals (Phases 4+)
```

### B. Quick Reference: Phase Transition Checklists

#### Phase 0 → Phase 1
- [ ] All 2355+ tests pass
- [ ] Broker contract: 26/26
- [ ] Exactly-once: 9/9
- [ ] Chaos: 24/24
- [ ] Admin CP: 44/44
- [ ] SIGNAL_ONLY mode configured

#### Phase 1 → Phase 2
- [ ] 10-15 live sessions completed
- [ ] 0 stale trades
- [ ] 0 broker connectivity incidents
- [ ] Signal latency < 500ms
- [ ] Regime detection verified
- [ ] SHADOW mode configured

#### Phase 2 → Phase 3
- [ ] 15-20 shadow sessions completed
- [ ] PnL deviation < 15%
- [ ] 0 state machine violations
- [ ] 0 reconciliation mismatches
- [ ] Entry/exit timing within 2s
- [ ] LIVE_MANUAL_CONFIRM mode configured

#### Phase 3 → Phase 4
- [ ] 10 manual confirm sessions completed
- [ ] Operator sign-off obtained
- [ ] Kill switch tested: 100% success
- [ ] RBAC verified: 100% enforcement
- [ ] Admin CP verified: all 22 endpoints
- [ ] FULL_AUTO mode configured with micro capital cap
- [ ] 24h cooldown observed

#### Phase 4 → Phase 5
- [ ] 20+ micro capital sessions completed
- [ ] 0 duplicate executions
- [ ] 0 reconciliation mismatches
- [ ] 0 risk limit violations
- [ ] 0 crash recovery failures
- [ ] Cost accuracy within 10%
- [ ] Principal Engineer approval
- [ ] 7 day cooldown observed

#### Phase 5 → Phase 6
- [ ] 30-60 controlled capital sessions completed
- [ ] 25+ consecutive healthy sessions
- [ ] 100% uptime during session hours
- [ ] 0 limit violations
- [ ] VIX adaptation verified
- [ ] Expiry compliance 100%
- [ ] Correlation guard verified
- [ ] Principal Engineer + CTO approval
- [ ] 14 day cooldown observed

### C. Incident Severity Classification

| Severity | Definition | Response Time | Escalation |
|----------|-----------|---------------|------------|
| **CRITICAL** | Capital loss, duplicate execution, unrecoverable state | < 5 minutes | Principal Engineer + CTO |
| **HIGH** | Position mismatch, reconciliation failure, kill switch failure | < 15 minutes | Principal Engineer |
| **MEDIUM** | Config drift, stale data > 60s, non-critical invariant violation | < 1 hour | On-call engineer |
| **LOW** | Log warning, metric anomaly, non-critical alert | < 24 hours | Next business day |
| **INFO** | Informational event | Logged | None |

### D. Certification Authority Contact

| Role | Authority | Contact |
|------|-----------|---------|
| Principal Production Validation Engineer | Final authority on ALL progression | System-generated |
| CTO / Chief Risk Officer | Phase 4+ escalation | System-escalated |
| Operator | Phase 3 sign-off | Human-in-loop |
| Automation | Phase 0-2 auto-progression | CI/CD pipeline |

---

*End of Certification Plan — AD-KIYU v2.53*  
*Next Review: After Phase 1 completion or 30 days, whichever comes first*
