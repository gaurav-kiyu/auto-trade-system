# OPB D25-R1 — ARCHITECTURE RECONCILIATION & IMPLEMENTATION EVIDENCE GATE REPORT

**Governance Authority**: `OPB-FINAL-PHASE-GOVERNANCE-001`  
**Execution Timestamp**: `2026-09-30T01:15:00+05:30`  
**Git Branch**: `v2.60-phase-d-candle-selection-remediation`  
**Authoritative Git HEAD**: `2769e6154728b6519c4cfa7d25478f7eb38a6d76` (Local and Remote in exact parity)  
**Current Operational Mode**: `PRODUCTION / PAPER / SIGNAL_ONLY`  
**Safety Invariants**: `full_auto_allowed=False, broker_routing=DISCONNECTED, live_trading_lockout=True, orders=0`  
**Phase D20-C Status**: `DISABLED (0)` | **Phase E Status**: `STRICTLY BLOCKED`  
**Task Classification**: **STRICTLY READ-ONLY EVIDENCE AUDIT & RECONCILIATION GATE** (Zero code changes, zero config changes, zero DB writes, zero deployments)

---

## 1. PURPOSE & AUDIT CONTEXT

Phase D25 established the target architecture for an instrument-accurate, category-complete signal lifecycle. However, before any engineering implementation may commence, the **OPB Engineering Constitution (`OPB-FINAL-PHASE-GOVERNANCE-001`)** mandates that:
> *"NEVER DECLARE COMPLETION OR COMMENCE IMPLEMENTATION BASED ON ASSUMPTION. Only PROVEN empirical test & remote verification results may be used as evidence."*

The purpose of **Phase D25-R1** is to perform a rigorous forensic audit to separate **genuine empirical market evidence** from **engineering test fixtures, simulation assumptions, and architectural hypotheses**, reconciling all conflicting numbers and defining an unambiguous implementation gate.

---

## 2. R1 — SEPARATE REAL EVIDENCE FROM TEST / PROPOSED EVIDENCE

Every data population utilized in Phase D24 and D25 has been forensically audited and classified into its rightful epistemological category:

| Evidence Population | Sample Size ($N$) | Data Source | Real Market Data? | Real Prod Signal? | Real Resolved Outcome? | Safe for Predictive Inference? | Epistemological Classification & Reason |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **Equity Swing Signals** | **279** | EC2 Production DB (`system_signals`) | **YES** | **YES** | **YES** ($N=76$) | **YES** | **GENUINE PRODUCTION OBSERVATIONS**: Real cash stock signals emitted on live EC2 runtime against live NSE ticks. Sole validated edge driver. |
| **Stock Option Signals** | **99** | EC2 Production DB (`system_signals`) | **YES** | **YES** | **NO** | **NO** | **CORRUPTED PRODUCTION OBSERVATIONS**: Cash stocks mislabeled as options; evaluated against spot cash with +4% intraday target. Outcome reflects spot mismatch, not option performance. |
| **Index Option Signals** | **60** | EC2 Production DB (`system_signals`) | **YES** | **YES** | **NO** | **NO** | **CORRUPTED PRODUCTION OBSERVATIONS**: Cash spot indices mislabeled as options; evaluated against spot cash with +4% intraday target. 100% timeout reflects spot target infeasibility. |
| **Commodity Signals** | **2** | EC2 Production DB (`system_signals`) | **YES** | **YES** | **NO** | **NO** | **INSUFFICIENT SAMPLE**: $N=2$ is statistically unrepresentative. Observation only. |
| **Local Futures Signals** | **386** | Local Dev DB (`db/signals_history.db`) | **NO** (Historical Bars) | **NO** (Local Tests) | **NO** (Test Runs) | **NO** | **ENGINEERING VALIDATION ONLY**: Generated during local test harnesses (Phases D14-D21) to validate R1 schema. `FUTURES_ENABLED=false` on EC2. Real DB shows 212 Expired, 73 SL, 0 T1. |
| **Options Targets (+25/+50/-20)**| **0** | D24 / D25 Architectural Proposal | **NO** | **NO** | **NO** | **NO** | **PROPOSED ARCHITECTURE VALUES**: Retail rule-of-thumb heuristics. Zero historical option contract tick/candle datasets exist in repository. |
| **Proposed 'Entry By' Durations**| **0** | D25 Hypothesis | **NO** | **NO** | **NO** | **NO** | **PROPOSED ARCHITECTURE VALUES**: Architectural hypotheses (15m, 5m, 10m). Zero empirical fill telemetry exists. |
| **Feasibility Formulas (ATR/Theta)**| **0** | D25 Hypothesis | **NO** | **NO** | **NO** | **NO** | **THEORETICALLY MOTIVATED HYPOTHESIS**: Mathematical approximations; uncalibrated against real market tick distributions. |

---

## 3. R2 — EQUITY SWING NUMERIC RECONCILIATION

Phase D25 presented several seemingly conflicting numbers for Equity Swing: $N=279$, 34 target hits, 43 T1 hits, 35 SL hits, 201 timeouts, and a 49.28% win rate. A deep forensic audit of `system_signals` and `signal_outcome_events` reveals the exact origin of every figure:

### Exact Database State (`EQUITY_SWING_DELIVERY`, $N=279$):
```text
================================================================================
EQUITY SWING FORENSIC TABLE BREAKDOWN
================================================================================
Table: `system_signals` (Category = EQUITY_SWING_DELIVERY)
  - ACTIVE (Unexpired 5-day horizon):            203 signals (72.76%)
  - SL_HIT:                                       35 signals (12.54%)
  - TARGET_1_HIT:                                 23 signals  (8.24%)
  - TARGET_2_HIT:                                 11 signals  (3.94%)
  - AMBIGUOUS (Same observation T1/T2 conflict):   7 signals  (2.51%)
  Total Population:                              279 signals (100.0%)

Column: `first_touch` in `system_signals`
  - Empty string (Active):                       203 signals
  - 'SL':                                         35 signals
  - 'T1':                                         34 signals (23 T1-only + 11 T1->T2)
  - 'AMBIGUOUS_SAME_OBSERVATION':                  7 signals

Table: `signal_outcome_events`
  - Total records with hit_t1 == 1:               43 events
  - Total records with hit_sl == 1:               35 events
  - Total records with hit_t2 == 1:               19 events
================================================================================
```

### Forensic Discrepancy Reconciliation:
1. **Where did 34 Target Hits come from?**
   - Derived from `system_signals.first_touch == 'T1'` ($23 	ext{ TARGET\_1\_HIT} + 11 	ext{ TARGET\_2\_HIT} = 34$).
2. **Where did 43 T1 Hits come from?**
   - Derived from querying raw event rows in `signal_outcome_events` where `hit_t1 == 1`.
   - The discrepancy of **9 events** ($43 - 34 = 9$) is proven:
     - **2 signals** (`ALUFLUOR`, `AXISCADES`) hit **Stop-Loss first**, and later bounced on subsequent days to touch T1. Under first-touch rules, the trade was already closed at SL (`first_touch = 'SL'`); the later T1 hit is a post-exit excursion.
     - **7 signals** (`HEROMOTORS`, `BOSCH-HCIL`, `RKEC`, `SBC`, `TIPSFILMS`, `RSYSTEMS`, `TNTELE`) breached both T1 and T2 in the exact same initial observation bar. Under conservative governance, these were flagged as `AMBIGUOUS_SAME_OBSERVATION` rather than credited as pure T1 hits.
     - Formula: $34 	ext{ (Pure First-Touch T1)} + 2 	ext{ (Post-SL Bounces)} + 7 	ext{ (Ambiguous)} = \mathbf{43 	ext{ Raw T1 Events}}$.
3. **Where did 35 SL Hits come from?**
   - Exact match ($N=35$) across both `system_signals` (`status = 'SL_HIT'`) and `signal_outcome_events`.
4. **Where did "201 Timeouts" come from?**
   - **RECONCILIATION ERROR IN D25 REPORTING.** In D25, the author calculated $279 - 76 = 203$ active signals, but mislabeled them as "timeouts" (and misprinted 201). In reality, **zero Equity Swing signals have timed out**. All 203 signals are currently **ACTIVE** within their valid 5-day holding horizons! Calling active signals "timeouts" was a reporting error.
5. **Where did 49.28% Win Rate come from?**
   - Evaluated on unambiguous resolved trades:
     $$	ext{Win Rate}_{	ext{Unambiguous}} = rac{	ext{First-Touch T1}}{	ext{First-Touch T1} + 	ext{First-Touch SL}} = rac{34}{34 + 35} = rac{34}{69} = \mathbf{49.28\%}$$
   - Conservative Win Rate (counting ambiguous signals as non-wins):
     $$	ext{Win Rate}_{	ext{Conservative}} = rac{	ext{First-Touch T1}}{	ext{All Resolved}} = rac{34}{34 + 35 + 7} = rac{34}{76} = \mathbf{44.74\%}$$
   - Platform Conversion Rate (resolved hits over all emitted signals):
     $$	ext{Conversion Rate} = rac{34}{279} = \mathbf{12.19\%}$$

---

## 4. R3 — OPTIONS +25% / +50% / -20% STATUS

An exhaustive search across the entire repository confirms that **zero historical option contract tick, bar, or outcome datasets exist**.
- Every Index Option ($N=60$) and Stock Option ($N=99$) in the database recorded cash spot prices and evaluated spot targets.
- The proposed target model (+25% T1, +50% T2, -20% SL on option premium) is an intuitive retail heuristic based on target delta expansion, but has **zero empirical validation** within OPB.
- **Classification**: **`EXPERIMENTAL CANDIDATE — NOT PRODUCTION VALIDATED`**.
- **Action**: These values MUST NOT be implemented, hardcoded, or deployed into production until a genuine forward observation dataset on live option contracts is accumulated.

---

## 5. R4 — 'ENTRY BY' DURATION RECONCILIATION

D25 proposed:
- Equity Swing: 15 minutes
- Index & Stock Options: 5 minutes
- Futures: 10 minutes
- Commodities & Currencies: 15 minutes

**Audit Finding**: None of these four durations are empirically derived.
- In production, OPB had zero entry expiration windows; signals remained active indefinitely.
- The proposed values represent **architectural hypotheses** based on candle timeframes and momentum decay.
- **Classification**: **`PROPOSED — REQUIRES FORWARD VALIDATION`**.
- **Action**: In the initial rollout, entry validity must operate in **OBSERVATION-ONLY MODE**, capturing timestamped order fill telemetry to measure fill rates and drift distributions before enforcing hard order cancellations.

---

## 6. R5 — OPTION ADAPTER RUNTIME READINESS

An inspection of the actual callable functions in the repository yields the following field-level readiness report:

| Option Field | Index Options Status | Stock Options Status | Callable Source / Implementation Reality |
| :--- | :--- | :--- | :--- |
| **`contract_symbol`** | `AVAILABLE BUT UNVERIFIED` | `REQUIRES IMPLEMENTATION` | Built in `core/live_option_quotes.py:build_option_symbol()`. Only supports index names; does NOT support stock option symbols. Not verified against live NSE master. |
| **`underlying`** | `AVAILABLE` | `AVAILABLE` | Parsed from clean symbol string. |
| **`option_type`** | `AVAILABLE` | `AVAILABLE` | Mapped from signal direction (`CE` for BUY, `PE` for SELL). |
| **`strike`** | `AVAILABLE BUT UNVERIFIED` | `REQUIRES IMPLEMENTATION` | Index strikes rounded to step 50/100. Stock strike steps vary dynamically by stock; no stock strike step table exists in repo. |
| **`expiry`** | `AVAILABLE BUT UNVERIFIED` | `AVAILABLE BUT UNVERIFIED` | Resolved via `core.exchange_calendar_engine.get_calendar_engine().get_next_expiry()`. |
| **`LTP`** | `NOT AVAILABLE` | `NOT AVAILABLE` | `fetch_live_option_quote()` relies on `broker_adapter.get_quote()`. In production, `broker_routing=DISCONNECTED`, and `PaperBrokerAdapter` lacks NFO feeds. Returns `None`. |
| **`bid` / `ask` / `spread`**| `NOT AVAILABLE` | `NOT AVAILABLE` | Requires live NFO Level-2 market depth. |
| **`OI` / `volume`** | `NOT AVAILABLE` | `NOT AVAILABLE` | Requires live NFO quote feed. |
| **`IV`** | `NOT AVAILABLE` | `NOT AVAILABLE` | `core/options_greeks_engine.py` can solve IV only if market price is provided. Without live option LTP, IV cannot be solved. |
| **`delta` / `gamma` / `theta`**| `NOT AVAILABLE` | `NOT AVAILABLE` | `compute_greeks_quick()` requires IV and spot. Without IV, Greeks cannot be calculated. |

### Runtime Readiness Verdict:
- **Can the current production runtime resolve an actual Index Option contract?**  
  **NO.** While Black-Scholes math and symbol construction routines exist, there is NO live option quote feed, NO BSE option adapter (`core/bse_option_chain.py` does not exist), and broker routing is disconnected.
- **Can the current production runtime resolve an actual Stock Option contract?**  
  **NO.** Stock strike selection, stock option symbol formatting, and stock option market feeds are completely absent.

---

## 7. R6 — FUTURES N=386 EVIDENCE CLASSIFICATION

A forensic trace of the 386 local Futures records in `db/signals_history.db` revealed:
- **Creation Context**: Generated during local engineering tests (Phases D14-D21) between 2026-09-17 and 2026-09-28 to validate the R1 contract resolver.
- **Actual Statuses in Local DB**:
  - `EXPIRED`: **212 signals**
  - `ACTIVE`: **101 signals**
  - `SL_HIT`: **73 signals**
  - `TARGET_1_HIT`: **0 signals (ZERO)**
- **Exposure of D25 Replay Discrepancy**:
  In Phase D25, the simulation script `scratch/simulate_d25_replay.py` contained the following line:
  ```python
  'would_emit': True,
  'prod_t1_hit': True, # tested in local run <--- HARDCODED TO TRUE!
  ```
  The simulation script hardcoded `prod_t1_hit = True` as an illustrative assumption. The real database contains **zero T1 hits** for futures!
- **Classification**: **`STRICTLY ENGINEERING VALIDATION ONLY — UNSAFE FOR PREDICTIVE INFERENCE`**.
- **Mandatory Invariant**: The N=386 local futures population MUST NOT be cited as evidence of trading profitability.

---

## 8. R7 — D25 FEASIBILITY FORMULA VALIDATION

| Feasibility Formula | Mathematical Expression | Classification | Audit Evaluation & Risk |
| :--- | :--- | :--- | :--- |
| **Index Option Move** | $	ext{Expected Move} 	imes \Delta \ge 	ext{Target Premium}$ | **THEORETICALLY MOTIVATED (B)** | Sound first-order Taylor approximation ($\Delta P pprox \Delta \cdot \Delta S$), but ignores Gamma and volatility crush. |
| **Theta Decay Cap** | $	ext{Theta} 	imes 	ext{Hours} \le 0.20 	imes 	ext{Target}$ | **ARBITRARY / PROPOSED (C)** | 20% cap is an uncalibrated heuristic rule of thumb. |
| **Spread Limit** | $	ext{Spread} \le 1.0 	ext{ INR}$ | **ARBITRARY / PROPOSED (C)** | A flat 1 INR cap is distortive: 4% on a 25 INR option, but 0.25% on a 400 INR option. Needs percentage-based spread limit. |
| **Equity Swing Move** | $4.0\% \le 0.80 	imes 5 	imes 	ext{Daily ATR}$ | **THEORETICALLY MOTIVATED (B)** | Aligns with empirical observation that stocks with ATR > 2% hit 4% targets, but 0.80 multiplier is uncalibrated. |
| **Futures Range** | $1.0	imes 	ext{ATR} \le 	ext{Remaining Range}$ | **THEORETICALLY MOTIVATED (B)** | Statistically sound intraday range constraint, but uncalibrated against intraday tick histories. |

**Verdict**: None of these formulas are empirically validated. They must be treated as **candidate experimental filters** rather than hard production gating rules.

---

## 9. R8 — CONTRACT SCHEMA VALIDATION

The sample contract object presented in D25 was audited against the Black-Scholes calculation engine (`core/options_greeks_engine.py`):
```text
================================================================================
D25 SAMPLE OPTION OBJECT vs BLACK-SCHOLES ENGINE TRUTH
================================================================================
Parameter / Metric       D25 Sample Value        Calculated Black-Scholes Truth
--------------------------------------------------------------------------------
Contract Symbol          NIFTY24OCT23500CE       INVALID (Year 24 vs 26; Monthly code on Weekly date)
Spot Price               23,520.40               23,520.40
Strike Price             23,500.00               23,500.00
Time to Expiry           2.5 Days                2.5 Days
Implied Volatility (IV)  13.5% (0.135)           13.5% (0.135)
Option Premium (Price)   185.50 INR              120.92 INR (FATAL MISMATCH - 53% Error)
Delta                    0.5200                  0.5490
Gamma                    0.002100                0.001507
Theta (Daily)            -12.50 INR/day          -23.09 INR/day (FATAL MISMATCH - 85% Error)
Vega                     18.20                   7.71 (FATAL MISMATCH - 136% Error)
================================================================================
```
**Verdict**: The D25 sample object contains **ILLUSTRATIVE MOCK EXAMPLE VALUES** with severe internal mathematical contradictions. It is strictly classified as **ILLUSTRATIVE SCHEMA SPECIFICATION ONLY**, with zero empirical standing.

---

## 10. R9 — UNIVERSAL CATEGORY & INDEX COMPLETENESS

The universal taxonomy is reaffirmed with 100% completeness:
- **All 10 Categories Covered**: `EQUITY_SWING_DELIVERY`, `INDEX_OPTIONS`, `STOCK_OPTIONS`, `FUTURES`, `COMMODITIES`, `CURRENCIES`, `ETFS_REITS`, `PENNY_SME`, `LARGE_CAP_EQUITY`, `MID_SMALL_CAP`.
- **All 7 Indices Covered**: `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `SENSEX`, `MIDCPNIFTY`, `BANKEX`, `NIFTYNXT50`.
- **Zero Omissions**: No category or index has been omitted or proxy-substituted.

---

## 11. R10 — FINAL IMPLEMENTATION GATE

```text
================================================================================
LIST A: APPROVED FOR IMPLEMENTATION NOW (UNAMBIGUOUS EVIDENCE & ZERO RISK)
================================================================================
1. [A-1] Fix `core/fno_universe.py` (`classify_instrument_market`):
   Stop misclassifying cash equities in FNO_EQUITY_STOCKS as `STOCK_OPTIONS`.
   Reclassify cash equity breakouts to `EQUITY_INTRADAY` or `EQUITY_SWING_DELIVERY`.
2. [A-2] Fix `AllNSEScanner._dispatch_futures_alert_if_eligible()`:
   Ensure alert entry price uses canonical contract LTP from `FuturesContractResolver`,
   never the cash spot price. (Keep FUTURES_ENABLED=false until verified).
3. [A-3] Fix Presentation Transparency:
   Update UI and Telegram presentation so Index Options explicitly display as
   "INDEX SPOT DIRECTIONAL" until genuine option contracts are wired.
4. [A-4] Decouple Active Signals from Timeouts:
   Ensure reporting scripts distinguish Active signals (N=203) from Timeouts.

================================================================================
LIST B: EXPERIMENTAL / VALIDATION REQUIRED (STRICTLY BLOCKED FROM PROD)
================================================================================
1. [B-1] Option Premium Targets (+25% T1, +50% T2, -20% SL) - EXPERIMENTAL
2. [B-2] Strict Entry By Order Cancellation Windows (15m, 5m, 10m) - HYPOTHESIS
3. [B-3] Feasibility Formulas (ATR multipliers, Theta caps, Spread caps) - THEORETICAL
4. [B-4] Automated Strike Selection Optimization - REQUIRES TICK DATA
5. [B-5] Calibrated Target Probability Engine - REQUIRES N >= 150 TRUTHFUL OUTCOMES
6. [B-6] BSE SENSEX / BANKEX Option Chain - REQUIRES ADAPTER IMPLEMENTATION

================================================================================
LIST C: MUST REMAIN UNTOUCHED (CONSTITUTIONAL INVARIANTS)
================================================================================
1. [C-1] EQUITY_SWING_DELIVERY +4% T1, +8% T2, -3% SL levels and scoring weights.
2. [C-2] R1 Futures Contract Resolver canonical architecture.
3. [C-3] R3 Completed Candle outcome measurement engine.
4. [C-4] D20-A and D20-B deployed candle selection remediation logic.
5. [C-5] Broker safety invariants (full_auto_allowed=False, broker_routing=DISCONNECTED, live_lockout=True).
6. [C-6] Phase E strictly blocked status.
7. [C-7] Low-sample categories (Commodities, Currencies, ETFs, Penny/SME) parameters.
================================================================================
```

---

## 12. REQUIRED FINAL RECOMMENDATION & IMPLEMENTATION PHASING

OPB is **NOT READY** for live option trading, automated order dropping, or synthetic probability scoring.
However, OPB **IS READY** for data purity and taxonomy fixes.

### Exact Implementation Phasing:
1. **Phase D26-A: Instrument Truth & Taxonomy Purity** (Execute First)
   - Implement List A fixes (Taxonomy reclassification, Presentation truth, Active vs Timeout reporting).
2. **Phase D26-B: Futures Scanner Contract Parity**
   - Correct `_dispatch_futures_alert_if_eligible` to use contract LTP; verify against R1 test suite while keeping `FUTURES_ENABLED=false` on EC2.
3. **Phase D26-C: Entry Validity & Drift Observation Telemetry**
   - Add lifecycle timestamp fields to schema; record drift in paper mode without dropping orders.
4. **Phase D26-D: Genuine Option Quote Feed Engineering**
   - Implement real NFO quote feed adapter via broker or market data vendor; build BSE adapter.
5. **Phase D26-E: Controlled Forward Validation & Target Calibration**
   - Collect 14 days of genuine option contract forward ticks; empirically calibrate targets and feasibility gates.

---

## 13. MANDATORY SAFETY ACCOUNTING & FINAL STOP

```text
================================================================================
OPB D25-R1 MANDATORY SAFETY INVARIANT ACCOUNTING
================================================================================
Production Code Changes:          0 (STRICT ZERO)
Production Configuration Edits:   0 (STRICT ZERO)
Database Writes / Mutations:      0 (STRICT ZERO - Verified SHA256)
Git Commits Executed:             0 (STRICT ZERO)
Git Pushes Executed:              0 (STRICT ZERO)
EC2 Deployments:                  0 (STRICT ZERO)
Service Restarts:                 0 (STRICT ZERO)
Broker Order API Calls:           0 (STRICT ZERO)
D20-C Activation:                 0 (DISABLED)
Phase E Activation:               0 (STRICTLY BLOCKED)
Canonical DB SHA256:              f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a
Working Tree Status:              100% CLEAN OF TRACKED MODIFICATIONS
================================================================================
```

**FINAL STATUS**:
`D25-R1 RECONCILIATION COMPLETE`  
`NO IMPLEMENTATION`  
`NO DEPLOYMENT`  
`NO PRODUCTION CHANGE`  
`PHASE E BLOCKED`
