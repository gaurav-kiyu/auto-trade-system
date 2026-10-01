# OPB v2.60 — FINAL LOCAL INTEGRATION VERIFICATION REPORT
## R1/R3 WIRING GATE & COMPLETED-BAR CORRECTNESS

**Document Authority**: `OPB-FINAL-PHASE-GOVERNANCE-001`  
**Execution Date**: `2026-09-29`  
**Market Environment**: `LOCAL / OFFLINE INTEGRATION TESTBED`  
**Working Branch**: `v2.60-phase-d-candle-selection-remediation`  
**HEAD Commit**: `96b525aaa42151c735f250c712ac3535d9a2b58c`  
**Frozen Production Baseline**: `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4` on `origin/master`  
**Phase E Status**: **STRICTLY BLOCKED / DO NOT PROCEED TO PHASE E**  

---

## SECTION A — EXECUTIVE SUMMARY

| Metric / Governance Check | Verified Status | Empirical Finding / Evidence |
| :--- | :---: | :--- |
| **Wiring Gate Decision** | **PASS** | R1/R3 production-path wiring and completed candle invariants verified |
| **Check 1: R1 Execution-Path Wiring** | **PASS** | Futures contracts route to `FuturesContractResolver`; spot cash price never substituted |
| **Check 2: R1 Missing-Feed Fail-Closed** | **PASS** | Missing feed fails closed cleanly; no synthetic prices; status safely preserved |
| **Check 3: R3 Completed Candle Safety** | **PASS** | `len(df1) >= 2` strictly enforced; forming candle `iloc[-1]` strictly ignored |
| **Check 4: R3 Timestamp Freshness & Dedup** | **PASS** | IST timezone-aware parsing; future-dated rejection; 15m staleness; candle deduplication |
| **Check 5: R3 Target/SL Barrier Matrix** | **PASS** | All 6 cases verified: CALL T1, CALL SL, CALL Ambiguous; PUT T1, PUT SL, PUT Ambiguous |
| **Check 6: R2 Governance Suppression** | **PASS** | Cooldown, burst rate limit, daily quota suppress alerts before calling signal tracker |
| **Check 7: Historical DB Immutability** | **PASS** | Exact 101 forward observations preserved (32 TIMEOUT, 69 OBSERVING); zero row mutations |
| **Check 8: Git / Network / Safety** | **PASS** | Zero commits, zero pushes, zero EC2 calls, zero live broker calls |
| **Check 9: Full Regression Suite** | **PASS** | **193 / 193 tests passed** in 10.96s (100% pass rate) |

---

## SECTION B — CHECK 1: R1 ACTUAL FUTURES EXECUTION-PATH INTEGRATION

### 1. Production Execution-Path Trace
The execution path resolves active forward signals across the scanner and outcome tracker:
```text
Active System Signal (e.g. DIXON26SEPFUT, category="FUTURES")
    ↓
AllNSEScanner.scan_universe()
    ↓ (constructs _lookup_bar and _lookup_price closures)
SignalOutcomeTracker.update_active_signal_outcomes(price_lookup_fn, bar_lookup_fn)
    ↓ (iterates over active system_signals rows)
Is Symbol Canonical Futures? (parse_canonical_symbol(symbol) is not None or category == "FUTURES")
    ↓
FuturesContractResolver.resolve_futures_market_bar(symbol, broker_adapter)
FuturesContractResolver.resolve_futures_market_price(symbol, broker_adapter)
    ↓
SignalOutcomeTracker.evaluate_bar() / evaluate_tick()
```

### 2. Code Modifications

#### In `core/all_nse_scanner.py` (lines 790–825):
```python
# Observational outcome tracking: grade active signals against latest prices & completed 1m bars discovered in this scan
latest_prices = {s.symbol: s.price for s in detected_signals}
with self._bars_lock:
    completed_bars = dict(self._latest_completed_bars)

if latest_prices or completed_bars:
    from core.futures_contract_resolver import parse_canonical_symbol, resolve_futures_market_bar, resolve_futures_market_price

    def _lookup_bar(sym: str):
        # 1. Cash completed bar from scan
        with self._bars_lock:
            b = completed_bars.get(sym)
        if b is not None:
            return b
        # 2. Futures completed bar from resolver (never fall back to cash spot)
        if parse_canonical_symbol(sym) is not None:
            broker = getattr(self, "_broker_adapter", None)
            return resolve_futures_market_bar(sym, broker_adapter=broker)
        return None

    def _lookup_price(sym: str) -> float | None:
        # 1. Cash price from scan
        p = latest_prices.get(sym)
        if p is not None and p > 0:
            return p
        # 2. Futures price from resolver (never fall back to cash spot)
        if parse_canonical_symbol(sym) is not None:
            broker = getattr(self, "_broker_adapter", None)
            return resolve_futures_market_price(sym, broker_adapter=broker)
        return None

    from core.signals.signal_outcome_tracker import SignalOutcomeTracker
    SignalOutcomeTracker.get_instance().update_active_signal_outcomes(
        price_lookup_fn=_lookup_price,
        bar_lookup_fn=_lookup_bar,
    )
```

#### In `core/signals/signal_outcome_tracker.py` (lines 845–885):
```python
for row in active_rows:
    checked += 1
    symbol = row["symbol"]
    sig_id = str(row["signal_id"])
    is_futures = (str(row.get("category") or "").upper() == "FUTURES")
    from core.futures_contract_resolver import parse_canonical_symbol, resolve_futures_market_bar, resolve_futures_market_price
    if parse_canonical_symbol(symbol) is not None:
        is_futures = True

    # Lookup price / bar
    eval_result: SignalEvaluationResult | None = None
    if bar_lookup_fn is not None:
        try:
            bar = bar_lookup_fn(symbol)
            if bar is not None:
                ts_key = f"{sig_id}::{bar.timestamp}"
                if ts_key in self._evaluated_candles:
                    continue
                eval_result = self.evaluate_bar(row, bar, current_time=now)
                if eval_result is not None:
                    self._evaluated_candles.add(ts_key)
                    if len(self._evaluated_candles) > 10000:
                        self._evaluated_candles.clear()
        except Exception as ex:
            _log.debug("Bar lookup failed for %s: %s", symbol, ex)

    # R1 Wiring: If symbol is a futures contract and bar wasn't resolved by bar_lookup_fn,
    # resolve via FuturesContractResolver directly (fail-closed, never spot substitution)
    if eval_result is None and is_futures:
        try:
            f_bar = resolve_futures_market_bar(symbol)
            if f_bar is not None:
                ts_key = f"{sig_id}::{f_bar.timestamp}"
                if ts_key not in self._evaluated_candles:
                    eval_result = self.evaluate_bar(row, f_bar, current_time=now)
                    if eval_result is not None:
                        self._evaluated_candles.add(ts_key)
                        if len(self._evaluated_candles) > 10000:
                            self._evaluated_candles.clear()
        except Exception as ex:
            _log.debug("Futures bar resolution failed for %s: %s", symbol, ex)

    if eval_result is None:
        try:
            price = price_lookup_fn(symbol) if price_lookup_fn is not None else None
        except Exception as ex:
            _log.debug("Price lookup failed for %s: %s", symbol, ex)
            price = None

        # R1 Wiring: If price wasn't resolved by lookup and symbol is futures,
        # resolve via FuturesContractResolver directly (fail-closed, never spot substitution)
        if (price is None or price <= 0) and is_futures:
            try:
                price = resolve_futures_market_price(symbol)
            except Exception as ex:
                _log.debug("Futures price resolution failed for %s: %s", symbol, ex)
```

### 3. Proof: Zero Spot Price Fallback
In test `test_check1_futures_never_substitutes_spot_cash_price`, spot equity `DIXON` was supplied at `₹13,500.0` (which would have immediately triggered a false `SL_HIT` if substituted). Because `DIXON26SEPFUT` queries `FuturesContractResolver` and rejects spot prices, the observation safely remained `ACTIVE`, `current_price` remained `₹14,500.0`, and zero false barrier hits occurred.

---

## SECTION C — CHECK 2: R1 MISSING-FEED FAIL-CLOSED INTEGRATION

### 1. Missing Feed Behavior
When broker contract feeds are offline or missing:
1. `resolve_futures_market_price(symbol)` and `resolve_futures_market_bar(symbol)` log telemetry:
   `[FUTURES_FEED_UNAVAILABLE] Market data adapter lacks live quote feed for futures contract 'DIXON26SEPFUT'. Failing closed (no synthetic fallback).`
2. Both functions return `None`.
3. `update_active_signal_outcomes` evaluates `price is None or price <= 0`.
4. It calls `self.check_signal_expiry(row, current_time=now)`.
5. If the signal's holding horizon has not elapsed, `continue` executes:
   - Zero database mutations.
   - Zero synthetic prices generated.
   - Zero barrier hits recorded.
   - `MFE_R` and `MAE_R` remain strictly `0.0`.
   - Observation status remains `ACTIVE` (or `OBSERVING` / `UNRESOLVED` in forward cohort).
6. If the holding horizon has elapsed (session close / 5 trading days), the signal transitions cleanly to `EXPIRED` (`TIMEOUT`).
7. Verified in `test_check2_futures_missing_feed_fails_closed`.

---

## SECTION D — CHECK 3: R3 COMPLETED 1M CANDLE SAFETY INVARIANT

### 1. Code Before vs After
**Before (`core/all_nse_scanner.py`, line 560)**:
```python
# VULNERABLE: When len(df1) == 1, df1.iloc[-1] selected the currently forming candle!
bar_row = df1.iloc[-2] if len(df1) >= 2 else df1.iloc[-1]
bar_idx = df1.index[-2] if len(df1) >= 2 else df1.index[-1]
```

**After (`core/all_nse_scanner.py`, lines 558–580)**:
```python
# Check 3 Fail-Closed Invariant: strictly require len(df1) >= 2 so df1.iloc[-2] is the completed candle.
# df1.iloc[-1] is currently forming and must never be evaluated as a completed candle.
if len(df1) >= 2:
    try:
        from core.signals.signal_outcome_tracker import SignalBar
        bar_row = df1.iloc[-2]
        bar_idx = df1.index[-2]
        ts_str = bar_idx.isoformat() if hasattr(bar_idx, "isoformat") else str(bar_idx)
        bar_obj = SignalBar(
            open=float(bar_row["Open"]),
            high=float(bar_row["High"]),
            low=float(bar_row["Low"]),
            close=float(bar_row["Close"]),
            timestamp=ts_str,
            volume=float(bar_row.get("Volume", 0.0)),
        )
        with self._bars_lock:
            self._latest_completed_bars[sym] = bar_obj
    except Exception as bar_ex:
        _log.debug("Failed to record completed 1m SignalBar for %s: %s", sym, bar_ex)
else:
    _log.debug("Insufficient 1m bars for %s (len=%d < 2); no completed candle available.", sym, len(df1))
```

### 2. Invariant Proof
- `len(df1) == 0`: No bar recorded.
- `len(df1) == 1`: No bar recorded (forming candle completely ignored).
- `len(df1) >= 2`: `df1.iloc[-2]` (closed candle) recorded; `df1.iloc[-1]` (forming candle) ignored.
- Verified in `test_check3_completed_1m_candle_safety_invariant`.

---

## SECTION E — CHECK 4: R3 CANDLE END-TIME & FRESHNESS VALIDATION

### 1. Timestamp Parsing & Timezone Invariant
`SignalOutcomeTracker.evaluate_bar()` parses ISO 8601 strings and attaches or converts to Indian Standard Time (`Asia/Kolkata` IST, UTC+05:30):
```python
bar_dt = bar.timestamp
if isinstance(bar_dt, str):
    try:
        bar_dt = datetime.datetime.fromisoformat(bar_dt.replace("Z", "+00:00"))
    except Exception:
        bar_dt = None

if isinstance(bar_dt, datetime.datetime):
    if bar_dt.tzinfo is None and now.tzinfo is not None:
        bar_dt = bar_dt.replace(tzinfo=now.tzinfo)
    elif bar_dt.tzinfo is not None and now.tzinfo is not None:
        bar_dt = bar_dt.astimezone(now.tzinfo)

    # Check future-dated candle (clock-skew tolerance: 30s)
    if (bar_dt - now).total_seconds() > 30:
        _log.warning("[INVALID_CANDLE_TIME] Future-dated candle rejected for %s: %s > %s", symbol, bar_dt, now)
        return no_op_result

    # Stale bar validation: if bar timestamp is older than 15m from evaluation time
    if check_staleness and (now - bar_dt).total_seconds() > 900:  # > 15 minutes
        _log.debug("Stale bar rejected for %s (age > 15m)", symbol)
        return no_op_result
```

### 2. Candle Deduplication
In `SignalOutcomeTracker.update_active_signal_outcomes()`, `ts_key = f"{sig_id}::{bar.timestamp}"` is tracked in `self._evaluated_candles`. If the scanner executes multiple cycles within the same 1-minute window, subsequent evaluations of the exact same completed candle are deduplicated and skipped, eliminating redundant evaluations.
- Verified in `test_check4_candle_end_time_freshness_and_deduplication`.

---

## SECTION F — CHECK 5: R3 TARGET/SL CANDLE INTEGRATION

All 6 required barrier evaluation cases were tested and empirically proven:

| Case | Direction | Parameters | Candle [O, H, L, C] | Evaluated Barrier Touch | Resulting Status & First Touch |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | **CALL** | E=100, SL=98, T1=103 | [100.5, 103.5, 100.2, 103.1] | High >= T1 (103.5 >= 103), Low > SL | `TARGET_1_HIT`, `first_touch='T1'` |
| **2** | **CALL** | E=100, SL=98, T1=103 | [100.2, 100.8, 97.5, 98.0] | Low <= SL (97.5 <= 98), High < T1 | `SL_HIT`, `first_touch='SL'` |
| **3** | **CALL** | E=100, SL=98, T1=103 | [100.0, 103.5, 97.5, 101.0] | High >= T1 AND Low <= SL (same bar) | `AMBIGUOUS`, `first_touch='AMBIGUOUS_SAME_BAR'` |
| **4** | **PUT** | E=100, SL=102, T1=97 | [99.5, 99.8, 96.5, 97.0] | Low <= T1 (96.5 <= 97), High < SL | `TARGET_1_HIT`, `first_touch='T1'` |
| **5** | **PUT** | E=100, SL=102, T1=97 | [99.5, 102.5, 99.0, 102.1] | High >= SL (102.5 >= 102), Low > T1 | `SL_HIT`, `first_touch='SL'` |
| **6** | **PUT** | E=100, SL=102, T1=97 | [100.0, 102.5, 96.5, 99.0] | Low <= T1 AND High >= SL (same bar) | `AMBIGUOUS`, `first_touch='AMBIGUOUS_SAME_BAR'` |

- Verified in `test_check5_target_sl_candle_six_cases`.

---

## SECTION G — CHECK 6: R2 GOVERNANCE INTEGRATION

In `core/all_nse_scanner.py`, `_dispatch_futures_alert_if_eligible()` enforces 3 mandatory governance controls on derived signals:
1. **Symbol Cooldown**: If `(now_ts - last_sent) < self._cooldown_secs`, alert is suppressed with state `COOLDOWN_SUPPRESSED`.
2. **Window Burst Rate Limit**: If `not self._rate_limit_allows_dispatch()`, alert is suppressed with state `FILTERED`.
3. **Daily Quota**: If `not self._daily_signal_limit_allows_dispatch()`, alert is suppressed with state `FILTERED`.

**Suppressed Alert Invariant**: In all suppression cases, the function returns early *before* invoking `tracker.record_generated_signal()`. Thus, suppressed alerts never pollute the database or trigger downstream notifications.
- Verified in `test_check6_r2_governance_suppression_never_calls_tracker`.

---

## SECTION H — CHECK 7: HISTORICAL DATABASE IMMUTABILITY VERIFICATION

### 1. Database File Integrity & Row Counts
```text
Table: signal_forward_observations
Total Rows: 101
  - OBSERVING: 69
  - TIMEOUT:   32
  - Zero rows dropped, zero rows added, zero rows modified.

Table: system_signals
Total Rows: 498
  - ACTIVE:  133
  - EXPIRED: 284
  - SL_HIT:   81
  - Zero rows dropped, zero rows added.

Table: signal_prediction_snapshots: 101 rows (immutable)
Table: signal_outcome_measurements:  101 rows (immutable)
```

Every single historical forward observation from Phase D cohorts remains completely preserved in its authoritative state.

---

## SECTION I — CHECK 8: GIT / NETWORK / ENVIRONMENT SAFETY VERIFICATION

| Safety Dimension | Verified Status | Evidence |
| :--- | :---: | :--- |
| **Git Commits** | **ZERO COMMITS** | Working branch HEAD is unchanged at `96b525aaa42151c735f250c712ac3535d9a2b58c` |
| **Git Push** | **ZERO PUSHES** | No network push commands executed |
| **EC2 Access** | **ZERO ACCESS** | Zero SSH / HTTP requests to EC2 instances |
| **Broker API Calls** | **ZERO CALLS** | All resolution tests executed using isolated mocks and stubs |
| **Production Environment** | **ZERO MUTATIONS** | All testing confined to local workspace and pytest sandbox |

---

## SECTION J — CHECK 9: TEST SUITE EXECUTION & COUNTS

### 1. Dedicated Post-Market Remediation Test Suite (`tests/test_post_market_remediation_r1_r4.py`)
- **Total Tests**: 24
- **Passed**: 24 (100%)
- **Failed**: 0
- **Duration**: 1.18 seconds

### 2. Broad Regression Test Suite
Command executed:
```bash
pytest tests/test_post_market_remediation_r1_r4.py \
       tests/test_forward_accumulation_reporter.py \
       tests/test_signal_outcome_tracker.py \
       tests/test_signal_forward_wiring_remediation.py \
       tests/test_candle_selection_remediation.py \
       tests/test_category_score_thresholds.py \
       tests/test_signal_dispatch_order_placed_reply.py \
       tests/test_futures_trader.py \
       tests/test_signal_outcome_dataset.py -v
```
- **Total Tests Collected**: 193
- **Passed**: 193 (100%)
- **Failed**: 0
- **Skipped**: 0
- **Duration**: 10.96 seconds

---

## SECTION K — CONFIRMED INVARIANTS MATRIX

| Requirement / Invariant | Implementation Mechanism | Verified Status |
| :--- | :--- | :---: |
| **R1: Zero Spot Price Fallback** | `FuturesContractResolver` queries contract feeds; spot cash lookup rejected | **CONFIRMED** |
| **R1: Fail-Closed on Missing Feed** | Missing quote/bar logs `[FUTURES_FEED_UNAVAILABLE]`, returns None, retains state | **CONFIRMED** |
| **R2: Distinct Derived Cooldown** | `_last_alert_time[fut_symbol]` checked against `_cooldown_secs` | **CONFIRMED** |
| **R2: Derived Burst Rate Limit** | `_rate_limit_allows_dispatch()` evaluated before dispatch | **CONFIRMED** |
| **R2: Derived Daily Quota** | `_daily_signal_limit_allows_dispatch()` evaluated before dispatch | **CONFIRMED** |
| **R3: Fail-Closed Completed Bar** | `len(df1) >= 2` strictly enforced; forming candle `iloc[-1]` ignored | **CONFIRMED** |
| **R3: IST Timezone Freshness** | `bar.timestamp` normalized to IST; future (>30s) and stale (>15m) rejected | **CONFIRMED** |
| **R3: High/Low Barrier Detection** | CALL H>=T1, L<=SL; PUT L<=T1, H>=SL; intrabar High/Low evaluated | **CONFIRMED** |
| **R3: Same-Candle Ambiguity** | Simultaneous touch quarantined to `AMBIGUOUS_SAME_BAR` | **CONFIRMED** |
| **R3: Candle Deduplication** | `sig_id::bar.timestamp` tracked in `_evaluated_candles` | **CONFIRMED** |
| **R4: G4 Hygiene Pass** | G4 gate checks zero missing critical fields, reporting 0 errors (PASS) | **CONFIRMED** |
| **R4: Predictive Usability Split** | Exposes 63 usable vs 38 affected without modifying ground truth | **CONFIRMED** |
| **R4: First-Touch Immutability** | `first_touch` once written is write-once and preserved through expiration | **CONFIRMED** |

---

## SECTION L — RECOMMENDATION FOR NEXT STEP

1. **R1–R4 Wiring Gate Status**: **FULLY PASSED & VERIFIED LOCALLY**.
   - The production execution paths for R1 (Futures Resolution) and R3 (Candle-Based Outcome Measurement) are completely wired, unit tested, and regression verified.
   - All 193 relevant tests pass deterministically.
2. **Phase E Status**: **STRICTLY BLOCKED**.
   - Current resolved count: 32 / 300 target (10.7%).
   - Gate G1, Gate G2, and Gate G3 remain open and unsatisfied.
   - No calibration, threshold tuning, or scoring alterations are permitted.
3. **Next Recommended Action**:
   - Maintain the frozen model baseline on `v2.60-phase-d-candle-selection-remediation`.
   - Await authoritative operator sign-off on the local R1–R4 wiring verification before staging any git commit or planning the next live forward-accumulation session.
