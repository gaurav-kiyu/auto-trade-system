# OPB PHASE D26-A/B: FINAL PRE-COMMIT DIFF & INTEGRITY AUDIT REPORT

**Governance Authority**: [`OPB-FINAL-PHASE-GOVERNANCE-001`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/.agents/rules/opb-final-phase-governance.md)  
**Execution Timestamp**: `2026-09-30T09:20:00+05:30`  
**Execution Mode**: `READ-ONLY AUDIT — NO COMMIT / NO PUSH / NO EC2`  
**Final Gate Conclusion**: **`D26-A/B PRE-COMMIT AUDIT PASSED — READY FOR HUMAN REVIEW`**

---

## 1. Repository & Git Baseline

- **Repository**: `d:\AI_APPs\TRADING_APP\OPB_V2_59_4_CANONICAL`
- **Branch**: `v2.60-phase-d-candle-selection-remediation`
- **Starting Approved Pre-D26 HEAD**: `2769e6154728b6519c4cfa7d25478f7eb38a6d76`
- **Current HEAD**: `2769e6154728b6519c4cfa7d25478f7eb38a6d76` (`HEAD == origin/v2.60-phase-d-candle-selection-remediation`)
- **Historical Baseline**: `d4271ff`
- **Git Status Summary**:
  - `git diff --check`: Clean (0 whitespace/newline issues)
  - `git diff 2769e6154728b6519c4cfa7d25478f7eb38a6d76..HEAD`: 0 commits ahead (Strict Local Working Tree modifications only)

### File Inventory & Categorization

#### Category A: Actual D26 Implementation (Tracked & Modified)
1. [`core/fno_universe.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/core/fno_universe.py): Taxonomy classification inversion remediation & strict 10-category preservation.
2. [`core/notifications/rich_signal_formatter.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/core/notifications/rich_signal_formatter.py): Truthful index spot directional presentation (Email & Telegram).
3. [`core/all_nse_scanner.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/core/all_nse_scanner.py): Futures quote integration, fail-closed gate (zero cash fallback), price level parity.

#### Category B: D26 Regression Tests (Tracked & Modified / New)
1. [`tests/test_d26_taxonomy_futures_parity.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/tests/test_d26_taxonomy_futures_parity.py): 13 dedicated D26 tests.
2. [`tests/test_post_market_remediation_r1_r4.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/tests/test_post_market_remediation_r1_r4.py): Mock futures price wired into test fixture.
3. [`tests/test_product_integrity_remediation.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/tests/test_product_integrity_remediation.py): Taxonomy assertion updates.
4. [`tests/test_remediation_p1_p2_p3.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/tests/test_remediation_p1_p2_p3.py): Taxonomy assertion updates.
5. [`tests/test_signal_quality_remediation_d20.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/tests/test_signal_quality_remediation_d20.py): Isolated temp_db fixture isolation.

#### Category C: Required Governance & Audit Artifacts (Untracked)
1. [`artifacts/phase_d26_a_b_taxonomy_futures_audit.md`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/artifacts/phase_d26_a_b_taxonomy_futures_audit.md)
2. [`artifacts/phase_d26_a_b_taxonomy_futures_audit.json`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/artifacts/phase_d26_a_b_taxonomy_futures_audit.json)
3. [`artifacts/phase_d26_final_precommit_diff_audit.md`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/artifacts/phase_d26_final_precommit_diff_audit.md)
4. [`artifacts/phase_d26_final_precommit_diff_audit.json`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/artifacts/phase_d26_final_precommit_diff_audit.json)

#### Category D: Pre-existing / Historical Reports & Artifacts (Untracked — MUST NOT BE COMMITTED)
- `OPB_V2594_FINAL_HISTORICAL_TRACEABILITY_CORRECTION_REPORT.md`
- `OPB_V2594_FINAL_MASTER_FORENSIC_REGRESSION_AND_ACCEPTANCE_REPORT.md`
- `OPB_V2594_FINAL_SUCCESS_METRICS_DOCS_RECONCILIATION_REPORT.md`
- `OPB_V2594_PHASE_J_TO_N_PRODUCTION_ACCEPTANCE_REPORT.md`
- Historical phase artifacts `artifacts/phase_d4_*` through `artifacts/phase_d25_*`
- `post_market_remediation_r1_r4_report.md`
- `post_market_remediation_r1_r4_wiring_gate_report.md`
*(Note: These files predate D26; none will be staged or committed).*

---

## 2. D26-A: Taxonomy Purity & Presentation Truth

### 2.1 Exact Precedence Logic in `classify_instrument_market`
```text
1. COMMODITIES      (MCX: or MCX symbols: CRUDEOIL, NATURALGAS, GOLD, etc.)
2. CURRENCIES       (CDS: or CDS pairs: USDINR, EURINR, GBPINR, JPYINR)
3. ETFS_REITS       (BEES, ETF, INVIT, REIT, GOLDSHARE)
4. PENNY_SME        (Series SM, ST, BZ, SME, PENNY, or symbol ends with _SME / -SME)
5. FUTURES          (Ends with FUT / FUTURES, series FUT, itype in FUTIDX / FUTSTK)
6. INDEX_OPTIONS    (FNO_INDICES or starts with Index name + CE/PE or itype OPTIDX)
7. STOCK_OPTIONS    (Genuine stock option derivative: regex ^<UNDERLYING><YY><MMM><STRIKE><CE|PE>$ or itype in OPTSTK/OPT or series OPT)
8. SWING / DELIVERY (Explicit series/itype in SWING, DELIVERY, CNC)
9. LARGE_CAP_EQUITY (Explicit series/mcap LARGE_CAP)
10. MID_SMALL_CAP   (Explicit series/mcap MID_CAP / SMALL_CAP)
11. CASH EQUITIES   (Series EQ / BE or itype CASH / EQUITY):
    ├─ In NIFTY_50_STOCKS: LARGE_CAP_EQUITY
    ├─ In FNO_EQUITY_STOCKS: MID_SMALL_CAP
    └─ Default: EQUITY_SWING_DELIVERY
12. Fallback:       EQUITY_SWING_DELIVERY
```

### 2.2 Canonical Category Count & Zero-New-Category Proof
- **Total Canonical Categories**: Exactly **10**.
- **Search for `EQUITY_INTRADAY`**: Zero runtime occurrences in `core/fno_universe.py`, `core/signals/`, or `system_signals`. (Only exists in legacy quant dictionary weights in `core/quant/factor_cluster_evaluator.py`).
- **No new category created**: `EQUITY_INTRADAY` was **not** created.

### 2.3 Empirical Classification Test Matrix

| Test Case | Symbol | Series | itype | Expected Category | Actual Category | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| 1 | `RELIANCE` | `EQ` | None | `LARGE_CAP_EQUITY` | `LARGE_CAP_EQUITY` | **PASS** |
| 2 | `TCS` | `EQ` | None | `LARGE_CAP_EQUITY` | `LARGE_CAP_EQUITY` | **PASS** |
| 3 | `INFY` | `EQ` | None | `LARGE_CAP_EQUITY` | `LARGE_CAP_EQUITY` | **PASS** |
| 4 | `TATAPOWER` | `EQ` | None | `MID_SMALL_CAP` | `MID_SMALL_CAP` | **PASS** |
| 5 | `IDEA` | `EQ` | None | `MID_SMALL_CAP` | `MID_SMALL_CAP` | **PASS** |
| 6 | `RELIANCE24OCT2900CE` | `OPT` | None | `STOCK_OPTIONS` | `STOCK_OPTIONS` | **PASS** |
| 7 | `TCS24OCT3500PE` | `OPT` | None | `STOCK_OPTIONS` | `STOCK_OPTIONS` | **PASS** |
| 8 | `NIFTY` | `INDEX` | None | `INDEX_OPTIONS` | `INDEX_OPTIONS` | **PASS** |
| 9 | `BANKNIFTY` | `INDEX` | None | `INDEX_OPTIONS` | `INDEX_OPTIONS` | **PASS** |
| 10 | `NIFTY24DEC25000CE` | `OPT` | `OPTIDX` | `INDEX_OPTIONS` | `INDEX_OPTIONS` | **PASS** |
| 11 | `BANKNIFTY24DEC50000PE`| `OPT` | `OPTIDX` | `INDEX_OPTIONS` | `INDEX_OPTIONS` | **PASS** |
| 12 | `RELIANCE26OCTFUT` | `FUT` | `FUTSTK` | `FUTURES` | `FUTURES` | **PASS** |
| 13 | `TRIDENT` (Non-FNO) | `EQ` | `CASH` | `EQUITY_SWING_DELIVERY` | `EQUITY_SWING_DELIVERY` | **PASS** |
| 14 | `RELIANCE` (Swing) | `SWING`| None | `EQUITY_SWING_DELIVERY` | `EQUITY_SWING_DELIVERY` | **PASS** |
| 15 | `RELIANCE` (CNC) | `CNC` | None | `EQUITY_SWING_DELIVERY` | `EQUITY_SWING_DELIVERY` | **PASS** |

### 2.4 Index Presentation Truth Verification
In [`core/notifications/rich_signal_formatter.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/core/notifications/rich_signal_formatter.py):
- **Spot Indices**:
  - `is_option`: `False`
  - `display_title`: `"NIFTY Index Spot Directional"`
  - `subject_instrument`: `"NIFTY (Spot)"`
  - Email Subject: `🟢 NIFTY (Spot) BULLISH (INDEX SPOT DIRECTIONAL) | Entry ₹24,500.00 | ...` (Zero `"BUY CE"` claim)
  - Telegram Message: `🟢 🎯 INDEX SPOT DIRECTIONAL: BULLISH (CALL)` (Zero `"OPTION BUYING"` claim)
- **Option Contracts**:
  - `is_option`: `True`
  - Email Subject: `🟢 NIFTY 24DEC25000CE BUY CE (CALL) | ...`

---

## 3. D26-B: Futures Execution Path & Parity Audit

### 3.1 Exact Downstream Execution Path
```text
parent_signal (ScannedStockSignal from AllNSEScanner.scan_single_stock)
    ↓
_dispatch_futures_alert_if_eligible(parent_signal)
    ↓ [Gate 1: Skip if parent is series FUT]
    ↓ [Gate 2: Skip if not bool(cfg.get("FUTURES_ENABLED", False))]
    ↓ [Gate 3: Verify is_fno_symbol(parent.symbol)]
FuturesContractResolver.get_instance().resolve_current_contract(parent.symbol)
    ↓ [Gate 4: Verify contract exists and contract.active is True]
    ↓ [Gate 5: Verify parent_signal.score >= get_min_score_for_category("FUTURES")]
    ↓ [Gate 6: R2 Cooldown check against self._last_alert_time[fut_symbol]]
    ↓ [Gate 7: Burst rate limit check via self._rate_limit_allows_dispatch()]
    ↓ [Gate 8: Daily signal limit check via self._daily_signal_limit_allows_dispatch()]
resolve_futures_market_price(fut_symbol, broker_adapter=self._broker_adapter)
    ↓ [Gate 9: FAIL-CLOSED PRICE GATE: if fut_price is None or fut_price <= 0]
    │          └─ Log [FUTURES_FEED_UNAVAILABLE], record FILTERED state, return immediately.
    │          └─ ZERO FALLBACK TO CASH SPOT PRICE.
self._last_alert_time[fut_symbol] = now_ts  (Commit cooldown slot only after price verified)
    ↓
fut_signal = ScannedStockSignal(symbol=fut_symbol, series="FUT", price=float(fut_price), ...)
    ↓
calculate_directional_levels(entry_price=float(fut_price), direction=fut_direction)
    ├─ sl_price = round(fut_price * 0.97, 2)
    ├─ t1_price = round(fut_price * 1.04, 2)
    └─ t2_price = round(fut_price * 1.08, 2)
    ↓
resolver.calculate_fair_value(parent.price, contract.expiry_date, actual_futures_price=float(fut_price))
    ├─ fut_features["fair_value"] = theoretical_fair_value
    └─ fut_features["basis"] = basis
    ↓
UserPermissionManager.get_eligible_recipients(category="FUTURES", ...)
    ↓
SignalTracker.get_instance().record_generated_signal({..., price=fut_signal.price, sl=sl_price, t1=t1_price, t2=t2_price})
    ↓
Telegram & Email Dispatch (Formatted with FUTURES BUY/LONG or FUTURES SELL/SHORT)
```

### 3.2 Empirical Fail-Closed Test Suite Results

| Test Scenario | Condition | Result | Cooldown Consumed | Persistence / Dispatch | Status |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **Case A** | Valid Futures quote (`3025.0`) | Accepted | **Yes** | **Yes** (Price = `3025.0`) | **PASS** |
| **Case B** | No Futures quote (`None`) | Filtered (Fail Closed) | **No** | **No** | **PASS** |
| **Case C** | Zero Futures quote (`0.0`) | Filtered (Fail Closed) | **No** | **No** | **PASS** |
| **Case D** | Negative Futures quote (`-10.0`)| Filtered (Fail Closed) | **No** | **No** | **PASS** |
| **Case E** | Resolver exception raised | Filtered (Fail Closed) | **No** | **No** | **PASS** |
| **Case F** | Cash spot exists (`3000.0`), Futures missing | Filtered (No cash fallback) | **No** | **No** | **PASS** |

### 3.3 Target Price Source Verification
- `fut_signal.price` = `float(fut_price)` (Contract LTP: `3025.0`)
- `stop_loss` = `round(3025.0 * 0.97, 2)` = `2934.25`
- `target_1` = `round(3025.0 * 1.04, 2)` = `3146.00`
- `target_2` = `round(3025.0 * 1.08, 2)` = `3267.00`
- **Zero reliance on spot cash price (`3000.0`)**.

### 3.4 Production Configuration Guard
- `core/all_nse_scanner.py` line 1363: `bool(self._cfg.get("FUTURES_ENABLED", False))` strictly defaults to `False`.
- `json/index_config.defaults.json`: `"FUTURES_ENABLED": false`.

---

## 4. Protected Subsystem Audit

| Subsystem | Requirement | Verified State | Status |
| :--- | :--- | :--- | :---: |
| Scoring Weights | No mutation | 0 modifications across evaluators | **PASS** |
| Scoring Thresholds | No mutation | Floor clamps & category thresholds intact | **PASS** |
| ML / Calibration | No mutation | Probability & Brier calibrators untouched | **PASS** |
| Regime Logic | No mutation | 4-regime classification untouched | **PASS** |
| Equity Swing T1 | +4.0% | Strict +4.0% preserved | **PASS** |
| Equity Swing T2 | +8.0% | Strict +8.0% preserved | **PASS** |
| Equity Swing SL | -3.0% | Strict -3.0% preserved | **PASS** |
| Position Sizing | No mutation | Capital allocator & Kelly scaling untouched | **PASS** |
| Broker Routing | Disconnected | No broker calls, disconnected mode intact | **PASS** |
| Order Execution | Blocked | 0 orders placed, live lockout active | **PASS** |
| Auth / Security | No mutation | Token & HMAC validation untouched | **PASS** |
| DB Schema | No mutation | 0 DDL statements executed, schema identical | **PASS** |
| Production Controls | `full_auto_allowed=False` | Unchanged | **PASS** |
| D20-A Options Gate | No mutation | Logic untouched, regression suite passing | **PASS** |
| D20-B Session Dedup | No mutation | Logic untouched, regression suite passing | **PASS** |
| D20-C Production Mode| `OFF` | Unchanged | **PASS** |
| R1 Futures Resolver | No mutation | `FuturesContractResolver` unchanged | **PASS** |
| R3 Reconciliation | No mutation | Post-market tracker unchanged | **PASS** |
| R4 Outcome Evaluator| No mutation | First-touch evaluator unchanged | **PASS** |

---

## 5. Database Safety & Integrity Audit

Independent verification before and after all regression test executions on `db/signals_history.db`:

```text
Database File: db/signals_history.db
Baseline SHA256: f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a
Post-Test SHA256: f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a
SHA256 Match: True (Exact parity)
PRAGMA integrity_check: ok
PRAGMA foreign_key_check: 0 violations
```

### Table Row Counts (Delta = 0 across all 11 tables):
- `system_signals`: 498 ($\Delta$ 0)
- `signal_outcome_events`: 365 ($\Delta$ 0)
- `signal_forward_observations`: 101 ($\Delta$ 0)
- `signal_outcome_measurements`: 101 ($\Delta$ 0)
- `signal_prediction_snapshots`: 101 ($\Delta$ 0)
- `user_deliveries`: 344 ($\Delta$ 0)
- `scan_cycle_metrics`: 38 ($\Delta$ 0)
- `signal_delivery_audit`: 12 ($\Delta$ 0)
- `notification_dead_letter`: 3 ($\Delta$ 0)
- `notification_retry_queue`: 3 ($\Delta$ 0)
- `sqlite_sequence`: 4 ($\Delta$ 0)

---

## 6. Regression Test Results

| Test Suite | Total | Passed | Failed | Skipped | Errors | Duration | Notes |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `tests/test_d26_taxonomy_futures_parity.py` | 13 | 13 | 0 | 0 | 0 | 1.20s | All 13 dedicated D26 parity tests pass |
| `tests/test_signal_quality_remediation_d20.py` | 28 | 28 | 0 | 0 | 0 | 2.19s | D20-A/B gates pass |
| `tests/test_post_market_remediation_r1_r4.py` | 24 | 24 | 0 | 0 | 0 | 1.71s | Post-market reconciliation passes |
| `tests/test_remediation_p1_p2_p3.py` | 28 | 27 | 1 | 0 | 0 | 1.17s | Taxonomy passes (1 pre-existing SVG test fails) |
| `tests/test_product_integrity_remediation.py` | 22 | 21 | 1 | 0 | 0 | 3.54s | Taxonomy passes (1 pre-existing payment test fails) |
| **Total Test Assertions** | **115** | **113** | **2** | **0** | **0** | **9.81s** | **Zero D26-related regressions** |

---

## 7. Safety Invariants Audit

- **Historical DB writes**: `0`
- **Historical rows modified**: `0`
- **Historical rows deleted**: `0`
- **Synthetic data generated**: `0`
- **Broker API calls**: `0`
- **Orders placed**: `0`
- **EC2 modifications**: `0`
- **GitHub pushes**: `0`
- **Production configuration changes**: `0`
- **FUTURES_ENABLED activation**: `0` (False in production)
- **D20-C activation**: `0` (OFF)
- **Phase E activation**: `0` (BLOCKED)
- **Git commits**: `0` (Local working tree only)

---

## 8. Final Gate Decision

Every check specified in the audit mandate has been empirically verified.
- Taxonomy purity is restored (no cash stocks in `STOCK_OPTIONS`).
- 10 canonical categories strictly preserved (zero `EQUITY_INTRADAY`).
- Spot indices presented truthfully as `Index Spot Directional`.
- Futures pricing parity enforced with strict fail-closed gate (zero spot cash fallback).
- Database hash matches baseline byte-for-byte (exact 0 delta across all 11 tables).
- Protected subsystems are 100% untouched.

**GATE CONCLUSION**:
# `D26-A/B PRE-COMMIT AUDIT PASSED — READY FOR HUMAN REVIEW`
