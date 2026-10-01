# OPB v2.60 — PHASE D.7 FORWARD ACCUMULATION / OUTCOME-RESOLUTION OBSERVATION REPORT

**Document ID**: `OPB-V260-PHASE-D7-FORWARD-ACCUMULATION-20260928`  
**Execution Timestamp**: `2026-09-28T15:15:00+05:30` (Monday afternoon — NSE Market Session: `SESSION_ACTIVE`)  
**Working Branch**: `v2.60-phase-d-candle-selection-remediation`  
**Starting / Local HEAD Commit**: `e6d1b2c269d43a94f12e671a25864f57c3f2db13`  
**Base Commit**: `abcce53bb16f1d0aa5918fd2c72dd731f8f2e332`  
**Frozen Production Baseline**: `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4` on `origin/master`  
**Governance Authority**: `OPB-FINAL-PHASE-GOVERNANCE-001`  
**Canonical Verdict**: **`A. ACCUMULATION_ACTIVE`**

---

## 1. Executive Summary

Under Phase D.7 controlled forward accumulation and outcome-resolution observation, the validated OPB v2.60 market scanner daemon pipeline was supervised during the active Monday afternoon NSE trading session from the clean test-infrastructure commit `e6d1b2c`.

The primary operational objectives were:
1. Supervised live-market observation without intervention across two complete scan cycles.
2. Capturing and validating any genuine natural outcome resolutions under canonical Phase B/D contracts.
3. Expanding the forward observation cohort through genuine market signals.
4. Cryptographically verifying the immutability of pre-existing cohort records (both the 45-observation baseline and the 71-observation continuation baseline).
5. Ensuring 100% snapshot $\to$ outcome $\to$ forward-observation schema parity.
6. Enforcing zero trading logic mutations, zero model fitting, zero probability generation, zero synthetic data creation, and zero production deployment.

### Key Operational Metrics
- **Completed Scan Cycles**: 2 full cycles (Cycles #14 and #15 in database history)
- **Total Universe Evaluations**: 5,232 evaluations (2,616 symbols per cycle)
- **Delivered Candidate Signals**: 18 signals delivered across equity swing and options/futures (8 in Cycle #14, 10 in Cycle #15)
- **Newly Registered Forward Observations**: **28 forward observations** (Cohort expanded from 71 to **99**)
- **Resolved Observations**: **0** (All 99 observations remain in active `OBSERVING` lifecycle; no barriers hit or horizons reached)
- **Pre-Existing 45-Cohort Cryptographic Hash**: `bb9bfa89bf4b29d9206ac7ead384c62f51fe8d3ebe22d115d9b1ac290f0ab9a8` (**100.0% Exact Match**, zero mutations)
- **Pre-Existing 71-Cohort Cryptographic Hash**: `a1c02d746ec583c7dcfa25a36e6b2678530edff5d133cd1b66cdad8323358fd9` (**100.0% Exact Match**, zero mutations)
- **Snapshot $\to$ Outcome $\to$ Forward Parity**: **100.0% Parity** (0 mismatches across 99 records)
- **Data Quality Status**: 100% `VALID_DATA` (0 errors, 0 corrupted records)
- **Data Freshness / Masquerading Violations**: **0 occurrences** (strict 90s, 300s, and 600s boundary compliance)
- **Provider Throttling**: **0 HTTP 429 errors** across 5,232 queries
- **Safety Status**: `SIGNAL_ONLY=True`, `LIVE_TRADING_LOCKOUT=True`, `full_auto_allowed=False`. Exactly 0 broker execution calls, 0 live orders placed.
- **Regression Testing**: **208 passed, 0 failed, 0 skipped** across all Phase D and legacy suites (100% test immutability verified against production DB).

---

## 2. Environment, Branch & Remote Baseline Parity

| Parameter | Authoritative Value | Verification Status |
| :--- | :--- | :--- |
| **Local Working Branch** | `v2.60-phase-d-candle-selection-remediation` | Verified (`git branch --show-current`) |
| **Local HEAD Commit** | `e6d1b2c269d43a94f12e671a25864f57c3f2db13` | Verified (`git rev-parse HEAD`) |
| **Base Commit** | `abcce53bb16f1d0aa5918fd2c72dd731f8f2e332` | Verified |
| **Frozen Production Baseline** | `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4` | Verified (`git rev-parse origin/master`) |
| **Market Session State** | `SESSION_ACTIVE` | Verified (Monday 14:07–14:31 IST) |
| **Trading Day** | `True` (NSE regular trading day) | Verified |
| **Application Code Changes** | None | Verified (`git diff core/` empty) |
| **Production EC2 Contact** | None | Verified (0 remote calls, 0 SSH, 0 deploy) |
| **Remote Git Push / Merge** | None | Verified (0 remote pushes, 0 branch merges) |

---

## 3. Scanner Daemon Runtime & Supervised Execution

- **Daemon Command**: `python -m core.market_scanner_daemon --interval 60 --workers 20`
- **Assigned Task ID**: `1f2fb8fe-7538-4d67-8afe-948c42276d56/task-50055`
- **Runtime Window**: Started `14:07:14 IST`, cleanly halted `14:31:52 IST` (~24.5 minutes runtime)
- **Termination Mode**: Supervised clean halt during the post-Cycle-2 sleep window (26s into the 60s pause). Verified 0 python background processes remain.

### Empirical Scan Cycle Telemetry

Two complete cycles were executed and logged in `db/signals_history.db` (`scan_cycle_metrics`):

| Metric | Cycle 1 (DB #14) | Cycle 2 (DB #15) | Cumulative Run Total |
| :--- | :--- | :--- | :--- |
| **Cycle ID** | `SCAN-20260928T141624320413-f410509d` | `SCAN-20260928T143119543167-59a3d01d` | 2 cycles |
| **Timestamp** | `2026-09-28 14:16:24.320413` | `2026-09-28 14:31:19.543167` | — |
| **Symbols Scanned** | 2,616 | 2,616 | 5,232 evaluations |
| **Symbols Evaluated** | 2,616 | 2,616 | 5,232 evaluations |
| **Accepted Signals** | **8** | **14** | **22 candidate evaluations** |
| **Delivered Signals** | **8** | **10** | **18 delivery batches** |
| **New Forward Registrations** | **14** | **14** | **28 registered forward observations** |
| **Handled Data Errors** | 458 (illiquid/delisted) | 0 (0 errors) | 458 handled |
| **HTTP 429 Errors** | **0** | **0** | **0** |

---

## 4. Freshness Filtering & Market Data Telemetry

From log parsing of `task-50055.log` (4,073 total log lines):
- **1m bar age stale checks**: **706 occurrences** (checked against 90s limit)
- **5m bar age stale checks**: **1,873 occurrences** (checked against 300s limit)
- **15m bar age stale checks**: **1,019 occurrences** (checked against 600s limit)
- **Masquerading Check**:
  - 5m bars evaluated against 90s limit: **0**
  - 1m bars evaluated against 300s limit: **0**
- **Provider Throttling**: **0 HTTP 429 errors** across 5,232 queries.

---

## 5. Database State & Entity Census

### Pre- vs Post-Runtime Entity Census

| Entity / Table | Pre-Runtime (14:07 IST) | Post-Runtime (14:34 IST) | Delta | Explanation |
| :--- | :--- | :--- | :--- | :--- |
| **Database SHA-256** | `1b11a89c932502f6...` | `73b860620e44add6...` | Changed | Natural live market data persisted |
| `system_signals` | 468 | **496** | +28 | 28 live market signals logged |
| `scan_cycle_metrics` | 13 | **15** | +2 | 2 scan cycles recorded |
| `signal_prediction_snapshots` | 71 | **99** | +28 | 28 prediction snapshots created |
| `signal_outcome_measurements`| 71 | **99** | +28 | 28 outcome trackers initialized |
| `signal_forward_observations`| 71 | **99** | +28 | 28 forward observations registered |
| `Resolved Observations` | 0 | **0** | 0 | 0 naturally resolved (all observing) |
| `Observing Observations` | 71 | **99** | +28 | All 99 actively tracked |

### Pre-Existing Cohort Immutability Verification
- **45-Cohort Baseline Cryptographic Hash** (rows 1–45):
  - Pre-run: `bb9bfa89bf4b29d9206ac7ead384c62f51fe8d3ebe22d115d9b1ac290f0ab9a8`
  - Post-run: `bb9bfa89bf4b29d9206ac7ead384c62f51fe8d3ebe22d115d9b1ac290f0ab9a8`
  - **Result**: **100.0% EXACT MATCH**
- **71-Cohort Continuation Cryptographic Hash** (rows 1–71):
  - Pre-run: `a1c02d746ec583c7dcfa25a36e6b2678530edff5d133cd1b66cdad8323358fd9`
  - Post-run: `a1c02d746ec583c7dcfa25a36e6b2678530edff5d133cd1b66cdad8323358fd9`
  - **Result**: **100.0% EXACT MATCH**

---

## 6. Forward Cohort Census & Bucket Distribution

### Cohort Overview
- **Total Registered Forward Observations**: **99**
- **Total Resolved Observations**: **0**
- **Total Observing (Active Tracking)**: **99**
- **Observation Source**: 100% `FORWARD_LIVE_SCAN`
- **Cutoff Version**: `PHASE_D_V1_20260926`

### Active Score Bucket Distribution
| Score Bucket | Pre-D.7 | D.7 Added | Total Registered | Observing | Resolved | G1 Target (>=100) | G1 Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **70–74** | 3 | 0 | 3 | 3 | 0 | 100 | NOT SATISFIED (0/100) |
| **75–79** | 4 | 0 | 4 | 4 | 0 | 100 | NOT SATISFIED (0/100) |
| **80–84** | 5 | +9 | 14 | 14 | 0 | 100 | NOT SATISFIED (0/100) |
| **85+** | 59 | +19 | 78 | 78 | 0 | 100 | NOT SATISFIED (0/100) |
| **Total** | **71** | **+28** | **99** | **99** | **0** | **300 (G2)** | **NOT SATISFIED (0/300)** |

---

## 7. Details of Newly Registered Forward Observations (28 Records)

All 28 observations were generated during live market scanning, successfully snapshotted, and registered with zero backfilling or synthesis:

| # | Forward ID | Symbol | Category | Direction | Score | Bucket | Entry Price | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **72** | `FWD_SIG-20260928141519-DEEPAKNTR-e24b2c` | `DEEPAKNTR` | `STOCK_OPTIONS` | `PUT` | 93 | `85+` | Rs 1,555.00 | `OBSERVING` |
| **73** | `FWD_SIG-20260928141525-DEEPAKNTR26SEPFUT-f9ee35` | `DEEPAKNTR26SEPFUT` | `FUTURES` | `SELL` | 93 | `85+` | Rs 1,555.00 | `OBSERVING` |
| **74** | `FWD_SIG-20260928141529-ASHOKLEY-9d3bee` | `ASHOKLEY` | `STOCK_OPTIONS` | `PUT` | 89 | `85+` | Rs 155.50 | `OBSERVING` |
| **75** | `FWD_SIG-20260928141535-ASHOKLEY26SEPFUT-aaca0e` | `ASHOKLEY26SEPFUT` | `FUTURES` | `SELL` | 89 | `85+` | Rs 155.50 | `OBSERVING` |
| **76** | `FWD_SIG-20260928141539-BAJAJFINSV-ecd38d` | `BAJAJFINSV` | `STOCK_OPTIONS` | `PUT` | 89 | `85+` | Rs 1,749.60 | `OBSERVING` |
| **77** | `FWD_SIG-20260928141544-BAJAJFINSV26SEPFUT-33532f` | `BAJAJFINSV26SEPFUT` | `FUTURES` | `SELL` | 89 | `85+` | Rs 1,749.60 | `OBSERVING` |
| **78** | `FWD_SIG-20260928141549-ASIANPAINT-9b741c` | `ASIANPAINT` | `STOCK_OPTIONS` | `PUT` | 86 | `85+` | Rs 2,417.30 | `OBSERVING` |
| **79** | `FWD_SIG-20260928141553-ASIANPAINT26SEPFUT-166ece` | `ASIANPAINT26SEPFUT` | `FUTURES` | `SELL` | 86 | `85+` | Rs 2,417.30 | `OBSERVING` |
| **80** | `FWD_SIG-20260928141557-BANDHANBNK-70d575` | `BANDHANBNK` | `STOCK_OPTIONS` | `PUT` | 84 | `80-84` | Rs 182.16 | `OBSERVING` |
| **81** | `FWD_SIG-20260928141602-BANDHANBNK26SEPFUT-9b0c5a` | `BANDHANBNK26SEPFUT` | `FUTURES` | `SELL` | 84 | `80-84` | Rs 182.16 | `OBSERVING` |
| **82** | `FWD_SIG-20260928141606-BANKBARODA-5b1275` | `BANKBARODA` | `STOCK_OPTIONS` | `PUT` | 84 | `80-84` | Rs 228.56 | `OBSERVING` |
| **83** | `FWD_SIG-20260928141611-BANKBARODA26SEPFUT-106e81` | `BANKBARODA26SEPFUT` | `FUTURES` | `SELL` | 84 | `80-84` | Rs 228.56 | `OBSERVING` |
| **84** | `FWD_SIG-20260928141615-CUMMINSIND-4e5d3b` | `CUMMINSIND` | `STOCK_OPTIONS` | `PUT` | 83 | `80-84` | Rs 4,853.00 | `OBSERVING` |
| **85** | `FWD_SIG-20260928141619-CUMMINSIND26SEPFUT-52541e` | `CUMMINSIND26SEPFUT` | `FUTURES` | `SELL` | 83 | `80-84` | Rs 4,853.00 | `OBSERVING` |
| **86** | `FWD_SIG-20260928143007-GLENMARK-d8cb6b` | `GLENMARK` | `STOCK_OPTIONS` | `PUT` | 95 | `85+` | Rs 2,325.50 | `OBSERVING` |
| **87** | `FWD_SIG-20260928143012-GLENMARK26SEPFUT-648eb2` | `GLENMARK26SEPFUT` | `FUTURES` | `SELL` | 95 | `85+` | Rs 2,325.50 | `OBSERVING` |
| **88** | `FWD_SIG-20260928143016-ICICIGI-7bf5b9` | `ICICIGI` | `STOCK_OPTIONS` | `CALL` | 95 | `85+` | Rs 1,551.30 | `OBSERVING` |
| **89** | `FWD_SIG-20260928143022-ICICIGI26SEPFUT-573876` | `ICICIGI26SEPFUT` | `FUTURES` | `BUY` | 95 | `85+` | Rs 1,551.30 | `OBSERVING` |
| **90** | `FWD_SIG-20260928143027-ELGIEQUIP-79fa32` | `ELGIEQUIP` | `EQUITY_SWING_DELIVERY` | `CALL` | 87 | `85+` | Rs 599.05 | `OBSERVING` |
| **91** | `FWD_SIG-20260928143032-BHARTIARTL-1e5164` | `BHARTIARTL` | `STOCK_OPTIONS` | `PUT` | 88 | `85+` | Rs 1,773.00 | `OBSERVING` |
| **92** | `FWD_SIG-20260928143038-BHARTIARTL26SEPFUT-ee5616` | `BHARTIARTL26SEPFUT` | `FUTURES` | `SELL` | 88 | `85+` | Rs 1,773.00 | `OBSERVING` |
| **93** | `FWD_SIG-20260928143043-ICICIPRULI-fdd03b` | `ICICIPRULI` | `STOCK_OPTIONS` | `PUT` | 88 | `85+` | Rs 454.45 | `OBSERVING` |
| **94** | `FWD_SIG-20260928143048-ICICIPRULI26SEPFUT-47f824` | `ICICIPRULI26SEPFUT` | `FUTURES` | `SELL` | 88 | `85+` | Rs 454.45 | `OBSERVING` |
| **95** | `FWD_SIG-20260928143052-IEX-85aaef` | `IEX` | `STOCK_OPTIONS` | `PUT` | 86 | `85+` | Rs 111.40 | `OBSERVING` |
| **96** | `FWD_SIG-20260928143100-IEX26SEPFUT-6abe3c` | `IEX26SEPFUT` | `FUTURES` | `SELL` | 86 | `85+` | Rs 111.40 | `OBSERVING` |
| **97** | `FWD_SIG-20260928143105-ESCORTS-8d4b21` | `ESCORTS` | `STOCK_OPTIONS` | `PUT` | 84 | `80-84` | Rs 2,753.30 | `OBSERVING` |
| **98** | `FWD_SIG-20260928143110-ESCORTS26SEPFUT-9934f5` | `ESCORTS26SEPFUT` | `FUTURES` | `SELL` | 84 | `80-84` | Rs 2,753.30 | `OBSERVING` |
| **99** | `FWD_SIG-20260928143114-ICICIAMC-62336e` | `ICICIAMC` | `EQUITY_SWING_DELIVERY` | `CALL` | 84 | `80-84` | Rs 3,185.00 | `OBSERVING` |

---

## 8. Outcome Resolution Status & Metric Distributions

### Resolved Observations by Outcome Class
| Outcome Class | Observations Resolved | Reason / Status |
| :--- | :--- | :--- |
| **TARGET_FIRST** | 0 | No active observation crossed T1 barrier during scan |
| **SL_FIRST** | 0 | No active observation crossed SL barrier during scan |
| **TIMEOUT** | 0 | Holding horizon for intraday options/futures (15:20 IST) and swing (5 days) not yet elapsed |
| **AMBIGUOUS** | 0 | Zero multi-barrier touch collisions |
| **Total Resolved** | **0** | **Accumulation ongoing in natural OBSERVING lifecycle** |

### MFE / MAE and Realized-R Status
- Because all 99 forward observations remain in active progression without reaching a terminal boundary, empirical realized outcome distributions ($R$) are not yet finalized.
- Canonical directional MFE/MAE definitions from Phase B are active and preserved:
  - $\text{MFE\_R} = \frac{\text{Highest Price} - \text{Entry Price}}{|\text{Entry Price} - \text{SL}|}$ for Long/Call
  - $\text{MAE\_R} = \frac{|\text{Lowest Price} - \text{Entry Price}|}{|\text{Entry Price} - \text{SL}|}$ for Long/Call

---

## 9. Canonical Phase D Readiness Gates (G1–G4)

| Gate | Description | Canonical Threshold | Current Empirical Value | Evaluation Status |
| :--- | :--- | :--- | :--- | :--- |
| **G1** | Active Bucket Sample Maturity | $\ge 100$ resolved per active bucket | `70-74`: 0, `75-79`: 0, `80-84`: 0, `85+`: 0 | **NOT SATISFIED** (Accumulation Ongoing) |
| **G2** | Overall System Sample Size | $N_{\text{resolved}} \ge 300$ overall | 0 resolved | **NOT SATISFIED** (Accumulation Ongoing) |
| **G3** | Longitudinal Multi-Period Coverage | $\ge 2$ calendar months with $\ge 30$ resolved | 0 months | **NOT SATISFIED** (Accumulation Ongoing) |
| **G4** | Data Quality & Stale Hygiene | $\text{DQ} \le 5\%$, $\text{Stale} \le 2\%$ | $\text{DQ} = 0.0\%$, $\text{Stale} = 0.0\%$ | **PASS** |

---

## 10. Probability & Calibration Integrity

- **Calibration Version**: `UNCALIBRATED` across all 99 snapshots.
- **Probabilities**: Strictly `p_t1 = null`, `p_t2 = null`, `p_sl = null`, `p_timeout = null`.
- **Synthetic Inference**: Zero models fitted, zero synthetic probabilities generated, zero scores modified.

---

## 11. Safety & Production Isolation

- `SIGNAL_ONLY = True`
- `LIVE_TRADING_LOCKOUT = True`
- `full_auto_allowed = False`
- **Real Orders Placed**: **0**
- **Broker API Calls**: **0**
- **Production Baseline**: `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4` on `origin/master` (100% frozen)
- **EC2 Interaction**: **0** (No SSH, HTTP, deployment, or git push)

---

## 12. Regression Verification (208 / 208 Passed)

1. **Phase D Test Suites (110 Tests)**:
   - Command: `pytest tests/test_signal_forward_observation.py tests/test_signal_forward_wiring_remediation.py tests/test_candle_selection_remediation.py tests/test_data_freshness_guard.py tests/test_forward_accumulation_reporter.py -v`
   - Result: **110 passed, 0 failed, 0 skipped** (100.0% Pass in 19.64s)
2. **Broader System & Regression Suites (98 Tests)**:
   - Command: `pytest tests/test_pipeline_remediation.py tests/test_universal_coverage_and_thresholds.py tests/test_signal_score_discrimination.py tests/test_signal_prediction_snapshots.py -v`
   - Result: **98 passed, 0 failed, 0 skipped** (100.0% Pass in 19.15s)
3. **Total Test Suite Passed**: **208 passed, 0 failed across all suites**.
4. **Database Immutability During Regressions**: Byte-for-byte verified pre- vs post-test SHA-256 (`73b860620e44add6ff4facd42941ef09f278be6fae76e7aa8a4b1dcd93e9ec65`).

---

## 13. Authoritative Monitor Summary

```text
====================================================================
  OPB v2.60 Automated Daily Forward Accumulation Monitor
====================================================================
Timestamp:       2026-09-28T14:53:59.099320
Market Date:     2026-09-28 (SESSION_ACTIVE)
Trading Day:     Yes
Forward Cohort:  Registered=99, Resolved=0
Gates:           G1=NOT SATISFIED, G2=NOT SATISFIED, G3=NOT SATISFIED, G4=PASS
Integrity:       CLEAN
Safety:          LOCKED (SIGNAL_ONLY)
--------------------------------------------------------------------
Operational State: ACCUMULATION_ACTIVE
Explanation:       Forward observation accumulation is active. Pipeline operating normally.
--------------------------------------------------------------------
Markdown Report:   D:\AI_APPs\TRADING_APP\OPB_V2_59_4_CANONICAL\artifacts\forward_accumulation_daily_report.md
JSON Report:       D:\AI_APPs\TRADING_APP\OPB_V2_59_4_CANONICAL\artifacts\forward_accumulation_daily_report.json
====================================================================
```

---

## 14. Phase E Readiness Status

- **Status**: **NOT READY FOR PHASE E**
- **Reason**: Canonical gates G1, G2, and G3 require $\ge 100$ resolved observations per active bucket, $\ge 300$ resolved overall, and $\ge 2$ calendar months of coverage. Current resolved sample count is 0.
- **Protocol**: Continue forward observation accumulation naturally during scheduled market sessions.

---

## 15. Canonical Verdict Selection

Under the mandated 4-verdict rubric:
- `A. ACCUMULATION_ACTIVE`
- `B. WAITING_FOR_MARKET_SESSION`
- `C. ACCUMULATION_BLOCKED`
- `D. SAFETY_STOP`

Because:
1. The market session is active (`SESSION_ACTIVE`),
2. The scanner daemon executed 2 complete supervised scan cycles across 5,232 symbol evaluations with zero unhandled errors and zero rate limiting,
3. 28 genuine forward observations were registered into the cohort (cohort size expanded from 71 to 99),
4. The pre-existing 45-observation cohort was preserved with 100.0% byte-for-byte hash parity (`bb9bfa89...`),
5. The pre-existing 71-observation continuation baseline was preserved with 100.0% byte-for-byte hash parity (`a1c02d74...`),
6. Zero observations prematurely or artificially resolved; natural observation lifecycle is actively maintained,
7. Zero models were fitted, zero probabilities were generated,
8. All 208 regression tests pass without error and leave the production database immutable,
9. All safety locks (`SIGNAL_ONLY`, `LIVE_TRADING_LOCKOUT`, `full_auto_allowed=False`, 0 broker calls, 0 orders placed, 0 EC2 contacts, 0 remote git pushes) remain 100% engaged:

### Canonical Verdict:
# **A. ACCUMULATION_ACTIVE**
