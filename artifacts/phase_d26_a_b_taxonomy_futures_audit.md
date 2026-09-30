# OPB PHASE D26-A + D26-B: TAXONOMY PURITY & FUTURES CONTRACT-PARITY AUDIT REPORT

**Governance Authority**: [`OPB-FINAL-PHASE-GOVERNANCE-001`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/.agents/rules/opb-final-phase-governance.md)  
**Execution Timestamp**: `2026-09-30T01:45:00+05:30`  
**Git Branch**: `v2.60-phase-d-candle-selection-remediation`  
**Git HEAD Approved**: `2769e6154728b6519c4cfa7d25478f7eb38a6d76`  
**Baseline**: `d4271...`  
**Operational Status**: `PRODUCTION / PAPER / SIGNAL_ONLY`  
**Safety Invariants**:
- `full_auto_allowed`: `False`
- `broker_routing`: `DISCONNECTED`
- `LIVE_TRADING_LOCKOUT`: `True`
- `orders`: `0`
- `D20-C`: `OFF`
- `Phase E`: `STRICTLY BLOCKED`
- `FUTURES_ENABLED`: `False` (Production fallback)

---

## 1. Executive Summary

Phase D26 executes the dual remediation required to restore canonical taxonomy purity and contract-level pricing truth:
1. **D26-A (Taxonomy Purity & Presentation Truth)**:
   - Eliminated the critical classification inversion in [`core/fno_universe.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/core/fno_universe.py) where 99 F&O-eligible cash equities were erroneously classified as `STOCK_OPTIONS`.
   - Reclassified cash equities strictly into existing canonical categories (`LARGE_CAP_EQUITY` for NIFTY 50 blue chips, `MID_SMALL_CAP` for F&O equities outside NIFTY 50, and `EQUITY_SWING_DELIVERY` for non-F&O delivery swing).
   - Preserved exactly the 10 canonical categories without creating synthetic or non-standard categories.
   - Restored genuine stock options (`RELIANCE24OCT2900CE`, `OPTSTK`) to `STOCK_OPTIONS`.
   - Remediated presentation truth in [`core/notifications/rich_signal_formatter.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/core/notifications/rich_signal_formatter.py) so spot index directional signals (`NIFTY`, `BANKNIFTY`) are accurately labeled `"Index Spot Directional"` and `"BULLISH (INDEX SPOT DIRECTIONAL)"` rather than misrepresenting them as derivative option buying (`"BUY CE"`).
2. **D26-B (Futures Contract Parity Remediation)**:
   - Remediated [`core/all_nse_scanner.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/core/all_nse_scanner.py) `_dispatch_futures_alert_if_eligible` to wire live market quote resolution via `resolve_futures_market_price(contract.canonical_symbol, broker_adapter=getattr(self, "_broker_adapter", None))`.
   - Implemented a strict **Fail-Closed Invariant**: if the live futures contract quote is unavailable or non-positive, evaluation logs `[FUTURES_FEED_UNAVAILABLE]` and terminates immediately. Cash spot price is **never** substituted.
   - Wired directional levels (Stop Loss, Target 1, Target 2) to derive strictly from actual `fut_price`.
   - Safely isolated theoretical fair value (`cost-of-carry`) and basis calculations from actual price, preventing runtime type errors.
   - Enforced R2 cooldown and daily signal rate limits prior to pricing and dispatch.
   - Set `FUTURES_ENABLED` fallback strictly to `False`.

---

## 2. D26-A: Taxonomy Purity & Presentation Truth Analysis

### 2.1 Root Cause of Historical Misclassification
In `core/fno_universe.py` (`classify_instrument_market`), the code previously evaluated:
```python
if clean_sym in FNO_EQUITY_STOCKS or itype_up in ("OPTSTK", "STOCK_OPTIONS"):
    return "STOCK_OPTIONS"
```
Because `FNO_EQUITY_STOCKS` contains the ~180 underlying cash equity tickers (e.g. `RELIANCE`, `INFY`, `TCS`), any cash stock in this set was labeled `STOCK_OPTIONS`. Meanwhile, actual option contracts like `RELIANCE24OCT2900CE` fell through to `EQUITY_SWING_DELIVERY`.

In the production database (`db/signals_history.db`), this caused 99 cash stock signals to be recorded as `STOCK_OPTIONS`. Because `SignalOutcomeTracker` treats `STOCK_OPTIONS` as intraday (`is_intraday=True`), 96 of these 99 signals (96.97%) were marked as `TIMEOUT` at the 15:30 IST market close, destroying holding period integrity and corrupting historical metrics.

### 2.2 Canonical Classification Remediation Matrix

| Symbol | Series | Instrument Type | Pre-D26 Category | Post-D26 Canonical Category | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `RELIANCE` | `EQ` | `CASH` / None | `STOCK_OPTIONS` (Bug) | **`LARGE_CAP_EQUITY`** | NIFTY 50 Blue Chip Cash Equity |
| `TCS` | `EQ` | `CASH` / None | `STOCK_OPTIONS` (Bug) | **`LARGE_CAP_EQUITY`** | NIFTY 50 Blue Chip Cash Equity |
| `INFY` | `EQ` | `CASH` / None | `STOCK_OPTIONS` (Bug) | **`LARGE_CAP_EQUITY`** | NIFTY 50 Blue Chip Cash Equity |
| `TATAPOWER` | `EQ` | `CASH` / None | `STOCK_OPTIONS` (Bug) | **`MID_SMALL_CAP`** | F&O Equity Stock outside NIFTY 50 |
| `IDEA` | `EQ` | `CASH` / None | `STOCK_OPTIONS` (Bug) | **`MID_SMALL_CAP`** | F&O Equity Stock outside NIFTY 50 |
| `RELIANCE24OCT2900CE` | `OPT` | `OPTSTK` / None | `EQUITY_SWING_DELIVERY` | **`STOCK_OPTIONS`** | Genuine stock option derivative contract |
| `TCS24OCT3500PE` | `OPT` | `OPTSTK` / None | `EQUITY_SWING_DELIVERY` | **`STOCK_OPTIONS`** | Genuine stock option derivative contract |
| `NIFTY` | None | `INDEX` / None | `INDEX_OPTIONS` | **`INDEX_OPTIONS`** | Canonical index spot (Truthful presentation) |
| `BANKNIFTY` | None | `INDEX` / None | `INDEX_OPTIONS` | **`INDEX_OPTIONS`** | Canonical index spot (Truthful presentation) |
| `NIFTY24DEC25000CE` | `OPT` | `OPTIDX` | `INDEX_OPTIONS` | **`INDEX_OPTIONS`** | Canonical index option contract |
| `RELIANCE26OCTFUT` | `FUT` | `FUTSTK` | `FUTURES` | **`FUTURES`** | Canonical stock futures contract |
| `ZOMATO` | `EQ` | `CASH` / None | `EQUITY_SWING_DELIVERY` | **`EQUITY_SWING_DELIVERY`** | Non-F&O cash equity swing |

### 2.3 Presentation Truth Remediation
In [`core/notifications/rich_signal_formatter.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/core/notifications/rich_signal_formatter.py):
- **Email Subject**: Spot index signals under `INDEX_OPTIONS` format as:
  - `🟢 BULLISH (INDEX SPOT DIRECTIONAL)` (for CALL/BUY)
  - `🔴 BEARISH (INDEX SPOT DIRECTIONAL)` (for PUT/SELL)
- **Telegram Message**: Spot index signals format as:
  - `🟢 🎯 INDEX SPOT DIRECTIONAL: BULLISH (CALL)`
  - `🔴 🎯 INDEX SPOT DIRECTIONAL: BEARISH (PUT)`
- **Symbol Descriptor**: `format_human_friendly_symbol` returns `is_option: False` and `display_title: "<SYMBOL> Index Spot Directional"` for spot indices.

---

## 3. D26-B: Futures Contract Parity Remediation Analysis

### 3.1 Defect in Prior Implementation
`AllNSEScanner._dispatch_futures_alert_if_eligible` previously set:
```python
fut_signal.price = parent_signal.price  # Spot cash price!
sl_price, t1_price, t2_price = calculate_directional_levels(entry_price=parent_signal.price, ...)
```
This substituted the cash equity price for the derivative futures contract, completely disregarding premium, basis, cost-of-carry, and contract-specific quote feeds.

### 3.2 Implemented Parity & Fail-Closed Architecture
1. **Quote Resolution**:
   - Invokes `resolve_futures_market_price(contract.canonical_symbol, broker_adapter=getattr(self, "_broker_adapter", None))`.
2. **Fail-Closed Invariant**:
   - If `fut_price is None or fut_price <= 0`:
     - Emits warning: `[FUTURES_FEED_UNAVAILABLE] Live futures quote unavailable for contract '<FUT_SYM>'. Failing closed (no spot cash fallback).`
     - Records evaluation state: `FILTERED` with reason `"Futures feed unavailable (fail closed - no cash fallback)"`.
     - Exits immediately (`return`). Zero fallback to spot cash price.
3. **Price Level Parity**:
   - Sets `fut_signal.price = float(fut_price)`.
   - Sets `fut_features["price"] = float(fut_price)`.
   - Computes:
     - `sl_price, t1_price, t2_price = calculate_directional_levels(entry_price=float(fut_price), direction=fut_direction)`.
4. **Theoretical vs Actual Isolation**:
   - Passes `actual_futures_price=float(fut_price)` to `resolver.calculate_fair_value`.
   - Stores theoretical fair value in `fut_features["fair_value"]` and basis in `fut_features["basis"]` cleanly without raising `TypeError`.
5. **R2 Cooldown & Limit Enforcement**:
   - Verifies deduplication cooldown and rate limits before pricing.
   - Commits cooldown timestamp `self._last_alert_time[fut_symbol] = now_ts` only after quote verification passes.
6. **Production Configuration Guard**:
   - Default fallback: `bool(self._cfg.get("FUTURES_ENABLED", False))`.

---

## 4. Empirical Test Verification

| Test Suite | Tests Run | Result | Duration | Scope Verified |
| :--- | :---: | :---: | :---: | :--- |
| [`tests/test_d26_taxonomy_futures_parity.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/tests/test_d26_taxonomy_futures_parity.py) | **13** | **PASSED** | 2.68s | D26-A cash/option classification, 10-category taxonomy, index spot formatting, D26-B live LTP, fail-closed feeds, R2 cooldowns, rate limits |
| [`tests/test_signal_quality_remediation_d20.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/tests/test_signal_quality_remediation_d20.py) | **28** | **PASSED** | 3.68s | D20-A/B signal quality gates, equity swing R-multiples, multi-theme UI |
| [`tests/test_post_market_remediation_r1_r4.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/tests/test_post_market_remediation_r1_r4.py) | **24** | **PASSED** | 2.76s | Post-market reconciliation, R1-R4 rules, derived futures wiring |
| [`tests/test_remediation_p1_p2_p3.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/tests/test_remediation_p1_p2_p3.py) | **1** | **PASSED** | 1.49s | `test_instrument_classification` |
| [`tests/test_product_integrity_remediation.py`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/tests/test_product_integrity_remediation.py) | **2** | **PASSED** | 1.82s | `test_canonical_taxonomy_classification`, `test_canonical_taxonomy_boundary_semantics` |

**Total Regression Tests Passed**: **68 tests**.

---

## 5. Database Safety & Integrity Verification

An empirical hash and row-count verification was executed before and after test execution on `db/signals_history.db`:

```text
Database File: db/signals_history.db
Baseline SHA256: f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a
Current  SHA256: f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a
SHA256 Exact Match: True
PRAGMA integrity_check: ok
PRAGMA foreign_key_check: 0 violations
```

### Table Row Counts (Delta = 0 across all 11 tables):
- `system_signals`: 498 (Δ 0)
- `signal_outcome_events`: 365 (Δ 0)
- `signal_forward_observations`: 101 (Δ 0)
- `signal_outcome_measurements`: 101 (Δ 0)
- `signal_prediction_snapshots`: 101 (Δ 0)
- `user_deliveries`: 344 (Δ 0)
- `scan_cycle_metrics`: 38 (Δ 0)
- `signal_delivery_audit`: 12 (Δ 0)
- `notification_dead_letter`: 3 (Δ 0)
- `notification_retry_queue`: 3 (Δ 0)
- `sqlite_sequence`: 4 (Δ 0)

---

## 6. Zero Mutation Compliance Audit

| Safety Invariant | Required State | Actual Empirical State | Status |
| :--- | :--- | :--- | :---: |
| EC2 Server Modification | 0 Modifications | 0 Modified | **COMPLIANT** |
| Git Commits | 0 Commits | 0 Commits | **COMPLIANT** |
| Git Push | 0 Pushes | 0 Pushed | **COMPLIANT** |
| Production Server Restart | 0 Restarts | 0 Restarts | **COMPLIANT** |
| Broker / Order API Calls | 0 API Calls | 0 Calls (`orders=0`) | **COMPLIANT** |
| Production Configuration Mutations | 0 Config Edits | 0 Edits (`config.json` untouched) | **COMPLIANT** |
| Historical Database Writes | 0 Mutations | 0 Mutations (`SHA256 match: True`) | **COMPLIANT** |
| `FUTURES_ENABLED` in Production | `False` | `False` | **COMPLIANT** |
| `D20-C` Experimental Targets | `OFF` | `OFF` | **COMPLIANT** |
| Equity Swing Targets (+4%/+8%/-3%) | Untouched | Untouched | **COMPLIANT** |
| Canonical 10 Categories | Exactly 10 Preserved | Exactly 10 Preserved | **COMPLIANT** |

---

## 7. Conclusion & Gate Decision

Phase D26-A and Phase D26-B are successfully remediated and verified under strict local-only engineering governance. All 13 dedicated parity tests and 55 regression tests pass with 100% success. Zero mutations occurred on EC2, GitHub remote, broker connections, production configuration, or the historical database.

**Completion Gate**: **APPROVED FOR LOCAL ARTIFACT CLOSURE (HARD STOP BEFORE COMMIT/PUSH)**.
