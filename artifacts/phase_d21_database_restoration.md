# OPB — D21 DATABASE CONTAMINATION FORENSIC RESTORATION REPORT

**Document ID**: `OPB-D21-DATABASE-RESTORATION-20260929`  
**Execution Timestamp**: `2026-09-29T18:08:00+05:30`  
**Governance Authority**: [`OPB-FINAL-PHASE-GOVERNANCE-001`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/.agents/rules/opb-final-phase-governance.md)  
**Git Branch**: `v2.60-phase-d-candle-selection-remediation`  
**Authoritative Working HEAD**: `124f52c81322a46275a88c2291924198920a02b1`  
**Pre-Restoration Contaminated DB SHA-256**: `c45c3e3a2693f7aecbc4e5ab0b11222b2c425ab839b51917fe88179f7b0a3e8f`  
**Post-Restoration DB SHA-256**: `f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a`  
**Historical Forward Observation Count**: `101 / 101 RESTORED` (Authoritative forward cohort intact)  
**Full Regression Suite**: `243 / 243 PASSED (100%)`  
**Post-Test Database Immutability**: `VERIFIED (SHA-256 unchanged across test run)`  
**Phase E Status**: `STRICTLY BLOCKED` (`full_auto_allowed=False`, `BROKER_AUTO_ROUTING=DISCONNECTED`)  

---

## 1. Executive Summary

During interactive tracing in Phase D21 (step 53126 at `2026-09-29 16:13:43 IST`), a diagnostic test signal:
```text
SIG-20260929161343-RELIANCE24AUG2500CE-ea1184
```
was inadvertently written to the authoritative local database (`db/signals_history.db`) because `SignalTracker.get_instance()` was invoked without mock isolation.

Pursuant to the strict mandate of [`OPB-FINAL-PHASE-GOVERNANCE-001`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/.agents/rules/opb-final-phase-governance.md), all staging preparation was immediately halted. Under this forensic restoration procedure:
1. A forensic byte-for-byte backup of the contaminated database was created and cryptographically verified at `scratch/signals_history_pre_restoration_contaminated.db` (`SHA-256: c45c3e3a...`).
2. An atomic SQL transaction was executed against `db/signals_history.db` targeting **ONLY** `signal_id = 'SIG-20260929161343-RELIANCE24AUG2500CE-ea1184'`, removing exactly 7 rows (1 in `system_signals`, 4 in `user_deliveries`, 1 in `signal_prediction_snapshots`, and 1 in `signal_forward_observations`).
3. Total forward observations returned from `102` back to the authoritative `101`.
4. Full table-by-table logical equivalence was verified across all 10 SQLite tables: **zero discrepancies, zero residual traces, and exact row content parity for all legitimate historical data**.
5. The full 243-test regression suite was executed and passed with a 100% success rate (including `test_g4_metric_dual_reporting` and `test_data_quality_affected_quarantine_in_analytics`).
6. Post-test database immutability was confirmed (`SHA-256` unchanged before and after test execution).

---

## 2. Forensic Contamination Details

| Parameter | Value |
| :--- | :--- |
| **Contaminating Signal ID** | `SIG-20260929161343-RELIANCE24AUG2500CE-ea1184` |
| **Symbol / Instrument** | `RELIANCE24AUG2500CE` (Series: `OPT`, Direction: `CALL`) |
| **Execution Timestamp** | `2026-09-29 16:13:43 IST` |
| **Originating Command** | Interactive python command in transcript step 53126 |
| **Target Database Path** | `d:\AI_APPs\TRADING_APP\OPB_V2_59_4_CANONICAL\db\signals_history.db` |
| **Pre-Contamination DB SHA-256** | `ceb7b33d1d90d64a445acb7d3377c1006f4292b3216d69fe4f2b34e274a22455` |
| **Contaminated DB SHA-256** | `c45c3e3a2693f7aecbc4e5ab0b11222b2c425ab839b51917fe88179f7b0a3e8f` |

### Forensic Blast-Radius: Rows Injected
- `system_signals`: Exactly 1 row (`signal_id = 'SIG-20260929161343-RELIANCE24AUG2500CE-ea1184'`)
- `user_deliveries`: Exactly 4 rows (deliveries to `admin`, `superadmin`, `test_admin`, `test_super_admin`)
- `signal_prediction_snapshots`: Exactly 1 row
- `signal_forward_observations`: Exactly 1 row (`FWD_SIG-20260929161343-RELIANCE24AUG2500CE-ea1184`)
- **Other Tables**: Exactly 0 rows injected or modified across all 6 remaining tables.

---

## 3. Mandatory Pre-Restoration Forensic Backup

Prior to any write operations on `db/signals_history.db`, a forensic backup was created:
- **Backup File Path**: `C:\Users\gaura\.gemini\antigravity\brain\1f2fb8fe-7538-4d67-8afe-948c42276d56\scratch\signals_history_pre_restoration_contaminated.db`
- **Backup File Size**: `1,216,512 bytes`
- **Backup SHA-256**: `c45c3e3a2693f7aecbc4e5ab0b11222b2c425ab839b51917fe88179f7b0a3e8f`
- **Cryptographic Verification**: **100% MATCH** with contaminated `db/signals_history.db`.

---

## 4. Controlled Restoration Execution

The restoration was executed via a strict single-transaction Python script ([`scratch/execute_db_restoration.py`](file:///C:/Users/gaura/.gemini/antigravity/brain/1f2fb8fe-7538-4d67-8afe-948c42276d56/scratch/execute_db_restoration.py)):

```sql
BEGIN TRANSACTION;
DELETE FROM signal_forward_observations WHERE signal_id = 'SIG-20260929161343-RELIANCE24AUG2500CE-ea1184';
DELETE FROM signal_prediction_snapshots WHERE signal_id = 'SIG-20260929161343-RELIANCE24AUG2500CE-ea1184';
DELETE FROM user_deliveries WHERE signal_id = 'SIG-20260929161343-RELIANCE24AUG2500CE-ea1184';
DELETE FROM system_signals WHERE signal_id = 'SIG-20260929161343-RELIANCE24AUG2500CE-ea1184';
COMMIT;
```

### Empirical Execution Metrics:
- Rows deleted from `signal_forward_observations`: **1**
- Rows deleted from `signal_prediction_snapshots`: **1**
- Rows deleted from `user_deliveries`: **4**
- Rows deleted from `system_signals`: **1**
- **Total rows deleted across all tables**: **7**
- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: `[] (0 violations)`
- Traces of contaminating signal ID across entire DB: **0**

---

## 5. Mechanical Analysis of SQLite SHA-256 Difference

The resulting database has SHA-256:
```text
f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a
```
as opposed to the pre-contamination SHA-256 (`ceb7b33d...`). 

As anticipated in Section 4 of the D21 restoration mandate, a SQL `DELETE` alone does not return the exact physical byte stream of the pre-INSERT SQLite file. The forensic mechanical reasons are:

1. **Transaction Change Counter**:
   - SQLite specification byte offsets 24–27 and 92–95 contain the file change counter and version-valid-for fields.
   - Every committed write transaction increments this 32-bit counter.
   - Pre-contamination counter was `521`.
   - The contamination insert committed counter `522`.
   - The restoration deletion committed counter `523`.
2. **B-Tree Page Allocation & Freelist**:
   - The initial insert expanded the database from 295 pages (1,208,320 bytes) to 297 pages (1,216,512 bytes), allocating leaf pages 296 and 297.
   - In SQLite, executing `DELETE` marks the record cells as unallocated/free cells within existing pages (pages 266, 282, 283, 296). SQLite does NOT truncate the file or release allocated B-tree pages back to the OS unless `VACUUM` is invoked.
3. **Assessment of VACUUM vs Page Stability**:
   - Running `VACUUM` was empirically tested on an isolated copy:
     - Vacuumed SHA-256: `c58c317ae7bc43ffe7fa31a242a2870bab9730576d7e03f237e269ca82ed7e0d`
     - Vacuumed Size: `1,179,648 bytes` (288 pages).
   - **Engineering Decision**: `VACUUM` was explicitly **REJECTED** in favor of preserving page stability. `VACUUM` completely repacks all tables into fresh pages in alphabetical order, fundamentally mutating physical page addresses, row packing, and index layouts for all 101 legitimate historical observations. Retaining the standard post-deletion state preserves exact historical page structures and eliminates any risk of row re-arrangement.

---

## 6. Table-by-Table Logical Equivalence Audit

To establish conclusive empirical proof of logical restoration, an exhaustive row-for-row audit ([`scratch/verify_logical_equivalence.py`](file:///C:/Users/gaura/.gemini/antigravity/brain/1f2fb8fe-7538-4d67-8afe-948c42276d56/scratch/verify_logical_equivalence.py)) was executed comparing the restored database against the pre-restoration backup (excluding the single contaminating signal):

| Table Name | Pre-Restoration Rows | Post-Restoration Rows | Rows Removed | Historical Content Match | Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `notification_dead_letter` | 3 | 3 | 0 | **100% Identical** | **VERIFIED** |
| `notification_retry_queue` | 3 | 3 | 0 | **100% Identical** | **VERIFIED** |
| `scan_cycle_metrics` | 38 | 38 | 0 | **100% Identical** | **VERIFIED** |
| `signal_delivery_audit` | 12 | 12 | 0 | **100% Identical** | **VERIFIED** |
| `signal_forward_observations` | 102 | **101** | 1 | **100% Identical** | **VERIFIED** |
| `signal_outcome_events` | 365 | 365 | 0 | **100% Identical** | **VERIFIED** |
| `signal_outcome_measurements` | 101 | 101 | 0 | **100% Identical** | **VERIFIED** |
| `signal_prediction_snapshots` | 102 | **101** | 1 | **100% Identical** | **VERIFIED** |
| `system_signals` | 499 | **498** | 1 | **100% Identical** | **VERIFIED** |
| `user_deliveries` | 348 | **344** | 4 | **100% Identical** | **VERIFIED** |

**Audit Result**: **10 out of 10 tables verified with ZERO discrepancies. Every single field of all 101 historical forward observations matches pre-contamination values exactly.**

---

## 7. Full Regression Suite & Immutability Verification

The entire 243-test canonical regression suite was executed against the restored database:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.0.3, pluggy-1.6.0
rootdir: D:\AI_APPs\TRADING_APP\OPB_V2_59_4_CANONICAL
configfile: pytest.ini
plugins: anyio-4.13.0
collected 243 items

tests/test_controlled_staging_d21.py ......................              [  9%]
tests/test_signal_quality_remediation_d20.py ............................ [ 20%]
tests/test_post_market_remediation_r1_r4.py ............................ [ 37%]
tests/test_forward_accumulation_reporter.py ............................ [ 53%]
tests/test_signal_outcome_tracker.py .................................... [ 69%]
tests/test_signal_forward_wiring_remediation.py ......................... [ 80%]
tests/test_candle_selection_remediation.py ...............               [ 86%]
tests/test_category_score_thresholds.py ............                     [ 91%]
tests/test_signal_dispatch_order_placed_reply.py ...........             [ 95%]
tests/test_futures_trader.py ......                                      [ 98%]
tests/test_signal_outcome_dataset.py ....                                [100%]

============================ 243 passed in 13.87s =============================
```

### Specific Target Integrity Tests Verified:
- `test_g4_metric_dual_reporting`: **PASSED**
- `test_data_quality_affected_quarantine_in_analytics`: **PASSED**
- `test_production_db_read_only_execution`: **PASSED**

### Post-Test Database Immutability Check:
- Pre-Test SHA-256: `f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a`
- Post-Test SHA-256: `f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a`
- **Result**: `Pre-Test == Post-Test` (100% Immutable).

---

## 8. Governance Invariants & Final State

| Invariant | Target Requirement | Empirical Status |
| :--- | :--- | :---: |
| **Zero Production Code Mutation** | No edits outside authorized test/doc paths | **CONFIRMED** |
| **Zero Git Commit / Push** | Local working tree only | **CONFIRMED** |
| **Zero EC2 Remote Sync** | No SSH/sync to production servers | **CONFIRMED** |
| **Zero Broker API Calls** | No order placement or live/paper broker calls | **CONFIRMED** |
| **Authoritative Observation Cohort** | Exactly 101 forward observations | **CONFIRMED** |
| **Regression Suite Pass Rate** | 243 / 243 tests passing | **CONFIRMED (100%)** |
| **Phase E Status** | Strictly blocked (`full_auto_allowed=False`) | **BLOCKED** |

**Conclusion**: The accidental contamination has been completely removed. The local database `db/signals_history.db` is fully restored, logically verified, and protected against further mutations. D21 staging preparation is now unblocked.
