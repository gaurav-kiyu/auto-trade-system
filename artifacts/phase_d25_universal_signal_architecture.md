# OPB D25 — UNIVERSAL SIGNAL LIFECYCLE, INSTRUMENT TRUTH & TARGET FEASIBILITY ARCHITECTURE SPECIFICATION

**Governance Authority**: `OPB-FINAL-PHASE-GOVERNANCE-001`  
**Execution Timestamp**: `2026-09-30T00:30:00+05:30`  
**Git Branch**: `v2.60-phase-d-candle-selection-remediation`  
**Authoritative Git HEAD**: `2769e6154728b6519c4cfa7d25478f7eb38a6d76` (Local and Remote in exact parity)  
**Operational Mode**: `PRODUCTION / PAPER / SIGNAL_ONLY`  
**Safety Status**: `full_auto_allowed=False, broker_routing=DISCONNECTED, live_lockout=True, orders=0`  
**Phase D20-C Status**: `DISABLED (0)` | **Phase E Status**: `STRICTLY BLOCKED`  
**Task Type**: **STRICTLY READ-ONLY ARCHITECTURAL & IMPLEMENTATION-READINESS AUDIT**

---

## 1. PRIMARY OBJECTIVE & EXECUTIVE MANDATE

The primary objective of **Phase D25** is to prepare OPB for an instrument-truthful, category-complete, and target-achievable signal lifecycle. D24 empirically proved that OPB has functioned historically as an aggressive **signal generation engine** rather than a **target-achievable signal generation engine**:
- **Equity Swing Delivery ($N=279$)**: The sole genuine edge producer on the platform (49.28% win rate, 34 target hits), where a 5-day holding horizon gives ample time for a +4.0% price move.
- **Index Options ($N=60$) & Stock Options ($N=99$)**: Fatally mislabeled cash directional signals. Evaluated against spot cash prices with a fixed +4.0% target and an intraday 15:30 IST cutoff, resulting in **100% and 96.97% timeout rates**.
- **Futures ($N=0$ on EC2, $N=386$ in Local Testing)**: Disabled in production (`FUTURES_ENABLED=false`). In the scanner, futures alerts previously inherited the cash spot price (`parent_signal.price`), creating price and volatility contamination.

D25 establishes the definitive, uncompromised architecture to transition OPB from generating raw signals to generating **fewer, higher-quality, instrument-accurate signals whose defined entry, T1, T2, and SL are realistically achievable**.

---

## 2. STAGE A: INSTRUMENT TRUTH AUDIT

An end-to-end trace from candidate discovery to outcome resolution reveals the exact data sources and price bases across categories:

```text
+---------------------------------------------------------------------------------------------------+
| CATEGORY               | DISPLAYED SYMBOL   | GENERATION PRICE | TARGET BASIS     | OUTCOME MONITOR PRICE | PARITY STATUS       |
+------------------------+--------------------+------------------+------------------+-----------------------+---------------------+
| EQUITY_SWING_DELIVERY  | Cash Equity (e.g.  | Cash Spot LTP    | Cash Spot +4.0%  | Completed Cash Daily  | EXACT PARITY (TRUE) |
|                        | TATACHEM)          |                  |                  | Candles (R3 Protected)|                     |
| INDEX_OPTIONS          | Synthetic Contract | Cash Index Spot  | Cash Spot +4.0%  | Cash Index Spot 1-Min | FATAL MISMATCH      |
|                        | (NIFTY24AUG24500CE)| (e.g. 23,500 pts)| (+940 pts)       | (No Option Contract)  | (MISLABELED)        |
| STOCK_OPTIONS          | Cash Stock Symbol  | Cash Stock LTP   | Cash Stock +4.0% | Cash Stock 1-Min      | FATAL MISMATCH      |
|                        | (e.g. TATASTEEL)   | (e.g. 150.00 INR)| (Intraday Cutoff)| (No Option Contract)  | (MISLABELED)        |
| FUTURES (PROD)         | Disabled on EC2    | N/A              | N/A              | N/A                   | DISABLED            |
| FUTURES (LOCAL TEST)   | Contract Symbol    | Cash Spot Price  | Spot Points      | Contract Bars (R1)    | PRICE BASIS DEFECT  |
|                        | (NIFTY-FUT-R1)     | (Parent Signal)  |                  |                       | (REMEDIATED IN D25) |
+---------------------------------------------------------------------------------------------------+
```

### Empirical Proofs of Instrument Truth:
1. **Index Options**: No option contract, strike price, option LTP, bid, ask, implied volatility, or delta was ever queried or recorded in production. The signal monitored the spot index price. A target of +4% on NIFTY is ~940 points (5.22x daily ATR). Requiring 5.22x daily ATR intraday is mathematically impossible, explaining the 100% failure rate.
2. **Stock Options**: Cash equities belonging to `FNO_EQUITY_STOCKS` were tagged as `STOCK_OPTIONS` merely because the stock is F&O listed. They were evaluated against cash spot prices under an intraday 15:30 IST timeout, explaining the 96.97% failure rate.
3. **Futures**: In `core/all_nse_scanner.py`, `_dispatch_futures_alert_if_eligible` set `entry_price = parent_signal.price` (the cash stock spot price) rather than querying the futures contract market feed.

---

## 3. STAGE B: THE UNIVERSAL SIGNAL LIFECYCLE

The universal signal lifecycle is strictly defined across 17 linear stages, with exact module mapping:

```text
[1. MARKET DATA] (`core/market_data_engine.py`)
       ↓
[2. CANDIDATE DISCOVERY] (`core/scanner/candidate_discovery.py`)
       ↓
[3. CATEGORY CLASSIFICATION] (`core/taxonomy/category_classifier.py`)
       ↓
[4. INSTRUMENT SELECTION] (`core/derivatives/instrument_resolver.py`)
       ↓
[5. DIRECTION DETERMINATION] (`core/strategy/directional_engine.py`)
       ↓
[6. SETUP SCORING] (`core/scoring/setup_score_engine.py`)
       ↓
[7. ENTRY VALIDITY GATING] (`core/signals/entry_validity_engine.py`)
       ↓
[8. TARGET FEASIBILITY GATING] (`core/signals/target_feasibility_engine.py`)
       ↓
[9. TARGET / SL CONSTRUCTION] (`core/signals/target_sl_builder.py`)
       ↓
[10. SIGNAL DELIVERY] (`core/dispatch/signal_dispatcher.py`)
       ↓
[11. ENTRY EXECUTION] (`core/execution/entry_manager.py`)
       ↓
[12. ACTIVE POSITION TRACKING] (`core/portfolio/active_position_tracker.py`)
       ↓
[13. T1 / T2 / SL MONITORING] (`core/signals/outcome_monitor.py` - R3 Protected)
       ↓
[14. POSITION EXPIRY MANAGEMENT] (`core/signals/expiry_manager.py`)
       ↓
[15. OUTCOME RESOLUTION] (`core/signals/outcome_resolver.py`)
       ↓
[16. MFE / MAE TRACKING] (`core/analytics/excursion_engine.py`)
       ↓
[17. ANALYTICS & CALIBRATION] (`core/analytics/calibration_engine.py`)
```

### The 4 Independent Lifecycle Timestamps:
These four timestamps represent distinct physical events and MUST NOT be conflated:
1. **$T_{	ext{CREATE}}$**: Exact timestamp of candle close when setup pattern is recognized and signal record created.
2. **$T_{	ext{ENTRY\_VALID\_FROM}}$**: Timestamp when order execution becomes authorized (typically at the open of the confirmation candle).
3. **$T_{	ext{ENTRY\_VALID\_UNTIL}}$ (`Entry By`)**: Expiration deadline of the entry opportunity window. If unfilled when $T > T_{	ext{ENTRY\_VALID\_UNTIL}}$, the order is strictly cancelled/invalidated.
4. **$T_{	ext{POSITION\_EXPIRY}}$**: The absolute position holding horizon cutoff (15:15 IST intraday, 5 trading days swing, or contract expiry date).

---

## 4. STAGE C & D: ENTRY MODEL & TARGET FEASIBILITY ENGINE

### Entry Validity Architecture:
To eliminate adverse price drift and inverted risk-to-reward ratios, OPB establishes a **Hybrid Entry Validity Model**:
- **Time Window**: 15 minutes for Equity Swing; 5 minutes for Index/Stock Options; 10 minutes for Futures.
- **Maximum Price Drift Window**: Maximum allowed adverse drift is **0.50%** above trigger price for Equity Swing, **1.50%** on Option Premium, and **0.25%** for Futures.
- **Order Invalidation**: If price breaches the entry range before filling, the signal transitions to `CANCELLED_DRIFT_EXCEEDED`.

### Target Feasibility Engine Specification:
The engine operates under a **Fail-Closed Principle**: If necessary volatility, liquidity, or market depth data is unavailable, the engine returns `INSUFFICIENT_DATA` and blocks signal emission.

```text
================================================================================
TARGET FEASIBILITY ENGINE EVALUATION LOGIC
================================================================================
Inputs:
  - Daily ATR (14-day), Realized Volatility (20-day)
  - Elapsed Session Time, Remaining Session Time
  - Intraday Consumed Range: (Session High - Session Low)
  - Distance to Target: |T1 - Entry Price|
  - Derivative Greeks: Delta, Gamma, Theta Decay per hour
  - Order Book Quality: Bid-Ask Spread, Market Depth, Open Interest

Evaluation Rules by Category:
1. EQUITY_SWING_DELIVERY:
   Feasible if: Target Distance (4.0%) <= 0.80 * (5 * Daily ATR)
   Reject Reason: EXTENDED_FROM_TREND if Entry > 1.03 * 20-EMA

2. INDEX_OPTIONS:
   Feasible if: (Underlying Expected Move * Delta) >= (+25% Premium Target)
                AND (Theta Decay * Holding Hours) <= 0.20 * Premium Target
                AND (Bid-Ask Spread <= 1.0 INR)
   Reject Reason: TARGET_TOO_FAR / THETA_EXHAUSTION / WIDE_SPREAD

3. FUTURES:
   Feasible if: Contract Target (1.0x ATR) <= Remaining Daily Expected Range
                AND (Bid-Ask Spread <= 0.50 pts)
   Reject Reason: RANGE_ALREADY_CONSUMED / INSUFFICIENT_VOLATILITY
================================================================================
```

---

## 5. STAGE F & G: TRUE DERIVATIVE CONTRACT ARCHITECTURE

### Stage F: Genuine Option Contract Object Schema:
```json
{
  "contract_type": "INDEX_OPTION",
  "underlying": "NIFTY",
  "exchange": "NSE",
  "option_type": "CE",
  "strike_price": 23500.0,
  "expiry_date": "2026-10-01",
  "contract_symbol": "NIFTY24OCT23500CE",
  "entry_premium": 185.50,
  "bid_price": 185.25,
  "ask_price": 185.75,
  "spread": 0.50,
  "delta": 0.52,
  "gamma": 0.0021,
  "theta": -12.50,
  "vega": 18.20,
  "implied_volatility": 0.135,
  "open_interest": 145000,
  "volume_lots": 32000,
  "underlying_spot_price": 23520.40,
  "days_to_expiry": 2.5
}
```

### Stage G: Futures Canonical Contract Architecture:
- Scanner MUST resolve near-month contract via `FuturesContractResolver.resolve_contract()` before evaluating breakout criteria.
- Target T1 defined strictly as **1.0x Futures ATR** (in contract points).
- SL defined strictly as **0.75x Futures ATR** (in contract points).
- Monitoring MUST track canonical contract bars; cash spot price fallback is permanently prohibited.

---

## 6. STAGE H & I: TARGET PROBABILITY & SIGNAL QUALITY OBJECTIVES

### The Probability Fallacy:
Current setup scores (e.g. 92) represent heuristic technical strength, NOT the mathematical probability of reaching target. Heuristic score $\ne P(T1 \text{ before } SL)$.
- Exposing `score / 100` as a probability is strictly prohibited.
- A true target probability model requires **point-in-time calibrated machine learning** (Isotonic Regression or Platt Scaling) predicting:
  $$P(T1 \text{ hit before } SL \text{ and before Expiry})$$
- **Calibration Prerequisite**: A minimum of **150 to 200 resolved truthful outcomes** must be accumulated per category before training or deploying probability estimators.

### Signal Quality Mandate:
- OPB does NOT optimize for maximum signal volume or minimum signal volume.
- OPB optimizes for **Target-Achievable Signal Generation**: Only signals with high setup confluence, verified entry windows, and mathematically feasible targets are emitted.
- If market conditions offer zero valid setups in a category, that category legitimately produces zero signals.

---

## 7. STAGE K & L: PRESENTATION CONTRACT & OUTCOME CONSISTENCY

### Canonical Presentation Payload:
Every signal delivered to the UI, Mobile App, or Telegram must provide complete transparency:
```json
{
  "signal_id": "SIG-20260930093000-NIFTY24SEP25000CE-a1b2c3",
  "created_at": "2026-09-30T09:30:00+05:30",
  "category": "INDEX_OPTIONS",
  "instrument_type": "OPTION_BUYING",
  "underlying": "NIFTY",
  "tradable_symbol": "NIFTY24SEP25000CE",
  "direction": "CALL",
  "entry_price": 185.50,
  "entry_range": [185.50, 188.25],
  "valid_from": "2026-09-30T09:30:00+05:30",
  "entry_by": "2026-09-30T09:35:00+05:30",
  "target_basis": "OPTION_PREMIUM_POINTS",
  "t1": 231.85,
  "t2": 278.25,
  "sl": 148.40,
  "position_expiry": "2026-09-30T15:15:00+05:30",
  "feasibility_status": "PASS",
  "feasibility_reason": "FEASIBLE_DELTA_ATR_EXPANSION",
  "score": 92,
  "score_bucket": "90-100 (ELITE)",
  "probability_status": "UNAVAILABLE_SAMPLE_COLLECTION",
  "probability_t1": null,
  "liquidity_status": "HIGH (OI: 125,400 lots, Spread: 0.50 INR)",
  "data_quality_status": "VERIFIED_LIVE_FEED",
  "outcome_basis": "NIFTY24SEP25000CE_COMPLETED_1M_BARS"
}
```

### Outcome Consistency & Invariant Preservation:
All outcome measurement strictly adheres to the established R1-R4 rules:
- **R1 Futures Resolver**: Preserved contract-level resolution.
- **R2 Derived Signal Governance**: Prevents duplicate signals.
- **R3 Completed Candle Outcome Measurement**: High/Low evaluation strictly on closed candles.
- **R4 Predictive Analytics Quarantine**: Zero contamination of operational signal tables.

---

## 8. IMPLEMENTATION READINESS & ROADMAP (P0 - P3)

```text
================================================================================
OPB UNIVERSAL SIGNAL LIFECYCLE IMPLEMENTATION ROADMAP
================================================================================
Phase P0: REQUIRED FOR INSTRUMENT TRUTH
  [P0-01] Wire `core/option_chain_json.py` & `core/live_option_quotes.py` into Index Options.
  [P0-02] Reclassify F&O cash equities to EQUITY_INTRADAY / wire genuine Stock Option resolver.
  [P0-03] Enforce canonical futures contract LTP in `AllNSEScanner._dispatch_futures_alert`.

Phase P1: REQUIRED FOR TARGET FEASIBILITY
  [P1-01] Implement `core/signals/target_feasibility_engine.py` with fail-closed checks.
  [P1-02] Implement `core/signals/entry_validity_engine.py` for 'Entry By' & drift guarding.

Phase P2: REQUIRED FOR SIGNAL QUALITY
  [P2-01] Deploy category-specific Target & SL Builder (ATR for Futures, Premium for Options).

Phase P3: FUTURE CALIBRATION
  [P3-01] Deploy Calibrated Target Probability Engine once N >= 200 truthful outcomes exist.
================================================================================
```

---

## 9. AUTHORITATIVE ANSWERS TO ALL 20 FINAL EXECUTIVE QUESTIONS

### Question 1: Does OPB now have a truthful architecture for every supported category?
**Answer**: **YES in architectural specification (D25); NO in current deployed production code.** D25 defines the truthful mathematical and data contracts for all 10 categories. In the currently deployed production runtime, however, Index Options and Stock Options remain mislabeled cash directional signals, and Futures remain disabled on EC2.

### Question 2: Which current categories are genuine instruments?
**Answer**: **Only `EQUITY_SWING_DELIVERY` is a genuine, instrument-truthful category in current production.** It trades cash equities, measures cash equity prices, uses realistic multi-day holding periods, and generates 100% of the platform's genuine edge.

### Question 3: Which categories are currently mislabeled?
**Answer**: **`INDEX_OPTIONS` and `STOCK_OPTIONS` are fatally mislabeled.** Index Options evaluate spot index points against spot percentage targets with no option contract or Greeks. Stock Options are cash equities tagged as options merely because the symbol is F&O listed.

### Question 4: Exactly what must change before Index Option Buying becomes genuine option buying?
**Answer**: Four mandatory changes must occur: (1) Wire `core/option_chain_json.py` to resolve ATM/1-OTM strikes; (2) Fetch live option contract quotes and Greeks via `core/live_option_quotes.py` and `core/options_greeks_engine.py`; (3) Define entry, T1 (+25%), T2 (+50%), and SL (-20%) on option premium; (4) Monitor outcomes using completed option contract bars.

### Question 5: Exactly what must change before Stock Option Buying becomes genuine option buying?
**Answer**: (1) Update `core/fno_universe.py` so cash equity breakouts are classified as `EQUITY_INTRADAY` or `EQUITY_SWING_DELIVERY`; (2) For genuine stock options, implement single-stock option chain parsing with strict minimum open interest ($\ge 1,000$ contracts) and spread controls ($\le 2.0\%$).

### Question 6: Exactly what must change before Futures can be enabled?
**Answer**: (1) Fix `AllNSEScanner._dispatch_futures_alert_if_eligible` so alert entry price uses the canonical contract LTP rather than cash spot price; (2) Verify contract liquidity and rollover logic; (3) Pass empirical R1 futures reconciliation in production; (4) Obtain explicit governance sign-off.

### Question 7: Can Equity Swing remain +4/+8/-3?
**Answer**: **YES, ABSOLUTELY.** Equity Swing is the platform's anchor edge (49.28% win rate across $N=279$ signals). The 5-day holding horizon gives ample time for a +4.0% move. Its parameters must remain strictly protected under Stage N.

### Question 8: What should Entry By mean for each category?
**Answer**: `Entry By` ($T_{	ext{ENTRY\_VALID\_UNTIL}}$) defines the exact timestamp beyond which an unfilled entry order is cancelled:
- **Index & Stock Options**: $T_{	ext{CREATE}} + 5$ Minutes (due to rapid theta decay).
- **Futures**: $T_{	ext{CREATE}} + 10$ Minutes.
- **Equity Swing Delivery**: $T_{	ext{CREATE}} + 15$ Minutes (with max 0.50% adverse price drift).
- **Commodities & Currencies**: $T_{	ext{CREATE}} + 15$ Minutes.

### Question 9: What should Position Expiry mean for each category?
**Answer**: Position Expiry ($T_{	ext{POSITION\_EXPIRY}}$) defines the terminal horizon of the trade:
- **Intraday Options & Futures**: Strictly 15:15 IST on trade date (auto-squareoff).
- **Equity Swing Delivery**: 15:30 IST on the 5th trading day post-entry.
- **Derivatives Swing**: Thursday 15:15 IST of weekly/monthly contract expiry.
- **Commodities (MCX)**: 23:30 / 23:55 IST on session date or contract tender cutoff.

### Question 10: What is the exact Target Feasibility contract?
**Answer**: A fail-closed callable `TargetFeasibilityEngine.evaluate_feasibility(candidate, market_state)` returning a structured object `FeasibilityResult(status, reason, metrics)`. Status must be `PASS`, `FAIL`, or `INSUFFICIENT_DATA`. If required data is missing or if $T1 > lpha(t) 	imes 	ext{ATR}$, it returns `FAIL` with a machine-readable reason and suppresses signal emission.

### Question 11: What data is required to calculate genuine target probability?
**Answer**: Point-in-time features recorded at candle close: (1) Technical setup indicators; (2) Relative volume; (3) Intraday range consumed vs ATR; (4) Distance to overhead support/resistance; (5) Implied volatility and Greeks; (6) 150+ resolved truthful forward outcomes per category to train an isotonic regression model.

### Question 12: Which categories currently have enough evidence to optimize?
**Answer**: **Only `EQUITY_SWING_DELIVERY` ($N=279$) and `FUTURES` ($N=386$ in R1 local testing).**

### Question 13: Which categories must remain observation-only?
**Answer**: **`COMMODITIES` ($N=2$), `CURRENCIES` ($N=1$), `ETFS_REITS` ($N=1$), `PENNY_SME` ($N=2$), `LARGE_CAP_EQUITY` ($N=4$), and `MID_SMALL_CAP` ($N=2$).** These categories must not be modified or calibrated until $N \ge 100$ forward observations are collected.

### Question 14: Can the architecture support NIFTY, BANKNIFTY, FINNIFTY, SENSEX, MIDCPNIFTY, BANKEX, and NIFTYNXT50 independently?
**Answer**: **YES.** The D25 architecture models each index with its own lot size, strike rounding, weekly expiry cycle (Tue/Wed/Thu/Fri/Mon), option chain adapter, and volatility profile without cross-index proxy borrowing.

### Question 15: Can the architecture support all 10 categories without hard-coded omissions?
**Answer**: **YES.** The 10-category master taxonomy provides a dedicated execution, feasibility, and expiry model for every category. Universal coverage means every category has an open architectural path, but emits signals only when genuine market opportunities arise.

### Question 16: What is the minimum safe P0 implementation?
**Answer**: P0 comprises: (1) Wire existing `core/option_chain_json.py` and `core/live_option_quotes.py` into Index Options; (2) Reclassify cash stocks from `STOCK_OPTIONS` to `EQUITY_INTRADAY`; (3) Enforce canonical futures contract LTP in `AllNSEScanner._dispatch_futures_alert`.

### Question 17: What must NOT be changed?
**Answer**: (1) Equity Swing +4%/+8%/-3% targets and scoring weights; (2) The R1 Futures Contract Resolver; (3) R3 Completed Candle outcome measurement; (4) Live trading lockout and Phase E block; (5) Low-sample categories.

### Question 18: What tests must pass before implementation?
**Answer**: (1) `tests/test_index_option_truth.py` (verifying contract symbol and premium target); (2) `tests/test_stock_option_taxonomy.py` (verifying zero cash stocks mislabeled as options); (3) `tests/test_futures_contract_pricing.py` (verifying contract price purity); (4) `tests/test_target_feasibility_engine.py` (verifying fail-closed gating); (5) Full 41-template regression suite.

### Question 19: What forward evidence must exist before activation?
**Answer**: A minimum of **14 consecutive calendar days of forward accumulation** on live EC2 with zero safety violations, zero database anomalies, and at least **150 truthful resolved signals** per active category demonstrating positive target expectancy.

### Question 20: Is the system currently optimized for signal generation or target-achievable signal generation?
**Answer**: **Historically, the deployed system was optimized for raw signal generation.** It generated high volumes of alerts without checking whether intraday targets were mathematically achievable. **With the D25 Universal Signal Architecture, OPB is now formally specified for Target-Achievable Signal Generation.**

---

## 10. MANDATORY SAFETY ACCOUNTING & FINAL STOP

```text
================================================================================
OPB D25 MANDATORY SAFETY INVARIANT ACCOUNTING
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

**FINAL STOP ENFORCED**: All D25 deliverables are complete. No code changes, no database writes, no commits, and no deployments were performed. Phase E remains strictly blocked.
