# OPB v2.60 — FORWARD VALIDATION EVIDENCE REPORT

**Governing Authority**: [`OPB-FINAL-PHASE-GOVERNANCE-001`](.agents/rules/opb-final-phase-governance.md)  
**Timestamp**: `2026-10-01T10:44:00+05:30` (IST)  
**Market status**: `OPEN` (Active Indian Market Session: 09:15–15:30 IST)

---

## 1. COMMIT & REMOTE PROVENANCE
- **Commit SHA**: `4863fd3b5dc5a30af23d38ad8e46005242d57f59`
- **GitHub SHA**: `4863fd3b5dc5a30af23d38ad8e46005242d57f59`
- **EC2 SHA**: `4863fd3b5dc5a30af23d38ad8e46005242d57f59`
- **Parity Status**: `100% EXACT PARITY (HEAD == origin == EC2)`

---

## 2. RUNTIME SAFETY & EXECUTION INVARIANTS
- **SIGNAL_ONLY**: `true`
- **Lockout**: `true` (`LIVE_TRADING_LOCKOUT = True`)
- **Full Auto Allowed**: `false`
- **Broker**: `DISCONNECTED`
- **Orders**: `0`
- **Trades**: `0`
- **Broker Positions**: `0`
- **Internal Orders**: `0`
- **Futures Auto Execution**: `false` (`FUTURES_ENABLED = false`)
- **D20-C**: `OFF` (`EXPERIMENTAL / NOT PRODUCTION`)
- **Execution Service Reconciliation**: `CLEAN (broker pos: 0, internal orders: 0, durable state checked: 0)`

---

## 3. LIVE MARKET FEED & SCANNER HEALTH
- **Market feed**: `Live NSE Direct API` (Real-time option chains and equity quotes)
- **Symbols scanned**: `2,608 symbols / cycle` (Interval: ~60s)
- **Freshness status**: `ACTIVE` (`ALL_NSE_SCANNER: [FRESHNESS_GATE]` actively rejecting bars older than 300s with `code=STALE_MARKET_DATA`)
- **Recent Scan Cycles**:
  - `SCAN-20261001T104215287217-6c241152`: 2,608 evaluated, 95 accepted, 10 delivered candidates
  - `SCAN-20261001T103424655538-a7dfa490`: 2,608 evaluated, 55 accepted, 10 delivered candidates
  - `SCAN-20261001T102122154908-a6171ee2`: 2,608 evaluated, 27 accepted, 10 delivered candidates

---

## 4. SIGNAL & OBSERVATION ACCUMULATION

### Session Window (Today: 2026-10-01):
- **New natural signals today**: `49`
- **New observations today**: `49`
- **New resolved outcomes today**: `0` (All 49 currently tracking forward in active multi-day/session holding horizon)

### Cumulative Forward Observations:
- **Cumulative observations**: `149`
- **Cumulative resolved**: `14`
- **Currently observing**: `135`

### Outcome Distribution (Resolved + Observing):
- **T1 Hits (TARGET_FIRST)**: `3` (Resolved wins: +4.00% target hit)
- **T2 Hits**: `0`
- **SL Hits (SL_FIRST)**: `2` (Resolved stop losses: -3.00% SL hit)
- **Timeout**: `9` (Holding horizon elapsed without barrier touch)
- **Ambiguous (Same Bar)**: `0`
- **DQ (Data Quality Fail)**: `0`
- **Stale Market Data**: `0`
- **Unresolved / Observing**: `134` (Active tracking)
- **Just Registered (Pending initial tick)**: `1`

---

## 5. SCORE BUCKETS PERFORMANCE

| Score Bucket | Total Observations | Resolved Count | T1 Hits (+4%) | SL Hits (-3%) | Timeout Count | Win Rate (Resolved) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **95–100** | 55 | 5 | 0 | 2 | 3 | 0.0% (Small sample: 5 resolved) |
| **90–94** | 39 | 3 | 3 | 0 | 0 | 100.0% (3/3 T1 hits) |
| **85–89** | 24 | 0 | 0 | 0 | 0 | N/A (0 resolved, 24 observing) |
| **80–84** | 23 | 2 | 0 | 0 | 2 | 0.0% (2 timeouts) |
| **< 80** | 8 | 4 | 0 | 0 | 4 | 0.0% (4 timeouts) |
| **Total** | **149** | **14** | **3** | **2** | **9** | **21.4% Overall (60.0% excluding timeouts)** |

*Governance Note: In accordance with Section 19, sample size (14 resolved) is insufficient to infer monotonicity. Observational only.*

---

## 6. CANONICAL CATEGORY BREAKDOWN

| Canonical Category | Total Observations | Resolved Count | T1 Hits (+4%) | SL Hits (-3%) | Observing |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **EQUITY_SWING_DELIVERY** | 70 | 3 | 2 | 1 | 67 |
| **MID_SMALL_CAP** | 42 | 3 | 1 | 1 | 39 |
| **LARGE_CAP_EQUITY** | 22 | 1 | 0 | 0 | 21 |
| **INDEX_OPTIONS** | 10 | 6 | 0 | 0 | 4 |
| **COMMODITIES** | 4 | 1 | 0 | 0 | 3 |
| **PENNY_SME** | 1 | 0 | 0 | 0 | 1 |
| **Total** | **149** | **14** | **3** | **2** | **135** |

---

## 7. TIME-OF-DAY BREAKDOWN (TODAY: 2026-10-01)

| Session Window | Signal Count | Average Score | Observations |
| :---: | :---: | :---: | :--- |
| **09:15–10:00** | 13 | 84.46 | Initial market opening volatility, selective screening |
| **10:00–11:30** | 36 | 91.39 | Morning trend alignment, momentum continuation |
| **11:30–13:30** | Active | In Progress | Mid-day consolidation tracking |
| **13:30–14:30** | Pending | — | European session overlap / afternoon positioning |
| **14:30–15:30** | Pending | — | Market close / expiry settlement window |

---

## 8. EXCURSION & DURATION METRICS
- **Resolved Observations**:
  - Average Maximum Favorable Excursion (`mfe_r`): `+0.484 R`
  - Average Maximum Adverse Excursion (`mae_r`): `+0.246 R`
- **Active Observing Signals**:
  - Current Average MFE (`mfe_r`): `+0.094 R`
  - Current Average MAE (`mae_r`): `+0.079 R`
- **Time-to-resolution**: Multi-session swing tracking active. Zero premature manual resolutions.

---

## 9. STATISTICAL GATES & PHASE-E STATUS

| Statistical Gate | Required Threshold | Current Verified State | Gate Status |
| :--- | :--- | :--- | :---: |
| **G1** | >= 100 resolved observations per active bucket | Bucket 95–100: 5; Bucket 90–94: 3; Bucket 80–84: 2 | **OPEN** |
| **G2** | >= 300 resolved forward events overall | 14 resolved (135 observing, 149 total) | **OPEN** |
| **G3** | >= 2 months with >= 30 resolved/month | Commenced Sept 2026; 2 months not yet elapsed | **OPEN** |
| **G4** | DQ <= 5%, Stale <= 2% | 149 / 149 observations: 100% `VALID_DATA` (0 DQ, 0 Stale) | **PASS** |

### Phase E Release Gate:
> ### 🛑 **`PHASE E REMAINS STRICTLY BLOCKED`**
> Technical stability and clean execution reconciliation do **not** constitute statistical readiness. Automated live trading remains locked out until G1, G2, and G3 empirically achieve their approved thresholds.

---

## 10. SECURITY STATUS CONFIRMATION
- **SEC-01 (Nginx Server Header)**: `OPEN` — Host Nginx configuration `/etc/nginx/nginx.conf:22` contains `server_tokens build;`. Requires host operational change to `server_tokens off;` during scheduled server maintenance.
- **SEC-02 (Super Admin MFA)**: `OPEN` — TOTP engine fully implemented in `core/auth/mfa.py`; requires administrator to complete one-time authenticator device setup.
- **SEC-03 (Admin First-Login Password)**: `OPEN` — Form login redirect active; API-level middleware scheduled for next security release.

---

## 11. INTEGRITY AUDIT
- **DB integrity (Local)**: SHA `f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a`, Size `1,216,512` B. Byte Delta: 0.
- **DB integrity (EC2)**: SQLite `PRAGMA integrity_check` -> `ok`. All row additions represent authorized natural runtime telemetry. Zero unauthorized manual writes.
- **Historical data integrity**: All historical Phase-D cohorts, outcome measurements, and predictions remain 100% immutable.
- **Synthetic / sample / demo audit**: Verified 0 sample/demo tokens across all 41 production UI pages.
- **Regression tests**: 62 / 62 tests pass (100% pass rate).
- **Unexpected anomalies**: `NONE`.

---

## 12. CODE CHANGES & GOVERNANCE ACTION
- **Code changes**: `NONE` (Zero code modifications performed; system is operating strictly in forward-validation observation mode).
- **Final classification**:

# 📋 **`OBSERVATION ONLY`**

- **Phase E**:

# 🛑 **`STRICTLY BLOCKED`**
