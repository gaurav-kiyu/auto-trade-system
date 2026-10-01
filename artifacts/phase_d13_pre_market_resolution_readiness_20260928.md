# OPB v2.60 — PHASE D.13 PRE-MARKET RESOLUTION-PATH READINESS AUDIT

**Document ID**: `OPB-V260-PHASE-D13-PRE-MARKET-RESOLUTION-READINESS-20260928`  
**Audit Timestamp**: `2026-09-28T18:25:00+05:30` (Pre-Market / Post-Market Close Audit)  
**Working Branch**: `v2.60-phase-d-candle-selection-remediation`  
**Starting / Local HEAD Commit**: `e6d1b2c269d43a94f12e671a25864f57c3f2db13`  
**Base Commit**: `abcce53bb16f1d0aa5918fd2c72dd731f8f2e332`  
**Frozen Production Baseline**: `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4` on `origin/master`  
**Governance Authority**: `OPB-FINAL-PHASE-GOVERNANCE-001`  
**Phase E Readiness Decision**: **DO NOT MOVE TO PHASE E / STRICTLY BLOCKED**  
**Final Empirical Verdict**: **`B. BLOCKED — ENGINEERING REMEDIATION REQUIRED`**

---

## 1. Executive Summary

Under governance authority **`OPB-FINAL-PHASE-GOVERNANCE-001`**, a comprehensive, 100% read-only engineering and empirical-readiness audit of the existing Phase-D forward cohort (101 observations) was executed prior to the next live NSE market session.

The primary objective was to empirically verify whether the existing 101 genuine `FORWARD_LIVE_SCAN` observations can correctly progress through the canonical Phase-B outcome measurement and Phase-D forward-resolution pipeline when real market prices move or holding horizons expire during the next market session.

### Key Audit Findings:
1. **Concrete Implementation Blocker Discovered (`BLK-PHASE-D13-UNRESOLVED-MEASUREMENT-BYPASS`)**:
   - In `SignalForwardObservationService.sync_forward_outcomes()` (`core/signals/signal_forward_observation.py` line 417–426), in-flight forward observations are checked against `signal_outcome_measurements`.
   - Because all 101 forward observations were already registered with an initial measurement record where `outcome = 'UNRESOLVED'`, `cur.fetchone()` returns this row.
   - The conditional `if not meas:` evaluates to `False`, completely bypassing `phase_b_service.build_signal_outcome_measurement(sig_id)`.
   - As an empirical result demonstrated in isolated sandbox execution, **when a signal's price hits Target 1, Stop Loss, or Expiry in `system_signals`, the forward observation CANNOT resolve**. The measurement remains trapped at `UNRESOLVED`, and `signal_forward_observations` remains permanently at `OBSERVING` (`is_resolved = 0`).
2. **Safety & Quarantine Invariants**:
   - `SIGNAL_ONLY=True`, `LIVE_TRADING_LOCKOUT=True`, `full_auto_allowed=False`.
   - Zero live broker orders, zero broker API calls, zero EC2 interactions, zero remote git pushes or merges.
3. **Cryptographic Cohort Immutability**:
   - Cohort hashes for 45, 71, 99, and 101 observations match previous checkpoints byte-for-byte (100.0% exact match).
   - Production database SHA-256 before & after the audit: `bb64bad5dc0ca581bfa18942997c5d5e23a65f97c783a0ca2d084418573354c0` (**0 bytes mutated, 100.0% match**).
4. **Test Regression Suite**:
   - **208 passed, 0 failed, 0 skipped** across Suite A (110 tests) and Suite B (98 tests).

---

## 2. Environment / Branch / Commit

- **Working Branch**: `v2.60-phase-d-candle-selection-remediation`
- **Current HEAD Commit**: `e6d1b2c269d43a94f12e671a25864f57c3f2db13`
- **Base Commit**: `abcce53bb16f1d0aa5918fd2c72dd731f8f2e332`
- **Frozen Production Baseline**: `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4` on `origin/master`
- **Host OS**: Windows 11 (Terminal: PowerShell)
- **Local Time**: `2026-09-28T18:25:00+05:30` (Monday post-market)
- **Database Path**: `db/signals_history.db`
- **Working Tree**: Zero staged changes, production database immutable.

---

## 3. Safety Audit

All hard safety rules mandated by `OPB-FINAL-PHASE-GOVERNANCE-001` were verified:

| Safety Control | Configured Value | Governance Requirement | Compliance Status |
| :--- | :---: | :---: | :---: |
| **`EXECUTION_MODE`** | `SIGNAL_ONLY` | `SIGNAL_ONLY` | **PASS** |
| **`SIGNAL_ONLY`** | `True` | `True` | **PASS** |
| **`LIVE_TRADING_LOCKOUT`** | `True` | `True` | **PASS** |
| **`live_trading_lockout_enabled`** | `True` | `True` | **PASS** |
| **`full_auto_allowed`** | `False` | `False` | **PASS** |
| **Live Orders Placed** | `0` | `0` | **PASS** |
| **Broker Execution Calls** | `0` | `0` | **PASS** |
| **EC2 Contacts / Deploys** | `0` | `0` | **PASS** |
| **Remote Git Pushes / Merges** | `0` | `0` | **PASS** |
| **Model Fitting / Probability Training** | `NONE / BLOCKED` | `BLOCKED` | **PASS** |
| **Calibration Status** | `UNCALIBRATED` | `UNCALIBRATED` | **PASS** |

---

## 4. 101-Cohort Census

Every observation among the 101 existing forward observations was audited without mutating the database:

### A. Lifecycle State Counts
- **Total Registered Forward Observations**: **101** (100% `FORWARD_LIVE_SCAN`)
- **Observing (In-Flight)**: **101**
- **Resolved**: **0**
- **Target First**: **0**
- **Stop Loss First**: **0**
- **Timeout**: **0**
- **Ambiguous**: **0**
- **No Data**: **0**
- **Invalidated**: **0**
- **Stale (>48h in OBSERVING)**: **0**

### B. Category Breakdown
- **`EQUITY_SWING_DELIVERY`**: 31 observations (Swing 5-day horizon)
- **`FUTURES`**: 38 observations (Swing 5-day horizon)
- **`STOCK_OPTIONS`**: 31 observations (Intraday horizon; 30 midday, 1 near-close grace)
- **`INDEX_OPTIONS`**: 1 observation (Intraday horizon; midday)

### C. Score Bucket Distribution
| Score Bucket | Registered | Observing | Resolved | Required (G1) | Current Deficit |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **70–74** | 3 | 3 | 0 | 100 | -100 |
| **75–79** | 4 | 4 | 0 | 100 | -100 |
| **80–84** | 14 | 14 | 0 | 100 | -100 |
| **85+** | 80 | 80 | 0 | 100 | -100 |
| **Sub-70 Anomaly** | 0 | 0 | 0 | 0 | 0 |

---

## 5. Resolution-Path Trace

The complete lifecycle path was traced from candle ingestion through readiness monitoring:

```text
Market Candle Ingestion
       ↓
Signal/Outcome Price Evaluation (SignalOutcomeTracker)
       ↓
Phase-B Outcome Measurement (SignalOutcomeDatasetService)
       ↓
MFE / MAE & Realized-R Calculation
       ↓
Canonical Outcome Classification (normalize_outcome_state)
       ↓
Phase-D Forward Observation Resolution (SignalForwardObservationService)
       ↓
Resolved Cohort Count & G1–G3 Readiness Gate Evaluation
```

### Detailed Path Classification & Evidence:

| Outcome Path | Status | Implementation | Wiring | Reachability | Empirical Evidence & Root Cause |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **A. `TARGET_FIRST`** | **BLOCKED** | IMPLEMENTED | WIRED | **BLOCKED** | `signal_forward_observation.py:417-425` reads existing row from `signal_outcome_measurements` where `outcome='UNRESOLVED'`. Because `meas` is not None, `build_signal_outcome_measurement(sig_id)` is never invoked. Sandboxed test proved `system_signals.status='TARGET_1_HIT'` fails to transition `is_resolved` to 1. |
| **B. `SL_FIRST`** | **BLOCKED** | IMPLEMENTED | WIRED | **BLOCKED** | Same bypass mechanism as `TARGET_FIRST`. Stop-loss touch in `system_signals` is never materialized into `signal_outcome_measurements` because `sync_forward_outcomes` does not re-evaluate existing `UNRESOLVED` measurements. |
| **C. `TIMEOUT`** | **BLOCKED** | IMPLEMENTED | WIRED | **BLOCKED** | `SignalOutcomeTracker.run_stale_signal_expiry_sweep()` correctly identifies holding horizon expiry and updates `system_signals.status='EXPIRED'`, but `sync_forward_outcomes()` does not trigger Phase B remeasurement for rows with `outcome='UNRESOLVED'`. |
| **D. `AMBIGUOUS`** | **BLOCKED** | IMPLEMENTED | WIRED | **BLOCKED** | Ambiguous same-bar events logged in `system_signals` cannot propagate to forward observations because `sync_forward_outcomes()` skips Phase B remeasurement. |
| **E. `NO_DATA`** | **BLOCKED** | IMPLEMENTED | WIRED | **BLOCKED** | Missing observation data triggers `NO_DATA` in Phase B `normalize_outcome_state()`, but Phase B is never re-executed for in-flight rows. |
| **F. `INVALIDATED`** | **BLOCKED** | IMPLEMENTED | WIRED | **BLOCKED** | Invalidation checks occur in Phase B, which is bypassed by `sync_forward_outcomes()` for existing rows. |

---

## 6. Critical EXPIRED-State Check

Governance Rule:
> `system_signals.EXPIRED != canonical forward outcome resolution unless the Phase-B outcome measurement has actually materialized and the required MFE/MAE / Realized-R validation has completed.`

### Audit Findings:
1. **Zero Direct EXPIRED Leakage**:
   - In `core/signals/signal_forward_observation.py`, forward observation resolution relies exclusively on `meas.get("outcome")` from `signal_outcome_measurements`.
   - `system_signals.status == "EXPIRED"` is **never** directly queried or mapped by `SignalForwardObservationService`.
   - All outcomes must be processed through Phase B `normalize_outcome_state()`, which requires valid price path calculations, MFE/MAE derivation, and Realized-R calculation before assigning `outcome = 'TIMEOUT'`.
2. **Current Behavioral Invariant**:
   - Because of the `sync_forward_outcomes` caching defect, an `EXPIRED` status in `system_signals` cannot currently cause any forward resolution (false or genuine). The safety invariant against unmeasured premature resolution is strictly maintained.

---

## 7. Existing 101-Cohort Resolution Readiness

Read-only calculation of resolution capability for the next market session:

1. **Price Movement Dependency**:
   - All **101 observations** are actively observing and eligible to resolve via `TARGET_FIRST` or `SL_FIRST` if real market prices reach their defined barriers (Target 1, Target 2, Stop Loss).
2. **Timeout Eligibility**:
   - **32 Intraday Observations** (31 stock options + 1 index option):
     - 31 midday options have completed their creation session (2026-09-28) and are eligible for expiry evaluation.
     - 1 near-close option (`15:23 IST`) has a 1-session grace period expiring at session close (`15:30 IST`) of the next trading day.
   - **69 Swing Observations** (31 equity delivery + 38 futures):
     - Cannot resolve via TIMEOUT on the next trading session. These signals are on Day 1 of their 5-trading-day holding horizon. They require 5 elapsed trading sessions before becoming timeout-eligible (scheduled for 2026-10-06).
3. **Data-Quality Dependencies**:
   - All 101 observations require valid, unmasqueraded 1m/5m market feeds during the session. Current error rate is 0.0% (all 101 records have `data_quality_status = 'VALID_DATA'`).
4. **Implementation Dependencies**:
   - **All 101 observations** are currently blocked from completing resolution by defect `BLK-PHASE-D13-UNRESOLVED-MEASUREMENT-BYPASS`.

---

## 8. Score-Bucket Accumulation Audit

Current distribution across canonical score buckets:
- `70–74`: 3 observations (3.0%)
- `75–79`: 4 observations (4.0%)
- `80–84`: 14 observations (13.9%)
- `85+`: 80 observations (79.2%)

### Deterministic Analysis of Bucket Asymmetry:
1. **Category Threshold Policy**:
   - In `core/all_nse_scanner.py` (lines 385–410), category-specific minimum score thresholds are enforced:
     - `EQUITY_SWING_DELIVERY`: Minimum score threshold = **70**.
     - `STOCK_OPTIONS`, `INDEX_OPTIONS`, `FUTURES`: Minimum score threshold = **80**.
   - As a mathematical consequence, **Stock Options and Futures signals CANNOT generate scores in 70–74 or 75–79**.
   - Only Equity swing signals can ever enter the `70–74` and `75–79` buckets.
2. **Multi-Strategy Confluence Skew**:
   - The scanner evaluates 16 quantitative strategies. A setup is rewarded with compounding confluence points when multiple independent strategies agree (e.g. Trend + Momentum + Volume Breakout).
   - High-conviction setups naturally compound to scores of 85+. Moderate setups (e.g. 2 strategies agreeing) produce scores in 70–79.
3. **Longitudinal Governance Risk for Gate G1**:
   - The pipeline is structurally capable of generating signals across all four buckets (evidenced by 3 signals in 70–74 and 4 in 75–79).
   - However, the accumulation velocity in 70–74 and 75–79 is ~20x slower than 85+. Reaching 100 resolved observations in 70–74 will require significantly more trading sessions than in 85+.
   - **Governance Directive**: Thresholds must NOT be lowered, and artificial signals must NOT be created. This asymmetry must be respected as an empirical property of the multi-strategy architecture.

---

## 9. Market-Data Readiness

The market data ingestion pipeline is protected by the Phase D.4 remediation:
1. **Multi-Timeframe Freshness**:
   - 1m candles: evaluated with strict 120-second freshness window.
   - 5m candles: evaluated with 360-second freshness window (not evaluated under 1m rules).
   - 15m candles: evaluated with dedicated 15m semantics.
2. **Zero-Volume Cleaning**:
   - Zero-volume periods cleaned without dropping valid 1m candles.
3. **Masquerading Prevention**:
   - If 1m data is insufficient, `df1m` is marked unavailable; 5m candles are never masqueraded as 1m.
4. **DataFreshnessGuard**:
   - Protects against clock skew, future-dated bars, and stale feeds.
5. **HTTP 429 & Exception Handling**:
   - Exponential backoff and circuit-breaking active in `AllNSEScanner`.

---

## 10. Cryptographic Integrity

### Pre-Existing Cohort Hashes:
- **45-Cohort Baseline Hash** (rows 1–45):
  - Expected: `bb9bfa89bf4b29d9206ac7ead384c62f51fe8d3ebe22d115d9b1ac290f0ab9a8`
  - Actual:   `bb9bfa89bf4b29d9206ac7ead384c62f51fe8d3ebe22d115d9b1ac290f0ab9a8`
  - **Verdict**: **100.0% EXACT MATCH**
- **71-Cohort Continuation Hash** (rows 1–71):
  - Expected: `a1c02d746ec583c7dcfa25a36e6b2678530edff5d133cd1b66cdad8323358fd9`
  - Actual:   `a1c02d746ec583c7dcfa25a36e6b2678530edff5d133cd1b66cdad8323358fd9`
  - **Verdict**: **100.0% EXACT MATCH**
- **99-Cohort Continuation Hash** (rows 1–99):
  - Expected: `296635bab62c9c3a22bb5b6e528842e9da22e685531b49bc6fe71ab447e6bcd5`
  - Actual:   `296635bab62c9c3a22bb5b6e528842e9da22e685531b49bc6fe71ab447e6bcd5`
  - **Verdict**: **100.0% EXACT MATCH**
- **101-Cohort Hash** (rows 1–101):
  - Expected: `a1330442919d991466b6a78ae5a87d77cdddf9d4c60796d85793ff16adc89ddb`
  - Actual:   `a1330442919d991466b6a78ae5a87d77cdddf9d4c60796d85793ff16adc89ddb`
  - **Verdict**: **100.0% EXACT MATCH**

### Parity & Contamination Audit:
- Missing snapshots (`signal_prediction_snapshots`): **0**
- Missing outcome measurements (`signal_outcome_measurements`): **0**
- Missing system signals (`system_signals`): **0**
- Referential mismatches: **0**
- Synthetic / Mock records: **0**
- Seed records: **0**
- Historical backfill: **0**
- Pre-cutoff records: **0**
- Populated probabilities (`p_t1`, `p_t2`, `p_sl`, `p_timeout`, `expected_value_r`): **0** (All NULL, calibration `UNCALIBRATED`)

---

## 11. Test Suite Results (208 Tests)

### Suite A: Phase D Tests (110 Tests)
Command: `pytest tests/test_signal_forward_observation.py tests/test_signal_forward_wiring_remediation.py tests/test_candle_selection_remediation.py tests/test_data_freshness_guard.py tests/test_forward_accumulation_reporter.py`
- Result: **110 passed, 0 failed, 0 skipped** in 17.76s

### Suite B: Broader System Regression (98 Tests)
Command: `pytest tests/test_pipeline_remediation.py tests/test_universal_coverage_and_thresholds.py tests/test_signal_score_discrimination.py tests/test_signal_prediction_snapshots.py`
- Result: **98 passed, 0 failed, 0 skipped** in 19.70s

**Total**: **208 passed, 0 failed, 0 skipped** (100.0% Pass Rate).

---

## 12. Database Immutability

- **DB SHA-256 (Pre-Audit)**:  `bb64bad5dc0ca581bfa18942997c5d5e23a65f97c783a0ca2d084418573354c0`
- **DB SHA-256 (Post-Audit)**: `bb64bad5dc0ca581bfa18942997c5d5e23a65f97c783a0ca2d084418573354c0`
- **SHA-256 Match**: **100.0% Byte-for-Byte Exact Match** (0 bytes mutated)

### Table Row Count Parity:
| Table Name | Pre-Audit | Post-Audit | Delta | Status |
| :--- | :---: | :---: | :---: | :---: |
| `system_signals` | 498 | 498 | 0 | Unchanged |
| `signal_prediction_snapshots` | 101 | 101 | 0 | Unchanged |
| `signal_outcome_measurements` | 101 | 101 | 0 | Unchanged |
| `signal_forward_observations` | 101 | 101 | 0 | Unchanged |
| `scan_cycle_metrics` | 22 | 22 | 0 | Unchanged |

---

## 13. Phase-E Readiness Gate Status

| Gate ID | Criterion | Current Status | Gate Verdict |
| :--- | :--- | :---: | :--- |
| **G1** | $\ge 100$ resolved in every active bucket | Max resolved = 0/100 | **NOT SATISFIED** |
| **G2** | $\ge 300$ total resolved observations | Total resolved = 0/300 | **NOT SATISFIED** |
| **G3** | $\ge 2$ calendar months of forward accumulation | Elapsed = 0.03 / 2.0 months | **NOT SATISFIED** |
| **G4** | Continuous data feed & clean telemetry | 0 data errors, 0 rate limits | **PASS** |

**Phase E Mandate**: **STRICTLY BLOCKED**. Model fitting, probability generation, and calibration remain strictly barred.

---

## 14. Concrete Blockers & Risks

### Primary Blocker:
- **Identifier**: `BLK-PHASE-D13-UNRESOLVED-MEASUREMENT-BYPASS`
- **File**: [`core/signals/signal_forward_observation.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/core/signals/signal_forward_observation.py#L417-L428)
- **Mechanism**: `sync_forward_outcomes()` skips `phase_b_service.build_signal_outcome_measurement(sig_id)` whenever a row exists in `signal_outcome_measurements`. Because all 101 forward observations have existing rows with `outcome = 'UNRESOLVED'`, live price barrier touches and expiry transitions in `system_signals` never trigger Phase B recalculation, keeping all forward observations trapped in `OBSERVING` (`is_resolved = 0`).
- **Remediation Specification**:
  Change line 424 in `core/signals/signal_forward_observation.py` to:
  ```python
  if not meas or str(meas.get("outcome") or "UNRESOLVED").upper() == "UNRESOLVED":
      meas = phase_b_service.build_signal_outcome_measurement(sig_id)
  ```
  This preserves the immutability of already-terminal measurements (`TARGET_FIRST`, `SL_FIRST`, `TIMEOUT`, etc.) while ensuring in-flight `UNRESOLVED` observations are actively measured against current market data.

---

## 15. Final Verdict

Under the governance rules of `OPB-FINAL-PHASE-GOVERNANCE-001`, the audit concludes with:

# **`B. BLOCKED — ENGINEERING REMEDIATION REQUIRED`**

**Rationale**:  
While data quality guards, safety locks, cryptographic cohort hashes, and the 208-test regression suite are 100% intact and passing, the forward resolution pipeline possesses a concrete code-path blocker (`BLK-PHASE-D13-UNRESOLVED-MEASUREMENT-BYPASS`). As empirically demonstrated, live market price movements or holding horizon expirations cannot transition any of the 101 forward observations from `OBSERVING` to `RESOLVED` until this one-line remediation is applied.
