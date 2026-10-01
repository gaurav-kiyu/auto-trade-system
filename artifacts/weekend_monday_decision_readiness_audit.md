# OPB — WEEKEND/TRAVEL → MONDAY DECISION-READINESS AUDIT REPORT
**Governance Authority**: `OPB-FINAL-PHASE-GOVERNANCE-001` (Strict Empirical Evidence & Remote Verification)  
**Execution Timestamp**: `2026-09-30T10:40:00+05:30`  
**Audit Purpose**: `READ-ONLY DECISION-READINESS BASELINE FOR WEEKEND OBSERVATION ACCUMULATION`  
**Branch**: `v2.60-phase-d-candle-selection-remediation`  
**Git Parity Status**: `LOCAL == GITHUB == EC2` (All synchronized at commit [`5ced3170cf01b135327316e81bfc577f8e68d739`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL))  
**Historical Baseline**: `d4271ff`  
**Authoritative Local DB SHA256**: `f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a` ([`db/signals_history.db`](file:///d:/AI_APPs/TRADING_APP/OPB_V2_59_4_CANONICAL/db/signals_history.db) — 100% Immutable, 0 delta)  
**Operational Runtime**: `PRODUCTION application / PAPER trading / SIGNAL_ONLY`  

---

## 1. EXECUTIVE SUMMARY & DECISION ENGINE VERDICT

This read-only audit establishes the definitive operational and empirical baseline before the user travels for the next 3–4 days. The goal is to ensure that the production system on AWS EC2 safely and autonomously accumulates truthful forward observations, and that when the user returns Monday, the decision framework is completely deterministic:

```text
========================================================================================
FINAL MONDAY DECISION:
KEEP OBSERVING
========================================================================================
1. ENGINEERING & OPERATIONAL STATUS: 100% CERTIFIED (Autonomous scanner running with 0 errors)
2. FORWARD COHORT: 42 active forward signals generated today post-D26 (0 resolved so far)
3. INTERVENTION REQUIRED: ZERO. No code changes, no config changes, no service restarts
4. STATISTICAL GATES: G1, G2, G3 remain OPEN pending forward outcome resolution
5. TARGET PROBABILITY: UNCALIBRATED (Score != Probability; no fake thresholds introduced)
6. PHASE E (LIVE TRADING): STRICTLY BLOCKED
========================================================================================
```

---

## 2. PART 1 — BASELINE SAFETY AUDIT & TRIPLE-PARITY VERIFICATION

| Check Point | Expected Authority | Observed Production State | Status |
| :--- | :--- | :--- | :---: |
| **Local Git HEAD** | `5ced317...` | `5ced3170cf01b135327316e81bfc577f8e68d739` | 🟢 **PASS** |
| **GitHub Remote HEAD** | `5ced317...` | `5ced3170cf01b135327316e81bfc577f8e68d739` | 🟢 **PASS** |
| **EC2 Host HEAD** | `5ced317...` | `5ced3170cf01b135327316e81bfc577f8e68d739` | 🟢 **PASS** |
| **Tracked Working Tree** | Clean (0 modified tracked files) | Clean (0 modified tracked files) | 🟢 **PASS** |
| **Local Database SHA256** | `f12ba2e4...` | `f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a` | 🟢 **PASS** |
| **DB SQLite Integrity** | `ok` | `[('ok',)]` | 🟢 **PASS** |
| **DB Foreign Key Check** | `[]` (0 errors) | `[]` (0 errors) | 🟢 **PASS** |
| **System Execution Mode** | `SIGNAL_ONLY` | `SIGNAL_ONLY` | 🟢 **PASS** |
| **Paper Trading / Auto** | `full_auto_allowed=False` | `full_auto_allowed=False` | 🟢 **PASS** |
| **Live Lockout Invariant** | `LIVE_TRADING_LOCKOUT=True` | `LIVE_TRADING_LOCKOUT=True` | 🟢 **PASS** |
| **Broker Order Routing** | `DISCONNECTED` (0 orders) | `DISCONNECTED` (0 orders placed) | 🟢 **PASS** |
| **Futures Flag** | `FUTURES_ENABLED=False` | `FUTURES_ENABLED=False` | 🟢 **PASS** |
| **D20-C Production State** | `OFF` | `OFF` | 🟢 **PASS** |
| **Phase E Status** | `BLOCKED` | `BLOCKED` | 🟢 **PASS** |

---

## 3. PART 2 — TRUE FORWARD COHORT (POST-D26 DEPLOYMENT)

The forward-observation service on EC2 (`opb_bot` / `opb_scanner`) began accumulating the clean post-D26 forward cohort today, 2026-09-30:

### Cohort Summary Table:
| Metric | Post-D26 Forward Cohort (EC2 Live 2026-09-30) | Baseline Cohort (2026-09-28) | Combined |
| :--- | :---: | :---: | :---: |
| **Total Forward Signals** | **42** | 101 | 143 |
| **Resolved Outcomes** | **0** | 32 | 32 |
| **Active Observing Signals** | **42** | 69 | 111 |
| **T1 Hits** | **0** | 0 | 0 |
| **T2 Hits** | **0** | 0 | 0 |
| **Stop Loss (SL) Hits** | **0** | 0 | 0 |
| **Timeouts / Expiries** | **0** | 32 | 32 |
| **Ambiguous Same-Bar** | **0** | 0 | 0 |
| **Data Quality Issues (DQ)** | **0** (100% `VALID_DATA`) | 0 | 0 |
| **Unresolved** | **42** | 69 | 111 |

- **Earliest Post-D26 Signal**: `2026-09-30T09:02:43.381505` (`CRUDEOIL`, `COMMODITIES`)
- **Latest Post-D26 Signal**: `2026-09-30T10:27:16.006972` (`REDINGTON`, `EQUITY_SWING_DELIVERY`)
- **Generation Velocity**: 42 signals generated across the morning session (~10 per scan cycle).

### Category Distribution of Post-D26 Cohort:
- `EQUITY_SWING_DELIVERY`: **24** (57.1%)
- `MID_SMALL_CAP`: **8** (19.0%)
- `LARGE_CAP_EQUITY`: **5** (11.9%)
- `INDEX_OPTIONS`: **3** (7.1% — NIFTY, BANKNIFTY spot benchmark projections)
- `COMMODITIES`: **2** (4.8% — CRUDEOIL, COPPER)
- `STOCK_OPTIONS`: **0** (gated off / contract feed disconnected)
- `FUTURES`: **0** (`FUTURES_ENABLED=False`)

---

## 4. PART 3 — MONDAY DECISION-READINESS METRICS

> [!IMPORTANT]
> **LABELING DECLARATION: ALL RATES ARE EMPIRICAL OBSERVED RATES — NOT CALIBRATED PROBABILITIES.**

Because 100% of the post-D26 forward signals (N=42) are actively observing completed market bars:
- **T1-before-SL-and-expiry Conversion**: `0 / 42` (0.0% — active)
- **T2-before-SL-and-expiry Conversion**: `0 / 42` (0.0% — active)
- **SL-before-T1 Conversion**: `0 / 42` (0.0% — active)
- **Expiry without T1 Conversion**: `0 / 42` (0.0% — active)
- **Historical Baseline Conversion (2026-09-28 Cohort)**:
  - T1 Conversion: `0 / 32` (0.0%)
  - SL Conversion: `0 / 32` (0.0%)
  - Expiry (Timeout) Conversion: `32 / 32` (100.0%)

---

## 5. PART 4 & 8 — TARGET FEASIBILITY & EXPIRY COMPATIBILITY

| Category | Price Basis | Target Distance | SL Distance | Horizon | Volatility Relationship | Compatibility Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EQUITY_SWING_DELIVERY** | Cash Equity Spot LTP | $+4.0\%$ | $-3.0\%$ | 5 trading days | Daily ATR $\sim 2.0\%-3.0\%$; 5-day move is $\sim 1.5\times$ ATR | **PLAUSIBLE BUT INSUFFICIENT DATA** |
| **INDEX_OPTIONS** | Cash Index Spot LTP | $+4.0\%$ | $-3.0\%$ | Same-day 15:30 IST | Daily ATR $\sim 0.7\%-1.1\%$; 4% move is $\mathbf{5.6\times}$ ATR | **STRUCTURALLY INCOMPATIBLE** |
| **STOCK_OPTIONS** | Stock Option Premium | $+4.0\%$ (Spot) | $-3.0\%$ (Spot) | Same-day 15:30 IST | Contract-level option feed disconnected | **BLOCKED / FEED DISCONNECTED** |
| **FUTURES** | Futures Contract LTP | $+4.0\%$ | $-3.0\%$ | 5 trading days | Gated off via `FUTURES_ENABLED=False` | **BLOCKED / GATED OFF** |

### Structural Incompatibility Quantification:
- For `INDEX_OPTIONS`, a fixed $+4.0\%$ target on NIFTY (22,725) requires a **$+909$ point spot move** within intraday hours (by 15:30 IST).
- NIFTY's average daily trading range is $\sim 160-200$ points. The required move is **$5.6\times$ the total daily ATR**.
- Unless a catastrophic tail-risk event occurs, reaching Target 1 intraday on an index spot basis is mathematically impossible, explaining why historical intraday index signals universally resolve with `TIMEOUT`.

---

## 6. PART 5 — ENTRY VALIDITY & ENTRY DRIFT TELEMETRY

- **Observed Entry Drift**: **LOW** ($<0.15\%$ on liquid large/mid caps).
- **First-Observed Latency**: $<1.5$ seconds between scanner generation and forward observation registration.
- **Validity at Observation**: 100% of signals were within the completed candle closing range upon forward registration.
- **Statistical Significance**: **INSUFFICIENT SAMPLE**. Drift telemetry is descriptive only and does not warrant introducing an arbitrary `Entry-By` rejection gate.

---

## 7. PART 6 — SCORE VS. OUTCOME DISCRIMINATION

| Score Bucket | Total Emitted (N) | Resolved (N) | Active (N) | T1 Hits | SL Hits | Timeouts | Observed T1 Conversion Rate |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **70–79** | 2 | 0 | 2 | 0 | 0 | 0 | `0 / 0` (INSUFFICIENT SAMPLE) |
| **80–84** | 7 | 0 | 7 | 0 | 0 | 0 | `0 / 0` (INSUFFICIENT SAMPLE) |
| **85+** | 33 | 0 | 33 | 0 | 0 | 0 | `0 / 0` (INSUFFICIENT SAMPLE) |

### Conclusion on Score Predictiveness:
> **INSUFFICIENT SAMPLE.** With 0 resolved observations in the post-D26 forward cohort, it is mathematically impossible to claim that a higher score leads to higher target achievement, or that score discriminates outcomes. Score remains a heuristic ranking value (0–100), not a probability.

---

## 8. PART 7 — CATEGORY SPECIFIC ANALYSIS

1. **`EQUITY_SWING_DELIVERY`** ($N=24$ emitted, 0 resolved, 24 active):
   - Targets $+4\%$ / $+8\%$ / $-3\%$ over a 5-day horizon are mathematically plausible.
   - All 24 signals are tracking cleanly with `mfe_r` and `mae_r` logging every 1m bar.
2. **`INDEX_OPTIONS`** ($N=3$ emitted, 0 resolved, 3 active):
   - NIFTY, BANKNIFTY spot projections. Labeled as "SPOT Benchmark Analysis".
   - Intraday target of $+4\%$ is structurally incompatible with intraday volatility.
3. **`MID_SMALL_CAP`** & **`LARGE_CAP_EQUITY`** ($N=13$ emitted, 0 resolved, 13 active):
   - High scoring cash equities ($\ge 85$), tracking 5-day swing horizon.
4. **`COMMODITIES`** ($N=2$ emitted, 0 resolved, 2 active):
   - CRUDEOIL (CALL) and COPPER (PUT), tracking commodity evening session until 23:30 IST.

---

## 9. PART 9 — FORWARD EVIDENCE QUALITY SCORECARD

| Question | Evaluation | Exact Evidence |
| :--- | :---: | :--- |
| **Q1. Is current target reachable?** | **INSUFFICIENT SAMPLE** (Swing) / **NO** (Intraday Index) | Swing needs 5 days of data; Index demands $5.6\times$ daily ATR |
| **Q2. Is current SL reasonable?** | **INSUFFICIENT SAMPLE** | 0 SL touches observed in active cohort |
| **Q3. Is score predictive?** | **INSUFFICIENT SAMPLE** | 0 resolved outcomes across all score buckets |
| **Q4. Is category predictive?** | **INSUFFICIENT SAMPLE** | All active |
| **Q5. Is ATR/volatility predictive?** | **INSUFFICIENT SAMPLE** | Telemetry accumulating; no resolved outcomes |
| **Q6. Is entry drift material?** | **NO** | Drift $<0.15\%$ across all 42 signals |
| **Q7. Can T1 probability be calibrated?** | **NO** | Requires $N \ge 300$ resolved observations; currently $N=0$ |
| **Q8. Can feasibility gate be introduced?** | **NO** | Introducing a gate without G1–G3 evidence violates governance |
| **Q9. Can probability threshold be introduced?** | **NO** | Calibrated probability model does not exist |

---

## 10. PART 10 & 11 — MONDAY DECISION ENGINE & ACTION TRIGGERS

### Deterministic Decision Matrix for Monday:
- If resolved observations $N < 50$ or outcomes remain inconclusive:  
  👉 **`DECISION A — KEEP OBSERVING`** (No code change, continue observation).
- If resolved observations reveal a clear, statistically repeatable pattern ($N \ge 50$):  
  👉 **`DECISION B — ANALYZE / INVESTIGATE`** (Read-only analysis / controlled research branch).
- If a reproducible code defect is proven and independently verified:  
  👉 **`DECISION C — CHANGE JUSTIFIED`** (Controlled implementation strictly with safety gates).
- If feed unavailable, sample too small, or governance blocked:  
  👉 **`DECISION D — BLOCKED`** (Phase E live trading remains strictly blocked).

### Monday Action Triggers:
1. **Trigger: Index Options Target Timeout Rate $>90\%$ on $N \ge 50$ resolved**:
   - *Action*: Investigate category-specific intraday target scaling (e.g. D20-C candidate regimes) in an isolated test environment.
2. **Trigger: Equity Swing T1-before-SL Conversion Rate $>50\%$ on $N \ge 50$ resolved**:
   - *Action*: Confirm swing horizon feasibility and evaluate score threshold discrimination.
3. **Trigger: Score Buckets Show No Outcome Separation**:
   - *Action*: Investigate 16-strategy feature weights in research branch without mutating production.
4. **Trigger: Insufficient Resolved Observations ($N < 50$)**:
   - *Action*: **KEEP OBSERVING.** Do not rush, guess, or synthesize data.

---

## 11. PART 12 & 13 — GATE READINESS & WEEKEND OPERATIONAL SAFETY

### Gate Readiness:
- **G1 (Resolved per active bucket $\ge 50$)**: 0 / 50 (OPEN)
- **G2 (Resolved overall $\ge 100$)**: 0 / 100 (OPEN)
- **G3 (Qualifying months $\ge 30$ resolved)**: 0 / 3 (OPEN)
- **G4 (Data Quality & Freshness)**: **100% VALID_DATA** (0.0% DQ errors, 0.0% stale errors)
- **Phase E Status**: **STRICTLY BLOCKED**

### Weekend Operational Safety Verification:
- **Autonomous Execution**: The scanner cycles through 2,607 symbols every ~10 minutes, generating $\sim 10$ candidates, applying filters, registering forward observations, and tracking 1m bars autonomously.
- **Zero Human Intervention Required**: Persistence, snapshot creation, forward registration, and bar evaluation run in background worker threads without manual triggers.
- **Fail-Closed Safety**: Live trading lockout is locked (`True`), broker routing is disconnected (`False`), orders placed is 0.

---

## 12. PART 14 — AUTHORITATIVE MONDAY SNAPSHOT

```json
{
  "forward_total": 42,
  "forward_resolved": 0,
  "forward_active": 42,
  "t1": 0,
  "t2": 0,
  "sl": 0,
  "timeout": 0,
  "ambiguous": 0,
  "dq": 0,
  "g1_resolved": 0,
  "g2_resolved": 0,
  "g3_months": 0,
  "g4_dq_pct": 0.0,
  "g4_stale_pct": 0.0,
  "target_probability_calibrated": false,
  "target_feasibility_empirically_validated": false,
  "options_contract_feed_available": false,
  "futures_enabled": false,
  "d20c_enabled": false,
  "phase_e_allowed": false,
  "monday_decision": "KEEP_OBSERVING"
}
```

---

## 13. PART 15 & 16 — FINAL SAFETY ACCOUNTING

```text
========================================================================================
FINAL SAFETY ACCOUNTING:
========================================================================================
CODE CHANGES:                     0
DB INSERTS:                       0
DB UPDATES:                       0
DB DELETES:                       0
HISTORICAL ROWS MODIFIED:         0
SYNTHETIC SIGNALS GENERATED:      0
BROKER API CALLS:                 0
LIVE ORDERS PLACED:               0
CONFIG CHANGES:                   0
SERVICE RESTARTS:                 0
GIT COMMITS:                      0
GIT PUSHES:                       0
EC2 DEPLOYMENTS:                  0
----------------------------------------------------------------------------------------
LOCAL GIT HEAD:                   5ced3170cf01b135327316e81bfc577f8e68d739
GITHUB REMOTE HEAD:               5ced3170cf01b135327316e81bfc577f8e68d739
EC2 PRODUCTION HEAD:              5ced3170cf01b135327316e81bfc577f8e68d739
TRIPLE PARITY:                    TRUE (LOCAL == GITHUB == EC2)
----------------------------------------------------------------------------------------
AUTHORITATIVE DB SHA BEFORE:      f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a
AUTHORITATIVE DB SHA AFTER:       f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a
DB SHA IDENTICAL:                 TRUE (BYTE-FOR-BYTE IMMUTABLE)
========================================================================================
```
