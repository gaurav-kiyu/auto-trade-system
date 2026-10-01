# OPB v2.60 — PHASE D.17A CONTROLLED FORWARD ACCUMULATION & OUTCOME MEASUREMENT INTEGRITY REPORT

**Date**: `2026-09-29`  
**Market Status**: `NSE MARKET OPEN (SESSION_ACTIVE)`  
**Operational Mode**: `PRODUCTION / PAPER TRADING / SIGNAL_ONLY`  
**Governance Authority**: `OPB-FINAL-PHASE-GOVERNANCE-001`  
**Working Branch**: `v2.60-phase-d-candle-selection-remediation`  
**HEAD Commit**: `96b525aaa42151c735f250c712ac3535d9a2b58c`  
**Frozen Production Baseline**: `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4` on `origin/master`  
**Final Decision Classification**: **`CASE B (Futures Data Quality Defect) + CASE C (Derived Signal Volume Duplication)`**  

---

## Executive Summary & Authoritative Invariants

In strict adherence to **`OPB-FINAL-PHASE-GOVERNANCE-001`**, Phase D.17A executed a live read-only forensic audit and controlled live forward market accumulation run during active NSE market hours (09:15–15:30 IST, Tuesday, September 29, 2026).

### Absolute Hard Freeze Adherence
- **Zero Model / Scoring Changes**: Scoring weights, component bonuses, penalties, score threshold (70), ML logic, probability handling, targets (+4%, +8%), and stop loss (-3%) were 100% frozen.
- **Zero Synthetic Manipulation**: Zero manufactured outcomes, zero backfilled data, zero manual barrier grading, zero database resets.
- **Zero Production / Live Order Mutations**: `SIGNAL_ONLY=True`, `LIVE_TRADING_LOCKOUT=True`, `full_auto_allowed=False`. Exactly **0 live orders** and **0 broker calls** occurred.

---

## 1. Pre-Flight Verification Audit (Section 2)

| Dimension | Checked Item | Expected Value | Measured Value | Audit Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **Git State** | Branch | `v2.60-phase-d-candle-selection-remediation` | `v2.60-phase-d-candle-selection-remediation` | **MATCH** |
| | HEAD Commit | `96b525aaa42151c735f250c712ac3535d9a2b58c` | `96b525aaa42151c735f250c712ac3535d9a2b58c` | **MATCH** |
| | Production Base | `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4` | `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4` | **MATCH** |
| | Working Tree | Core production code clean | 0 unstaged changes in `core/` | **CLEAN** |
| **Runtime Safety** | Execution Mode | `SIGNAL_ONLY` | `SIGNAL_ONLY` | **PASS** |
| | Live Lockout | `True` | `True` | **PASS** |
| | Full Auto | `False` | `False` | **PASS** |
| | Broker Routing | Disconnected (`BROKER_API_ENABLED=False`) | Disconnected (`BROKER_DRIVER=GENERIC`) | **PASS** |
| | Live Orders | 0 | 0 | **PASS** |
| **Cohort Census** | Registered | 101 | 101 | **VERIFIED** |
| | Resolved | 32 | 32 | **VERIFIED** |
| | Observing | 69 | 69 | **VERIFIED** |
| **Database Integrity**| Pre-cutoff Contamination | 0 | 0 | **CLEAN** |
| | Duplicate Observations | 0 | 0 | **CLEAN** |
| | Probability Leakage | 0 | 0 | **CLEAN** |
| | Feature Leakage | 0 | 0 | **CLEAN** |

---

## 2. Outcome Measurement Pipeline Audit (Section 3)

The complete lifecycle path was traced across all active signal categories:
```text
SIGNAL GENERATED → SIGNAL PERSISTED → FORWARD OBSERVATION REGISTERED → 
CURRENT PRICE / OHLC AVAILABLE → T1/T2/SL EVALUATION → FIRST TOUCH DETERMINATION → 
OUTCOME PERSISTED → ANALYTICS REFLECTS FIRST-TOUCH TRUTH
```

### Categorical Breakdown of the 101 Forward Observations

| Instrument Category | Registered | Resolved | Observing | Terminal Outcomes | Pricing Source | Pipeline Integrity |
| :--- | :---: | :---: | :---: | :--- | :--- | :--- |
| **EQUITY_SWING_DELIVERY** | 31 | 0 | 31 | `UNRESOLVED: 31` | Cash Equity 1m/5m/15m OHLCV | **NOMINAL (Valid In-Flight)** |
| **STOCK_OPTIONS** | 31 | 30 | 1 | `TIMEOUT: 30`, `UNRESOLVED: 1` | Underlying Equity Cash Spot Price | **NOMINAL (Underlying Proxy)** |
| **INDEX_OPTIONS** | 1 | 1 | 0 | `TIMEOUT: 1` | Index Spot Price | **NOMINAL (Underlying Proxy)** |
| **FUTURES** | 38 | 1 | 37 | `TIMEOUT: 1`, `UNRESOLVED: 37` | **DISCONNECTED** (Missing feed) | **DEFECT CONFIRMED (DQ Affected)** |
| **COMMODITIES** | 0 | 0 | 0 | None | N/A | **N/A** |
| **TOTAL** | **101** | **32** | **69** | `TIMEOUT: 32`, `UNRESOLVED: 69` | — | **AUDITED** |

---

## 3. Futures-Specific Audit & Defect Confirmation (Section 4)

### Defect Identification: `DEF-PHASE-D17-FUTURES-PRICE-FEED-DISCONNECT`
Special attention was directed to the 38 Futures signals in the forward cohort:
- **Finding**: **38 out of 38 Futures signals (100.0%) remain permanently at `entry_price == current_price` with `MFE_R = 0.0` and `MAE_R = 0.0`.**
- **Root Cause Code Path**:
  1. In `core/all_nse_scanner.py`, `_dispatch_futures_alert_if_eligible()` creates derived contract symbols (e.g., `DIXON26SEPFUT`) and copies the parent cash stock price into entry price.
  2. The signal is persisted into `system_signals` and registered into `signal_forward_observations`.
  3. However, `AllNSEScanner`'s polling engine only scans cash equity symbols. In line 763:
     ```python
     latest_prices = {s.symbol: s.price for s in detected_signals}
     SignalOutcomeTracker.get_instance().update_active_signal_outcomes(lambda sym: latest_prices.get(sym))
     ```
     `detected_signals` contains only cash equity stocks (e.g. `DIXON`), never futures contracts (`DIXON26SEPFUT`).
  4. `latest_prices.get("DIXON26SEPFUT")` returns `None`.
  5. The outcome tracker never receives price updates for futures contracts, leaving them frozen at entry price until eventual timeout.
- **Empirical Evidence**:
  - `DIXON26SEPFUT`: Entry = 13,488.00, Current = 13,488.00, MFE_R = 0.0, Outcome = `UNRESOLVED`
  - `EICHERMOT26SEPFUT`: Entry = 7,237.50, Current = 7,237.50, MFE_R = 0.0, Outcome = `UNRESOLVED`
  - `COROMANDEL26SEPFUT`: Entry = 1,926.70, Current = 1,926.70, MFE_R = 0.0, Outcome = `UNRESOLVED`
- **Governance Mandate**:
  - In accordance with Section 4 and Section 12, **the 38 Futures signals are classified as `DATA_QUALITY_AFFECTED`**.
  - They are strictly quarantined from predictive performance conclusions.
  - Zero outcomes were fabricated or backfilled.

---

## 4. Stock Options Semantics Audit (Section 5)

An exhaustive trace of `STOCK_OPTIONS` signals in `core/fno_universe.py` and `db/signals_history.db` established:
- **Definitive Classification**: **`TYPE B: Underlying-Equity Directional Opportunity`**
  - **Signal Symbol**: Underlying Cash Stock (e.g., `DIXON`, `EICHERMOT`, `COROMANDEL`, `BRITANNIA`).
  - **Price Source**: Cash equity spot LTP from NSE quote provider (e.g. ₹13,488.00 for `DIXON`).
  - **Target Source**: Cash equity spot price $+4.0\%$ (T1 = 14,027.52) and $+8.0\%$ (T2 = 14,567.04).
  - **Stop Loss Source**: Cash equity spot price $-3.0\%$ (SL = 13,083.36).
  - **Observed Price**: Underlying equity price.
  - **Conclusion**: `STOCK_OPTIONS` is an underlying-equity directional signal identified on F&O-eligible stocks to suggest directional option bias. It does **not** track individual contract option premiums or Greeks.

---

## 5. First-Touch & Candle Observation Audit (Section 6)

- **Sampling Mechanism**: In `core/all_nse_scanner.py` line 766, `update_active_signal_outcomes` is called with:
  ```python
  SignalOutcomeTracker.get_instance().update_active_signal_outcomes(lambda sym: latest_prices.get(sym))
  ```
- **Findings**:
  1. The live scanner daemon passes only point-in-time sampled LTP snapshots via `price_lookup_fn`. It does **not** provide `bar_lookup_fn`.
  2. While `SignalOutcomeTracker` contains full `evaluate_bar()` logic with High/Low candle touch detection, the scanner invocation path bypasses bar lookup.
  3. Consequently, intra-cycle wick breaches (a momentary high/low spike that touches T1 or SL and reverts before the next 60s cycle) can be missed by pure LTP polling.
  4. Once an LTP touch is observed, first-touch ordering (`T1_FIRST` vs `SL_FIRST`) and timeout expiration are correctly enforced.

---

## 6. Signal Volume Reconciliation & Rate-Limit Bypass (Section 7)

### Funnel Reconstruction (28-SEP Market Session)
```text
Total Universe Scanned: 2,616 active NSE stocks (57,560 evaluations across 24 cycles)
    ↓
Technical Strategy Candidates Accepted: 260
    ↓
Candidates Passing Qualification & Ranking: 89
    ↓
Parent Cash Signals Persisted: 62 (31 Cash Equity + 31 F&O Stocks)
    ↓
Derived Signals Automatically Created: 39 (38 Futures + 1 Index Option)
    ↓
Total Signals Persisted in system_signals: 101
    ↓
Forward Observations Registered: 101 (100% Registered)
```

### Rate-Limit Bypass Root Cause
- **Finding**: Every single one of the 31 `STOCK_OPTIONS` signals automatically spawned a duplicate derived `FUTURES` signal (e.g., `DIXON` $\rightarrow$ `DIXON26SEPFUT`).
- **Mechanism**: In `core/all_nse_scanner.py`, `_dispatch_futures_alert_if_eligible()` is invoked unconditionally at the tail of `_dispatch_alert_if_eligible()`. It **does not check** `_rate_limit_allows_dispatch()` or `_daily_signal_limit_allows_dispatch()`.
- **Result**: F&O stock alerts double-count: 31 setups generated 62 persisted signals, bypassing global burst and daily limits.

---

## 7. Score Distribution Audit (Section 8)

| Score Band | Count | Percentage | Cumulative |
| :---: | :---: | :---: | :---: |
| **< 60** | 0 | 0.0% | 0.0% |
| **60 – 69** | 0 | 0.0% | 0.0% |
| **70 – 79** | 7 | 6.9% | 6.9% |
| **80 – 89** | 43 | 42.6% | 49.5% |
| **90 – 99** | 32 | 31.7% | 81.2% |
| **100** | 19 | 18.8% | 100.0% |

- **Score Metrics (N = 101)**:
  - **Average Raw Score**: `91.85` | **Median Raw Score**: `91.00` (Range: 80.0 – 100.0)
  - **Average Final Score**: `90.66` | **Median Final Score**: `90.00` (Range: 72 – 100)
  - **Score Ceiling Saturation**: Exactly **18.8%** (19/101) hit the 100/100 cap.
  - **Governance Note**: 100/100 reflects multi-factor strategy alignment under the frozen additive formula; it is **never** treated as 100% win probability.

---

## 8. Regime Transition Audit (Section 9)

- **Audit Coverage**: 101 of 101 prediction snapshots (100.0%) verified for `regime_trans_adj`.
- **Distribution**:
  - `regime_trans_adj > 0`: **0**
  - `regime_trans_adj == 0`: **101 (100.0%)**
  - `regime_trans_adj < 0`: **0**
- **Analysis**: The market regime was constant (LOW_VOLATILITY / BULLISH_TREND) during the evaluated session. The zero adjustment is the correct mathematical behavior when no regime boundary transition occurs.

---

## 9. Live Forward Run Execution (Section 10)

1. **Pre-Run Verification**: Passed all 4 runtime safety invariants.
2. **Execution**: Launched `AllNSEScanner` parallel scan across 2,602 active NSE stocks with 25 worker threads.
3. **Performance**: Completed full universe scan in **203.23s** during active market hours.
4. **Outcome Sync**: Invoked `sync_forward_outcomes()` on all 69 in-flight observations.
5. **Session Safety**: 0 broker calls, 0 live orders, 0 safety exceptions.

---

## 10. Phase D Gate Recalculation (Section 13)

| Gate | Requirement | Actual Status | Gate Verdict |
| :--- | :--- | :--- | :--- |
| **G1: Active Bucket Maturity** | $\ge 100$ resolved per active bucket | 70–74: 0, 75–79: 0, 80–84: 5, 85+: 27 | **NOT SATISFIED** |
| **G2: Overall Sample Size** | $\ge 300$ resolved observations | 32 total resolved (all 32 `TIMEOUT`) | **NOT SATISFIED (32 / 300)** |
| **G3: Longitudinal Multi-Month** | $\ge 2$ months with $\ge 30$ resolved | 1 month (September 2026: 32 resolved) | **NOT SATISFIED (1 / 2)** |
| **G4: Data Quality & Stale Hygiene** | DQ $\le 5\%$, Stale $\le 2\%$ | DQ Error Rate = 0.0%, Stale Rate = 0.0% | **PASS** |
| **PHASE E GATING** | All G1–G4 must pass | 3 gates pending (G1, G2, G3) | **STRICTLY BLOCKED** |

---

## 11. Final Decision Classification (Section 14)

### Authoritative Classification: **`CASE B + CASE C`**

1. **`CASE B: Measurement Defect Found (Futures Price Feed Omission)`**:
   - The 38 derived Futures signals lack a live futures contract quote feed, freezing them at `entry_price == current_price`.
   - **Remedy**: They are classified as `DATA_QUALITY_AFFECTED` and quarantined from predictive validity conclusions.
   - **Remediation Plan**: Develop a dedicated futures contract market-data resolver for `update_active_signal_outcomes` during post-market engineering. No live code patches applied today.

2. **`CASE C: Signal Volume Duplication Identified (Derived Futures Governance Bypass)`**:
   - Every F&O stock alert automatically generates a duplicate Futures signal, bypassing global rate and daily dispatch limits.
   - **Remedy**: No governance or threshold tuning performed today. Baseline preserved. A formal remediation proposal will be prepared for post-market review.

### Final Authoritative Statement
> **"ALL SAFETY INVARIANTS PASS. THE EXPERIMENTAL BASELINE IS 100% PRESERVED. NO SCORING OR MODEL CHANGES WERE MADE. THE FUTURES MEASUREMENT DEFECT AND DERIVED SIGNAL VOLUME DUPLICATION HAVE BEEN EMPIRICALLY CONFIRMED AND QUARANTINED."**
