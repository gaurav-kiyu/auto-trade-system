# OPB PHASE D20-R1: RECONCILIATION & COMBINED VALIDATION REPORT

**Authority**: `OPB-FINAL-PHASE-GOVERNANCE-001`  
**Execution Timestamp**: `2026-09-29T15:58:00+05:30`  
**Git Branch**: `v2.60-phase-d-candle-selection-remediation`  
**Git HEAD**: `124f52c81322a46275a88c2291924198920a02b1`  
**Working Tree State**: Uncommitted Local Sandbox (Zero commits, Zero pushes)  
**Execution Mode**: READ-ONLY / OFFLINE ANALYSIS PASS  
**Local Database SHA-256**: `ceb7b33d1d90d64a445acb7d3377c1006f4292b3216d69fe4f2b34e274a22455` (Exact byte-for-byte unmutated)  
**EC2 Database Status**: Unmodified / Untouched  
**Phase E Status**: **STRICTLY BLOCKED / DO NOT PROCEED TO PHASE E** (`full_auto_allowed=False`, `BROKER_AUTO_ROUTING=DISCONNECTED`)  

---

## 1. D19 VS D20 BASELINE RECONCILIATION

### The Problem Investigated:
In the initial D20 summary presentation, a discrepancy was noted:
- D19 authoritative baseline reported: $N = 440$, $T1/T2 = 32$, $SL = 38$, $Timeout = 121$, $Ambiguous = 6$, $Active = 243$.
- An interim D20 summary table showed: $SL = 165$, $Timeout = 121$.

### Forensic Audit & Exact Root Cause:
A complete code, data, and event audit of both `artifacts/phase_d19_signal_quality_experiment.json`, `scratch/d19_experiment_engine.py`, `scratch/d20_historical_replay.py`, and `artifacts/phase_d20_controlled_remediation_validation.md` was conducted:

1. **The Underlying Data and Artifacts Always Contained Exactly 38 SL Hits**:
   - In `artifacts/phase_d20_controlled_remediation_validation.md` (lines 127–132), the baseline was recorded as:
     `T1: 32 | SL: 38 | Timeouts: 121 | Ambiguous: 6 | Active: 243 | Total: 440`.
   - In `artifacts/phase_d19_signal_quality_experiment.json`, `D1_Baseline` recorded:
     `t1_hits: 32, sl_hits: 38, timeouts: 121, ambiguous: 6, active: 243`.
2. **Exact Origin of the Number 165**:
   - The number **165** is the exact mathematical sum of **all non-target resolved outcomes**:
     $$\text{Non-Target Resolved Exits} = \text{SL\_HIT}\ (38) + \text{EXPIRED}\ (121) + \text{AMBIGUOUS}\ (6) = 165$$
   - In the informal chat summary table of the previous turn, the row label was written as *"Stop Loss Hits"* instead of *"Total Non-Target Resolved Exits"*.
   - When the row below it also displayed *"Timeouts: 121"*, it created the impression that pure SL hits totaled 165, which would have double-counted the 121 timeouts and 6 ambiguous outcomes.
3. **Exact Origin of the Number 56 under D20-A**:
   - Similarly, under D20-A, the remaining non-target resolved outcomes were:
     $$\text{D20-A Non-Target Resolved Exits} = \text{SL\_HIT}\ (36) + \text{EXPIRED}\ (14) + \text{AMBIGUOUS}\ (6) = 56$$
   - This was reported as 56 in the same summary table.
4. **Exact Origin of Holdout Numbers 94 and 29**:
   - Baseline Holdout non-target exits: $\text{SL}\ (17) + \text{Timeout}\ (73) + \text{Ambiguous}\ (4) = 94$.
   - D20-A Holdout non-target exits: $\text{SL}\ (16) + \text{Timeout}\ (9) + \text{Ambiguous}\ (4) = 29$.

### Reconciliation Table:

| Canonical Category | D19 Count | D20 Replay Count | Difference | Root Cause & Resolution |
| :--- | :---: | :---: | :---: | :--- |
| **TARGET_1_HIT** | 22 | 22 | 0 | Exact match |
| **TARGET_2_HIT** | 10 | 10 | 0 | Exact match |
| **TOTAL TARGETS (T1+T2)** | **32** | **32** | **0** | **Exact match across all pipelines** |
| **SL_HIT (Pure Stop Loss)** | **38** | **38** | **0** | **Exact match (165 was conflated non-target exits)** |
| **EXPIRED (Timeout)** | **121** | **121** | **0** | **Exact match** |
| **AMBIGUOUS (Same-bar)** | **6** | **6** | **0** | **Exact match** |
| **ACTIVE / HOLDING** | **243** | **243** | **0** | **Exact match** ($243 + 197 = 440$) |
| **TOTAL POPULATION** | **440** | **440** | **0** | **Exact match; zero missing rows** |
| *Composite Non-Target (SL+TO+Ambig)* | *165* | *165* | *0* | *Proves source of 165 reporting label* |

$$\sum \text{Categories} = 32\ (\text{Targets}) + 38\ (\text{SL}) + 121\ (\text{Timeouts}) + 6\ (\text{Ambiguous}) + 243\ (\text{Active}) = 440$$

There is zero discrepancy in the underlying authoritative dataset. The accounting is strictly unified.

---

## 2. REBUILT AUTHORITATIVE D20 BASELINE

Using canonical R1–R4 outcome-accounting semantics:

| Metric | Authoritative Full Population ($N=440$) | Authoritative Design Cohort ($N=127$) | Authoritative Holdout Cohort ($N=313$) |
| :--- | :---: | :---: | :---: |
| **Total Signals** | 440 | 127 | 313 |
| **Target 1 Hits** | 22 | 7 | 15 |
| **Target 2 Hits** | 10 | 5 | 5 |
| **Total Target Hits** | **32** | **12** | **20** |
| **Stop Loss Hits** | **38** | **21** | **17** |
| **Timeouts (Expired)** | **121** | **48** | **73** |
| **Ambiguous (Same-Bar)** | **6** | **2** | **4** |
| **Active / Holding** | **243** | **44** | **199** |
| **Disqualified (DQ)** | **0** | **0** | **0** |
| **Target Hit Rate** | **7.27%** | **9.45%** | **6.39%** |
| **Resolved Win Rate** | **16.24%** | **14.46%** | **17.54%** |
| **Pure Win Rate (T vs SL)** | **45.71%** | **36.36%** | **54.05%** |
| **Average MFE** | 1.14% | 1.31% | 1.07% |
| **Median MFE** | 0.00% | 0.00% | 0.00% |
| **Average MAE** | 0.63% | 1.02% | 0.47% |
| **Median MAE** | 0.00% | 0.00% | 0.00% |

$$\text{Target Hit Rate} = \frac{32}{440} = 7.27\%$$
$$\text{Resolved Win Rate} = \frac{32}{32 + 38 + 121 + 6} = \frac{32}{197} = 16.24\%$$
$$\text{Pure Win Rate} = \frac{32}{32 + 38} = \frac{32}{70} = 45.71\%$$

---

## 3. COMBINED EXPERIMENT RESULTS (V0, V1, V2, V3A, V3B)

Four variants were evaluated across the identical historical dataset ($N=440$):
- **V0**: Authoritative Baseline (Unfiltered).
- **V1**: D20-A Options Gate (`breakout > 0` AND `volume > 0` for `STOCK_OPTIONS` and `INDEX_OPTIONS`).
- **V2**: D20-A + D20-B (Options Gate + Index Session Deduplication: max 1 CALL + 1 PUT per index per session).
- **V3a**: D20-A + D20-B + D20-C Target-Only Candidate (+1.2% Target / Existing -3.0% SL).
- **V3b**: D20-A + D20-B + D20-C Target + SL Candidate (+1.2% Target / Shortened -1.0% SL).

### Full Population Comparative Matrix ($N=440$):

| Metric | V0 (Baseline) | V1 (D20-A) | V2 (D20-A+B) | V3a (+1.2% T / -3% SL) | V3b (+1.2% T / -1% SL) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Total Signals** | 440 | 440 | 440 | 440 | 440 |
| **Retained Signals** | 440 (100.0%) | 302 (68.64%) | 302 (68.64%) | 302 (68.64%) | 302 (68.64%) |
| **Filtered Signals** | 0 | 138 (31.36%) | 138 (31.36%) | 138 (31.36%) | 138 (31.36%) |
| **Unique Opportunities** | 373 | 296 | 296 | 296 | 296 |
| **Target 1 Hits** | 22 | 22 | 22 | 24 | 24 |
| **Target 2 Hits** | 10 | 10 | 10 | 10 | 10 |
| **Total Targets** | **32** | **32** | **32** | **34 (+2)** | **34 (+2)** |
| **Stop Loss Hits** | **38** | **36 (-2)** | **36 (-2)** | **36 (-2)** | **37 (-1)** |
| **Timeouts** | **121** | **14 (-88.4%)**| **14 (-88.4%)**| **18 (-85.1%)**| **17 (-86.0%)**|
| **Ambiguous Same-Bar**| 6 | 6 | 6 | 6 | 6 |
| **Active / Holding** | 243 | 214 | 214 | 208 | 208 |
| **Target Hit Rate** | **7.27%** | **10.60%** | **10.60%** | **11.26%** | **11.26%** |
| **Resolved Win Rate** | **16.24%** | **36.36%** | **36.36%** | **36.17%** | **36.17%** |
| **Pure Win Rate (T vs SL)**| **45.71%** | **47.06%** | **47.06%** | **48.57%** | **47.89%** |
| **Average MFE** | 1.14% | 1.59% | 1.59% | 1.59% | 1.59% |
| **Median MFE** | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| **Average MAE** | 0.63% | 0.81% | 0.81% | 0.81% | 0.81% |
| **Median MAE** | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |

---

## 4. DECOMPOSITION OF V3A VS V3B (TARGET-DISTANCE VS SL-DISTANCE EFFECTS)

By isolating the target distance from the stop-loss distance across the 21 retained options signals:

1. **Target-Distance Effect (V3a vs V2)**:
   - Target distance shortened from +4.0% to +1.2% while keeping SL at -3.0%.
   - **Targets**: Increases from 32 to 34 (+2 target hits: e.g., `ICICIGI` CALL MFE reached +1.7%).
   - **Stop Losses**: Unchanged at 36.
   - **Pure Win Rate**: Improves from 47.06% to **48.57%**.
2. **Stop-Loss Distance Effect (V3b vs V3a)**:
   - Stop loss tightened from -3.0% to -1.0% while keeping target at +1.2%.
   - **Stop Losses**: Increases from 36 to 37 (+1 additional SL hit: `PVRINOX` CALL reached MAE = 2.44%, which avoids a -3.0% SL but breaches a -1.0% SL).
   - **Timeouts**: Decreases from 18 to 17 (the signal converts from a timeout into a stop loss).
   - **Pure Win Rate**: Drops slightly from 48.57% to **47.89%**.
3. **Conclusion on Decomposition**:
   - Shortening options targets provides a modest lift (+2 targets).
   - Tightening options stop loss from -3.0% to -1.0% increases stop-outs (+1 SL) on volatile pullbacks without generating additional target hits.

---

## 5. CHRONOLOGICAL HOLDOUT COMPARISON

The dataset was strictly evaluated on the unseen out-of-sample holdout period ($N=313$, generated between 2026-09-25 and 2026-09-29):

| Metric | V0 (Holdout Base) | V1 (D20-A) | V2 (D20-A+B) | V3a (Exp Target) | V3b (Exp Target+SL) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Retained Signals** | 313 (100.0%) | 219 (69.97%) | 219 (69.97%) | 219 (69.97%) | 219 (69.97%) |
| **Filtered Signals** | 0 | 94 (30.03%) | 94 (30.03%) | 94 (30.03%) | 94 (30.03%) |
| **Target Preservation**| 20 | **20 (100.0%)**| **20 (100.0%)**| **21 (+1)** | **21 (+1)** |
| **Stop Loss Hits** | 17 | 16 (-1) | 16 (-1) | 16 (-1) | 17 (0) |
| **Timeouts** | 73 | **9 (-87.7%)** | **9 (-87.7%)** | **14 (-80.8%)**| **13 (-82.2%)**|
| **Active / Holding** | 199 | 170 | 170 | 164 | 164 |
| **Target Hit Rate** | 6.39% | **9.13%** | **9.13%** | **9.59%** | **9.59%** |
| **Resolved Win Rate** | 17.54% | **40.82%** | **40.82%** | **38.18%** | **38.18%** |
| **Pure Win Rate** | 54.05% | **55.56%** | **55.56%** | **56.76%** | **55.26%** |

### Design Period Performance ($N=127$, 2026-09-14 to 2026-09-24):
- **V0**: Retained 127, 12 Targets, 21 SL, 48 Timeouts $\to$ Resolved Win Rate: **14.46%**.
- **V1 / V2**: Retained 83, 12 Targets (**100% preserved**), 20 SL, 5 Timeouts ($-89.6\%$) $\to$ Resolved Win Rate: **30.77%**.
- **V3a / V3b**: Retained 83, 13 Targets (+1), 20 SL, 4 Timeouts $\to$ Resolved Win Rate: **33.33%**.

---

## 6. D20-B SPECIFIC STANDALONE VALIDATION

To evaluate D20-B in complete isolation (independent of D20-A), the index deduplication algorithm was executed directly against all historical index option signals:

| Dimension | Baseline Index Signals | Retained Under D20-B | Filtered Under D20-B | Delta / Retention |
| :--- | :---: | :---: | :---: | :---: |
| **Total Index Signals** | 60 | **43** | **17** | **71.67% retained** |
| **CALL Signals** | 31 | 25 | 6 | 80.65% retained |
| **PUT Signals** | 29 | 18 | 11 | 62.07% retained |
| **Target Hits** | 0 | 0 | 0 | 0 targets lost (100% preserved) |
| **Stop Loss Hits** | 0 | 0 | 0 | 0 change |
| **Timeouts** | 57 | 43 | 14 | **-14 timeouts eliminated** |
| **Active Signals** | 3 | 0 | 3 | -3 redundant active eliminated |

### Invariant Rules Confirmed:
1. **Maximum 1 CALL per index per session**: Verified (subsequent same-day CALLs blocked).
2. **Maximum 1 PUT per index per session**: Verified (subsequent same-day PUTs blocked).
3. **CALL + PUT Coexistence**: Verified (a CALL and a PUT for NIFTY on the same date both pass).
4. **Session Date Rollover Reset**: Verified (quotas cleanly reset at 00:00:00 IST on date transition).
5. **Why V1 and V2 are Identical in Combined Evaluation**:
   - In the historical dataset, all 60 index option signals had `breakout == 0` or `volume == 0`.
   - Therefore, D20-A filtered all 60 index options before D20-B was evaluated.
   - In live forward trading where index options pass the breakout/volume gate, D20-B acts as an essential secondary safeguard against same-session index burst spam.

---

## 7. D20-A SPECIFIC VALIDATION

### Invariant Checks:
- **STOCK_OPTIONS**: Gate enforced. Signals with `breakout <= 0` or `volume <= 0` or missing components are rejected fail-closed.
- **INDEX_OPTIONS**: Gate enforced. Same breakout and volume confirmation required.
- **EQUITY_SWING_DELIVERY**: **100% UNCHANGED**. All 279 cash equity swing signals bypass the gate without modification.
- **Pre-Persistence / Pre-Dispatch Filtering**:
  - In `core/all_nse_scanner.py`, `_dispatch_alert_if_eligible` rejects un-gated options prior to alert dispatch.
  - In `core/signals/signal_tracker.py`, `record_generated_signal` rejects un-gated options prior to SQLite persistence.

---

## 8. D20-C SPECIFIC VALIDATION

### Production Defaults:
- Strictly maintained at T1 = +4.0%, T2 = +8.0%, SL = -3.0%.
- Verified via unit test `test_d20_experimental_target_model_production_default`.
- When `mode="PRODUCTION"` or unspecified, zero experimental logic is invoked.

---

## 9. CATEGORY & DIRECTION BREAKDOWN

### Category Breakdown Under V2 (D20-A + D20-B):

| Category | Baseline Total | Retained | Filtered | Targets | SL | Timeouts | Resolved Win Rate |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **EQUITY_SWING_DELIVERY**| 279 | 279 (100.0%) | 0 (0.0%) | 31 | 35 | 0 | 46.97% (Identical) |
| **STOCK_OPTIONS** | 99 | 21 (21.21%) | 78 (78.79%) | 0 | 1 | 14 | 0.00% (T=2 in V3) |
| **INDEX_OPTIONS** | 60 | 0 (0.0%) | 60 (100.0%) | 0 | 0 | 0 | N/A (Noise purged) |
| **FUTURES** | 2 | 2 (100.0%) | 0 (0.0%) | 1 | 0 | 0 | Excluded per R1 |

### Direction Breakdown Under V2 (D20-A + D20-B):

| Direction | Baseline Total | Retained | Filtered | Targets | SL | Timeouts | Resolved Win Rate |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **CALL** | 338 | 290 (85.80%) | 48 (14.20%) | 31 | 30 | 8 | 44.93% (vs 29.81%) |
| **PUT** | 102 | 12 (11.76%) | 90 (88.24%) | 1 | 6 | 6 | 7.69% (vs 1.39%) |

---

## 10. DATA INTEGRITY & AUDIT PROOF

| State Item | Pre-Reconciliation Value | Post-Reconciliation Value | Audit Status |
| :--- | :--- | :--- | :---: |
| **Local Database SHA-256** | `ceb7b33d1d90d64a445acb7d3377c1006f4292b3216d69fe4f2b34e274a22455` | `ceb7b33d1d90d64a445acb7d3377c1006f4292b3216d69fe4f2b34e274a22455` | **VERIFIED UNCHANGED** |
| **Production Row Mutations**| 0 rows written | 0 rows written | **ZERO MUTATION** |
| **Synthetic Records Added** | 0 | 0 | **ZERO FABRICATION** |
| **Historical Outcomes Altered**| 0 | 0 | **ZERO BACKFILL** |
| **EC2 Access** | None | None | **ZERO EC2 ACCESS** |
| **GitHub Remote Access** | None | None | **ZERO GITHUB ACCESS** |
| **Broker live calls** | None | None | **ZERO BROKER ACCESS** |

---

## 11. REGRESSION SUITE STATUS

Full 221-test suite execution evidence:
- **Tests Executed**: 221
- **Passed**: 221 (100.0%)
- **Failed**: 0
- **Duration**: 12.75 seconds

---

## 12. FINAL CANDIDATE CLASSIFICATION

In accordance with strict OPB governance vocabulary:

1. **D20-A (Category-Aware Options Quality Gate: breakout > 0 AND volume > 0)**:
   - **Classification**: **SUPPORTED FOR NEXT VALIDATION**
   - **Rationale**: Demonstrates consistent empirical timeout reduction (-88.4%) with 100% target preservation across both design and out-of-sample holdout cohorts, with zero mutation to cash equity delivery.
2. **D20-B (Index Session Deduplication: max 1 CALL + 1 PUT per index/session)**:
   - **Classification**: **SUPPORTED FOR NEXT VALIDATION**
   - **Rationale**: Eliminates 17 redundant same-session index burst signals (-28.3%) in standalone testing with zero target loss, preventing alert flooding.
3. **D20-C (Experimental Target Model Scaffolding: +1.2% Target)**:
   - **Classification**: **PROMISING BUT INSUFFICIENT EVIDENCE**
   - **Rationale**: Generates +2 target hits in historical replay under V3a, but options sample size in low-volatility conditions remains small ($N=21$); tightening stop loss (V3b) increases stop-outs. Production defaults must remain active until forward staging evidence is gathered.

---

## 13. FINAL STATUS & GOVERNANCE COMPLIANCE

```text
FINAL STATUS:      D20-R1 COMPLETE / BLOCKED
GITHUB:            NOT TOUCHED
EC2:               NOT TOUCHED
BROKER:            NOT TOUCHED
PRODUCTION:        UNCHANGED
PHASE E:           BLOCKED

WAIT FOR OPERATOR REVIEW.
```
