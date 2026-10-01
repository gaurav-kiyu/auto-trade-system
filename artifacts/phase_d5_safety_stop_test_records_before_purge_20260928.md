# OPB v2.60 — FORENSIC AUDIT: 7 SYNTHETIC TEST RECORDS BEFORE PURGE

**Document ID**: `OPB-V260-SAFETY-STOP-TEST-RECORDS-PRE-PURGE-20260928`  
**Execution Timestamp**: `2026-09-28T13:10:00+05:30`  
**Source Suite**: `tests/test_universal_coverage_and_thresholds.py` (Tests 19, 21, 38, 40, 41, 42)  
**Creation Window**: `2026-09-28 12:57:12` to `2026-09-28 12:57:13 IST`  
**Target Database**: `db/signals_history.db`  

---

## 1. Summary of Positively Identified Records

All 7 records were confirmed to originate exclusively from unmocked `SignalTracker.get_instance().record_generated_signal(...)` calls inside `tests/test_universal_coverage_and_thresholds.py`. Each record bears an explicit `opportunity_key` starting with `TEST-`.

| # | Signal ID | Symbol | Opportunity Key | Score | Category | Direction | Registered Forward ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `SIG-20260928125712-NIFTY26SEPFUT-39fa89` | `NIFTY26SEPFUT` | `TEST-FUT-MOM-1790580432.693895` | 84 | FUTURES | BUY | `FWD_SIG-20260928125712-NIFTY26SEPFUT-39fa89` |
| **2** | `SIG-20260928125713-BANKNIFTY26SEPFUT-fad72a` | `BANKNIFTY26SEPFUT` | `TEST-MARGIN-BLOCK-1790580433.4847047` | 85 | FUTURES | BUY | `FWD_SIG-20260928125713-BANKNIFTY26SEPFUT-fad72a` |
| **3** | `SIG-20260928125713-TCS26SEPFUT-9208e4` | `TCS26SEPFUT` | `TEST-DEDUP-FUT-1790580433.592235` | 88 | FUTURES | BUY | `FWD_SIG-20260928125713-TCS26SEPFUT-9208e4` |
| **4** | `SIG-20260928125713-SENSEX26SEPFUT-9a4d60` | `SENSEX26SEPFUT` | `TEST-DECOUPLE-1790580433.7022505` | 86 | FUTURES | BUY | `FWD_SIG-20260928125713-SENSEX26SEPFUT-9a4d60` |
| **5** | `SIG-20260928125713-INFY26SEPFUT-2aadf6` | `INFY26SEPFUT` | `TEST-RESTART-1790580433.8148816` | 80 | FUTURES | BUY | `FWD_SIG-20260928125713-INFY26SEPFUT-2aadf6` |
| **6** | `SIG-20260928125713-WIPRO26SEPFUT-294fb7` | `WIPRO26SEPFUT` | `TEST-LINEAGE-1790580433.837912` | 82 | FUTURES | BUY | `FWD_SIG-20260928125713-WIPRO26SEPFUT-294fb7` |
| **7** | `SIG-20260928125713-SBIN26SEPFUT-43899b` | `SBIN26SEPFUT` | `TEST-DUP-FUT-1790580433.858575` | 81 | FUTURES | BUY | `FWD_SIG-20260928125713-SBIN26SEPFUT-43899b` |

---

## 2. Table-by-Table Footprint to be Purged

1. **`system_signals`**: Exactly 7 rows matching the 7 Signal IDs above.
2. **`signal_prediction_snapshots`**: Exactly 7 rows matching the 7 Signal IDs above.
3. **`signal_forward_observations`**: Exactly 7 rows matching the 7 Forward IDs above.
4. **`user_deliveries`**: Exactly 3 rows matching `DEL-SIG-20260928125712-NIFTY26SEPFUT-39fa89-admin`, `DEL-SIG-20260928125713-BANKNIFTY26SEPFUT-fad72a-admin`, `DEL-SIG-20260928125713-SENSEX26SEPFUT-9a4d60-admin`.
5. **`signal_outcome_measurements`**: 0 rows exist (verified).
6. **`scan_cycle_metrics`**: 0 rows exist (verified).

---

## 3. Relational Foreign Key Integrity

- Primary Key target: `signal_id` IN:
  - `'SIG-20260928125712-NIFTY26SEPFUT-39fa89'`
  - `'SIG-20260928125713-BANKNIFTY26SEPFUT-fad72a'`
  - `'SIG-20260928125713-TCS26SEPFUT-9208e4'`
  - `'SIG-20260928125713-SENSEX26SEPFUT-9a4d60'`
  - `'SIG-20260928125713-INFY26SEPFUT-2aadf6'`
  - `'SIG-20260928125713-WIPRO26SEPFUT-294fb7'`
  - `'SIG-20260928125713-SBIN26SEPFUT-43899b'`

All 45 legitimate observations (from morning/midday live scans) have distinct, genuine equity IDs and remain 100% untargeted and unmutated.
