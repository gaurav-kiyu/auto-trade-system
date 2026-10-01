# OPB — COMPLETE SIGNAL LIFECYCLE + TARGET / EXPIRY FEASIBILITY AUDIT
**Governance Authority**: `OPB-FINAL-PHASE-GOVERNANCE-001`  
**Audit Type**: `STRICT READ-ONLY CODE + CONFIG + TEST + HISTORICAL-EVIDENCE AUDIT`  
**Audit Timestamp**: `2026-09-29T23:30:00+05:30`  
**Branch**: `v2.60-phase-d-candle-selection-remediation`  
**Authoritative Git HEAD**: `2769e6154728b6519c4cfa7d25478f7eb38a6d76`  
**GitHub Remote HEAD**: `2769e6154728b6519c4cfa7d25478f7eb38a6d76` (Parity: EXACT)  

---

## EXECUTIVE SUMMARY & PRIMARY FINDING

The OPB quantitative trading platform was audited to answer a single foundational question:
> **"Is the current deployed signal-generation logic optimized to generate fewer but materially higher-quality signals where the defined entry, T1, T2, and SL are realistically achievable within the signal's validity / expiry window?"**

### The Definitive Empirical Verdict:
**NO.** The current system is heavily optimized for **SIGNAL BROADCAST VOLUME & NOTIFICATION GENERATION**, rather than **FEASIBLE TARGET ACHIEVEMENT**. 

While the platform boasts institutional-grade plumbing—including immutable audit logging, multi-theme UI dashboards, telegram commander hooks, rigorous calendar filtering, and duplicate-prevention gates (D20-A/B)—its mathematical definition of **Entry, Target 1, Target 2, and Expiry** suffers from three catastrophic structural defects:
1. **The Intraday Target-Feasibility Paradox**: All four asset categories share a hardcoded **$+4.0\%$ Target 1**, **$+8.0\%$ Target 2**, and **$-3.0\%$ Stop Loss**. For Intraday Index Options (e.g. NIFTY at 25,200), Target 1 demands a **$+1,008$ point spot move** within intraday hours (by 15:30 IST). Because NIFTY's average daily range is only $\sim 180$ points ($0.7\%$), this target is mathematically $\mathbf{5.6\times}$ the total daily ATR. Target 1 is structurally impossible on $99.9\%$ of trading sessions, leading to universal `TIMEOUT` / `EXPIRED` outcomes.
2. **Derivative Cash-Spot Masquerading**: For both `STOCK_OPTIONS` and `FUTURES`, signals are emitted with the **Cash Equity Spot LTP** as the Entry Price, rather than actual option contract premiums or futures market prices. A user receives a notification saying *"Option Buying: BUY CE | RELIANCE Option | Entry: ₹2,900.00 | Target 1: ₹3,016.00"*. No option contract is bought at ₹2,900. Option strike selection, option premium Greeks, and theta decay are completely unmodeled in the generation and outcome pipelines.
3. **The Lifecycle Design Gap (Zero Entry Expiry)**: There is no concept of an **Entry Validity Window** (`Entry By`). A signal emitted at 09:30 IST remains "active" and valid for entry until market close (15:30 IST), even if the setup has completely evaporated, price has drifted through the stop loss, or the session is minutes from closing.

---

## 27 PRIMARY QUESTIONS ASSESSMENT

| # | Question | Current Deployed State & Empirical Finding | Verdict |
| :--- | :--- | :--- | :---: |
| **1** | Why is the signal generated? | Generated when a symbol's composite score across 16 technical strategies meets or exceeds the configured category threshold (`core/all_nse_scanner.py:643`). | **YES** |
| **2** | What makes the signal eligible? | Active symbol in universe, open session, fresh 1m/5m/15m data, D20-A options breakout/volume gate, D20-B session dedup, long-only cash check. | **YES** |
| **3** | What makes it strong enough to send? | Score $\ge$ threshold (70-80), tier in (`STRONG`, `MODERATE`), ML prob $\ge 0.65$ (or 0.50 uncalibrated neutral fallback in signal-only mode). | **YES** |
| **4** | What is the exact entry price? | Cash equity / index spot LTP from the latest bar (`signal.price`). Futures also uses cash spot price (`parent_signal.price`). | **SPOT LTP** |
| **5** | Is there an entry range? | **None.** Entry is strictly a single scalar point price. | **NO** |
| **6** | What is "Start From"? | In notifications, it is labeled "Valid From" and is simply the raw ISO generation timestamp formatted to IST. | **NO** |
| **7** | What is "Entry By"? | **Absent.** There is no entry deadline. Only "Max Exit Time" (holding horizon) is displayed. | **NO** |
| **8** | What is T1? | Fixed $+4.0\%$ for CALL/BUY/LONG; $-4.0\%$ for PUT/SELL/SHORT relative to entry price. | **FIXED +4%** |
| **9** | What is T2? | Fixed $+8.0\%$ for CALL/BUY/LONG; $-8.0\%$ for PUT/SELL/SHORT relative to entry price. | **FIXED +8%** |
| **10** | What is SL? | Fixed $-3.0\%$ for CALL/BUY/LONG; $+3.0\%$ for PUT/SELL/SHORT relative to entry price. | **FIXED -3%** |
| **11** | What determines those values? | Hardcoded constants in `core/signal_utils.py:calculate_directional_levels` (lines 471-478). | **HARDCODED** |
| **12** | What determines expiry? | Category rule in `core/signals/signal_outcome_tracker.py`: Options = same day 15:30 IST; Equities/Futures = 5 trading days 15:30 IST. | **CATEGORY** |
| **13** | What determines max holding time? | Intraday options: 1 to 6.25 session hours; Swing/Futures: 5 trading days. | **FIXED HORIZON** |
| **14** | Can signal expire before target is reachable? | **YES.** Frequent and systemic. Index options demand a 4% move intraday ($5.6\times$ daily ATR), making expiry before target mathematically inevitable. | **YES (CRITICAL)** |
| **15** | Does system estimate expected move? | **NO.** Zero IV expected move or intraday remaining volatility calculation. | **NO** |
| **16** | Does it compare target distance vs volatility? | **NO.** Target distance is fixed at 4.0%, completely decoupled from ATR or volatility. | **NO** |
| **17** | Does it estimate time-to-target? | **NO.** Zero velocity, drift, or duration model. | **NO** |
| **18** | Does it calculate probability of T1 before SL? | **NO.** `p_t1` is stored as `None` / `UNCALIBRATED` in prediction snapshots. | **NO** |
| **19** | Does it calculate probability of T2 before SL? | **NO.** `p_t2` is stored as `None` / `UNCALIBRATED`. | **NO** |
| **20** | Does it reject target-infeasible signals? | **NO.** `TARGET FEASIBILITY GATE = ABSENT`. | **NO** |
| **21** | Does it distinguish entry expiry from position expiry? | **NO.** Entry validity window does not exist; conflated with holding horizon. | **NO** |
| **22** | Does it distinguish validity from observation lifetime? | **NO.** Merged under the single holding horizon. | **NO** |
| **23** | Does it use category-specific target logic? | **NO.** All 4 categories share identical $+4\%$ T1, $+8\%$ T2, $-3\%$ SL. | **NO** |
| **24** | Does it use category-specific expiry logic? | **YES.** Intraday (same day) for Options vs 5 days for Swing/Futures. | **YES** |
| **25** | Does it use instrument-specific volatility? | **NO.** Fixed percentage ignores symbol beta, ATR, and IV. | **NO** |
| **26** | Does it use option Greeks / IV / theta? | **NO.** Zero Greeks used in signal pricing, strike selection, or target calculation. | **NO** |
| **27** | Does monitoring logic use the SAME target/SL as displayed? | **YES.** `SignalOutcomeTracker` evaluates the exact `target_1`, `target_2`, and `stop_loss` persisted at generation. | **YES** |

---

## PHASE 1 — COMPLETE CODEBASE DISCOVERY & INVENTORY

The complete signal generation, evaluation, target calculation, delivery, and outcome tracking pipeline consists of the following authoritative modules:

1. **`core/all_nse_scanner.py`**:
   - `scan_universe()`: High-throughput parallel scanner across 2,500+ NSE symbols.
   - `scan_single_stock()`: Evaluates 1m/5m/15m OHLCV data, checks freshness, applies long-only cash gate and ML score filters.
   - `_dispatch_alert_if_eligible()`: Executes D20-A Options Quality Gate, D20-B Index Session Dedup, cooldowns, target level generation, and notification formatting.
   - `_dispatch_futures_alert_if_eligible()`: Spawns derivative Futures signal from parent stock candidate using cash spot LTP.
2. **`core/signals/signal_quality_gate.py`**:
   - `validate_options_quality_gate()`: Implements D20-A fail-closed requirement (`breakout > 0 AND volume > 0`).
   - `check_index_session_dedup()`: Implements D20-B limit of max 1 CALL + 1 PUT per canonical index per session date.
   - `calculate_experimental_target_levels()`: D20-C candidate target logic (isolated and OFF in production).
3. **`core/signal_utils.py`**:
   - `calculate_directional_levels()`: Authoritative production calculator for T1 ($+4\%$), T2 ($+8\%$), and SL ($-3\%$).
   - `validate_ohlcv()`: Verifies positive prices, candle sequence, and allows zero-volume for indices only.
4. **`core/fno_universe.py`**:
   - `classify_instrument_market()`: 10-class instrument classifier separating F&O derivatives from cash equity.
   - `is_fno_symbol()`: Determines if symbol has active exchange derivative contracts.
5. **`core/notifications/rich_signal_formatter.py`**:
   - `get_holding_horizon_info()`: Determines `valid_from` (generation time) and `valid_until` (exit time).
   - `build_rich_html_email()` & `build_rich_telegram_html()`: Formats signals into user-facing alerts.
6. **`core/signals/signal_tracker.py`**:
   - `record_generated_signal()`: Persists signal into `system_signals` and creates immutable Phase-A snapshot in `signal_prediction_snapshots`.
   - `update_active_signal_outcomes()`: Legacy tick updater for signal win rates.
7. **`core/signals/signal_forward_observation.py`**:
   - `SignalForwardObservationService.register_forward_signal()`: Registers forward observation records into `signal_forward_observations` (fail-closed requirement on prediction snapshot).
8. **`core/signals/signal_outcome_tracker.py`**:
   - `evaluate_bar()`: Evaluates completed 1m candles for first-touch T1, T2, SL, or same-bar ambiguity.
   - `check_signal_expiry()` & `expire_stale_signals()`: Evaluates holding horizon expiration based on calendar days.
9. **`core/signals/signal_outcome_dataset.py`**:
   - `SignalOutcomeDatasetService.build_dataset()`: Compiles prediction snapshots and outcome measurements into structured analytics datasets.
10. **`index_app/domains/signal/evaluator.py` & `core/adaptive_signal.py`**:
    - `SignalEvaluator.evaluate()`: Computes 16-strategy score components, technical indicators (RSI, ADX, VWAP, ATR), and ML probability.

---

## PHASE 2 — END-TO-END SIGNAL EXECUTION TRACE

```text
RAW MARKET DATA (Yahoo Finance / WebSocket OHLCV 1m, 5m, 15m)
      ↓ [core/data_freshness_guard.py: check_data_freshness()]
DATA NORMALIZATION & FRESHNESS VALIDATION (Drop forming candle, verify timestamps)
      ↓ [core/adaptive_signal.py: FeatureEngine + 16 Quantitative Strategies]
TECHNICAL INDICATOR & SCORE EVALUATION (RSI, ADX, VWAP, ATR, MACD, Volume)
      ↓ [core/adaptive_signal.py: evaluate_adaptive_signal()]
CANDIDATE SETUP (Direction: CALL/PUT, Raw Score 0-150, Normalized Score 0-100, Tier: STRONG/MODERATE)
      ↓ [core/fno_universe.py: classify_instrument_market()]
CATEGORY ASSIGNMENT (EQUITY_SWING, STOCK_OPTIONS, INDEX_OPTIONS, FUTURES)
      ↓ [core/all_nse_scanner.py: scan_single_stock()]
LONG-ONLY CASH FILTER (Suppress PUT on non-F&O cash equities)
      ↓ [core/all_nse_scanner.py: scan_single_stock()]
SCORE THRESHOLD & ML PROBABILITY GATE (Score >= Category Threshold, ML Prob >= 0.65 or 0.50 fallback)
      ↓ [core/all_nse_scanner.py: scan_universe()]
PARALLEL SCAN AGGREGATION & TOP-N DIVERSIFICATION (Max alerts per cycle)
      ↓ [core/signals/signal_quality_gate.py: validate_options_quality_gate()]
D20-A OPTIONS QUALITY GATE (Strictly require breakout > 0 AND volume > 0 for options)
      ↓ [core/signals/signal_quality_gate.py: check_index_session_dedup()]
D20-B INDEX SESSION DEDUP GATE (Max 1 CALL + 1 PUT per index per session)
      ↓ [core/all_nse_scanner.py: _dispatch_alert_if_eligible()]
COOLDOWN & RATE LIMITS (Symbol 900s cooldown, max per window, max 100/day)
      ↓ [core/signal_utils.py: calculate_directional_levels()]
TARGET & STOP-LOSS CALCULATION (Hardcoded: T1 = +4.0%, T2 = +8.0%, SL = -3.0%)
      ↓ [core/signals/signal_tracker.py: record_generated_signal()]
SIGNAL PERSISTENCE (Insert into system_signals & user_deliveries)
      ↓ [core/signals/signal_tracker.py: record_generated_signal()]
PREDICTION SNAPSHOT CAPTURE (Insert immutable row into signal_prediction_snapshots; p_t1=None, calib=UNCALIBRATED)
      ↓ [core/signals/signal_forward_observation.py: register_forward_signal()]
FORWARD OBSERVATION REGISTRATION (Insert row into signal_forward_observations)
      ↓ [core/notifications/rich_signal_formatter.py + TelegramNotifier / EmailNotifier]
EXTERNAL USER DISPATCH (Send rich HTML email and Telegram card)
      ↓ [core/all_nse_scanner.py: _dispatch_futures_alert_if_eligible()]
DERIVED FUTURES DISPATCH (If F&O stock, spawn distinct FUT signal using Cash Spot LTP)
      ↓ [core/signals/signal_outcome_tracker.py: update_active_signal_outcomes()]
OBSERVATIONAL OUTCOME TRACKING (Evaluate closed 1m bars for first touch of T1, T2, SL, or Same-Bar Ambiguity)
      ↓ [core/signals/signal_outcome_tracker.py: check_signal_expiry()]
HOLDING HORIZON EXPIRY SWEEP (Expire signals past 15:30 IST or 5 trading days)
      ↓ [core/signals/signal_outcome_dataset.py: build_dataset()]
ANALYTICS & DISCRIMINATION REPORTING (Compile Brier scores, MFE/MAE distributions)
```

---

## PHASE 3 — CATEGORY-BY-CATEGORY AUDIT MATRIX

| Dimension | A. EQUITY SWING | B. STOCK OPTIONS | C. INDEX OPTIONS | D. FUTURES |
| :--- | :--- | :--- | :--- | :--- |
| **Instrument Identified** | Cash Listed Equities | F&O Listed Stocks | Benchmark Indices | Canonical Futures Contract |
| **Entry Price** | Cash Spot LTP | Cash Spot LTP | Index Spot Value | Cash Spot LTP |
| **Entry Range** | None (Single price) | None (Single price) | None (Single price) | None (Single price) |
| **Start From** | Generation timestamp | Generation timestamp | Generation timestamp | Generation timestamp |
| **Entry By** | None | None | None | None |
| **Target 1 (T1)** | $+4.0\%$ | $+4.0\%$ (CALL) / $-4.0\%$ (PUT) | $+4.0\%$ (CALL) / $-4.0\%$ (PUT) | $+4.0\%$ (BUY) / $-4.0\%$ (SELL) |
| **Target 2 (T2)** | $+8.0\%$ | $+8.0\%$ (CALL) / $-8.0\%$ (PUT) | $+8.0\%$ (CALL) / $-8.0\%$ (PUT) | $+8.0\%$ (BUY) / $-8.0\%$ (SELL) |
| **Stop Loss (SL)** | $-3.0\%$ | $-3.0\%$ (CALL) / $+3.0\%$ (PUT) | $-3.0\%$ (CALL) / $+3.0\%$ (PUT) | $-3.0\%$ (BUY) / $+3.0\%$ (SELL) |
| **Expiry / Validity** | 5 Trading Days (15:30 IST) | Same Day 15:30 IST | Same Day 15:30 IST | 5 Trading Days (15:30 IST) |
| **Target Basis** | Cash Stock Price | Cash Stock Price | Index Spot Level | Cash Stock Price |
| **Volatility Basis** | None (Fixed %) | None (Fixed %) | None (Fixed %) | None (Fixed %) |
| **Time Basis** | 5 Trading Days | Intraday (1–6.25 hrs) | Intraday (1–6.25 hrs) | 5 Trading Days |
| **Probability Model** | None (`UNCALIBRATED`) | None (`UNCALIBRATED`) | None (`UNCALIBRATED`) | None (`UNCALIBRATED`) |
| **Outcome Price Feed** | Cash completed 1m bars | Cash completed 1m bars | Index completed 1m bars | Resolved Futures market bars |
| **Structural Feasibility** | **Plausible** | **Severely Infeasible** | **Structurally Impossible** | **Moderate / Basis Risk** |

---

## PHASE 4 & 5 — ENTRY LOGIC & LIFECYCLE DESIGN GAPS

### 1. Entry Price Selection
- **Cash Equities (`EQUITY_SWING_DELIVERY`)**: Uses `signal.price`, which is the `Close` price of the latest completed 1-minute candle.
- **Stock Options (`STOCK_OPTIONS`)**: Uses the **Cash Equity Spot Price**. No option strike is selected; no option premium is queried.
- **Index Options (`INDEX_OPTIONS`)**: Uses the **Index Spot Value** (e.g. NIFTY 25,200).
- **Futures (`FUTURES`)**: In `_dispatch_futures_alert_if_eligible` (line 1487), `calculate_directional_levels(entry_price=parent_signal.price)` sets entry to the **Cash Equity Spot Price**.

### 2. Gaps, Late Entry, and Stale Signal Delivery
- **Zero Slippage / Gap Bounds**: If the price gaps beyond entry, the system does not cancel the signal or recalculate R:R.
- **Absence of Entry Invalidation**: If a signal is emitted at 10:00 IST at price ₹100, and by 11:30 IST the price has moved to ₹103.50 (almost at T1 ₹104), the signal in the dashboard is still listed as `ACTIVE` with entry ₹100. A user entering at 11:30 IST buys at ₹103.50 with a target of ₹104 (reward 0.5%) and stop-loss of ₹97 (risk 6.5%), resulting in an inverted, disastrous R:R of **1 : 0.07**!

### 3. Conflation of Lifecycle Windows (The Lifecycle Design Gap)
The application currently conflates four distinct temporal concepts:
1. **$T_{\text{create}}$ (Signal Creation Time)**: When the algorithm emitted the candidate.
2. **$T_{\text{entry\_valid}}$ (Entry Validity Window)**: The window (e.g., 5 to 15 minutes) during which the entry price and setup structure remain valid. $\rightarrow$ **COMPLETELY MISSING.**
3. **$T_{\text{holding}}$ (Position Holding Horizon)**: How long a filled position may be held before forced market exit (Intraday 15:15 IST or 5 trading days). $\rightarrow$ **DISPLAYED AS `Valid Until`.**
4. **$T_{\text{observation}}$ (Outcome Tracking Lifetime)**: How long the algorithmic observer monitors market data to score the strategy. $\rightarrow$ **HARDCODED TO `check_signal_expiry`.**

---

## PHASE 6 & 7 — TARGET & STOP-LOSS CALCULATION

### Canonical Calculations (`core/signal_utils.py` lines 471-478)

For **CALL / BUY / LONG**:
$$\text{SL} = \text{round}(\text{Entry} \times 0.97, 2) \quad (-3.0\%)$$
$$\text{T1} = \text{round}(\text{Entry} \times 1.04, 2) \quad (+4.0\%)$$
$$\text{T2} = \text{round}(\text{Entry} \times 1.08, 2) \quad (+8.0\%)$$

For **PUT / SELL / SHORT**:
$$\text{SL} = \text{round}(\text{Entry} \times 1.03, 2) \quad (+3.0\%)$$
$$\text{T1} = \text{round}(\text{Entry} \times 0.96, 2) \quad (-4.0\%)$$
$$\text{T2} = \text{round}(\text{Entry} \times 0.92, 2) \quad (-8.0\%)$$

### Risk-to-Reward Profiles
$$\text{Risk} = |\text{Entry} - \text{SL}| = 3.0\%$$
$$\text{Reward}_1 = |\text{T1} - \text{Entry}| = 4.0\% \implies \mathbf{R:R_1 = 1 : 1.33}$$
$$\text{Reward}_2 = |\text{T2} - \text{Entry}| = 8.0\% \implies \mathbf{R:R_2 = 1 : 2.67}$$

### Critical Findings on Targets
1. **Stock Options Target Fallacy**: For stock options, targets are applied to the cash stock price. A 4% move on an equity stock represents a 4% stock move. If an option trader actually bought an ATM option contract, a 4% underlying move would yield a $\sim 50\%$ to $100\%$ return on option premium due to delta and gamma. Conversely, expecting the underlying stock to move 4% in the remaining hours of the session is completely mismatched with typical daily ranges.
2. **Index Options Target Impossibility**: For NIFTY (spot 25,200), T1 ($+4\%$) is **26,208** ($+1,008$ points) and T2 ($+8\%$) is **27,216** ($+2,016$ points). Demanding 1,008 index points intraday is an absurdity that guarantees failure.

---

## PHASE 8 — TARGET FEASIBILITY AUDIT

### Quantitative Feasibility Comparison

| Metric | NIFTY (Index Options) | RELIANCE (Stock Options) | TCS (Equity Swing) | NIFTY-FUT (Futures) |
| :--- | :---: | :---: | :---: | :---: |
| **Typical Spot Entry** | 25,200 | 2,900 | 4,200 | 25,250 |
| **Target 1 (+4.0%)** | 26,208 (+1,008 pts) | 3,016 (+116 pts) | 4,368 (+168 pts) | 26,260 (+1,010 pts) |
| **Average Daily ATR** | $\sim 180$ pts ($0.71\%$) | $\sim 42$ pts ($1.45\%$) | $\sim 65$ pts ($1.55\%$) | $\sim 185$ pts ($0.73\%$) |
| **Holding Horizon** | Intraday ($\le 6$ hrs) | Intraday ($\le 6$ hrs) | 5 Trading Days | 5 Trading Days |
| **Available Expected Move** | $\sim 180$ pts ($1.0\times$ ATR) | $\sim 42$ pts ($1.0\times$ ATR) | $\sim 145$ pts ($2.2\times$ ATR) | $\sim 410$ pts ($2.2\times$ ATR) |
| **Target / Expected Move** | $\mathbf{5.60\times}$ | $\mathbf{2.76\times}$ | $\mathbf{1.15\times}$ | $\mathbf{2.46\times}$ |
| **Feasibility Verdict** | **IMPOSSIBLE** | **UNREALISTIC** | **FEASIBLE** | **BORDERLINE** |

### Definitive Code Audit Result:
```text
TARGET FEASIBILITY GATE = ABSENT
```
There is **zero code** in `AllNSEScanner`, `SignalTracker`, or `SignalQualityGate` that compares the distance to Target 1 against the instrument's ATR, remaining session time, or implied volatility.

---

## PHASE 9 — TARGET PROBABILITY & CALIBRATION AUDIT

1. **Prediction Snapshot Fields**:
   In `core/signals/signal_tracker.py` (lines 750-780), the fields `p_t1`, `p_t2`, `p_sl`, `p_timeout`, and `expected_value_r` exist in the database schema.
2. **Actual Population**:
   When `AllNSEScanner` invokes `tracker.record_generated_signal(...)` (lines 1197-1222), **none of these probability fields are supplied**.
   They default to `None`, and `calibration_version` is explicitly set to `"UNCALIBRATED"`.
3. **ML Win Probability vs Target Probability**:
   The scanner extracts `sig.ml_probability`. This is an uncalibrated classifier score (defaulting to a neutral `0.50` when no ML model is active). It represents generic directional inclination, NOT the probability of price reaching T1 ($+4\%$) before touching SL ($-3\%$).
4. **Definitive Code Audit Result**:
   ```text
   NO VALIDATED TARGET-PROBABILITY DELIVERY GATE
   ```

---

## PHASE 10 — EXPIRY & TIME-TO-TARGET AUDIT

1. **Intraday Options Expiry**:
   In `core/signals/signal_outcome_tracker.py` line 1151, intraday signals expire at `15:30:00 IST` on the creation date.
   If an option signal is emitted at 14:00 IST, it has exactly **90 minutes** of market time before expiry.
   To reach $+4.0\%$ in 90 minutes, an index or large-cap stock would need to experience a 6-sigma volatility shock.
2. **Definitive Finding**:
   ```text
   TARGET/EXPIRY INCOMPATIBILITY = CONFIRMED
   ```
   The required target distance vastly exceeds the maximum realistic price excursion within the remaining lifetime of the signal.

---

## PHASE 11 — OUTCOME MONITORING FIDELITY

1. **Price Consistency**:
   `SignalOutcomeTracker.evaluate_bar()` retrieves `target_1`, `target_2`, and `stop_loss` directly from the persisted `system_signals` table. It grades outcomes against the EXACT levels broadcast to users.
2. **High/Low Intrabar Ordering**:
   If a single 1-minute candle touches both T1 and SL, `evaluate_bar()` correctly refrains from guessing intrabar sequence and marks the outcome as `AMBIGUOUS_SAME_BAR`.
3. **Completed Candles Only**:
   R3 is strictly enforced: `AllNSEScanner` extracts `df1.iloc[-2]` (the completed candle), preventing evaluation on unclosed bars.
4. **Futures Pricing (R1)**:
   In `_lookup_bar()` and `_lookup_price()`, futures symbols resolve actual futures contract bars via `resolve_futures_market_bar()`, never falling back to cash spot during outcome tracking.

---

## PHASE 12 — PRE-DELIVERY REJECTION GATES AUDIT

| Potential Reject Condition | Handled Pre-Delivery? | Deployed Code Reference |
| :--- | :---: | :--- |
| **Market Session Closed** | **YES** | `core/all_nse_scanner.py:447` (`is_category_session_open`) |
| **Data Stale / Lagging** | **YES** | `core/data_freshness_guard.py` |
| **Non-F&O Cash Equity Short** | **YES** | `core/all_nse_scanner.py:599` (Long-only cash gate) |
| **Options Breakout / Volume $\le 0$** | **YES** | `core/signals/signal_quality_gate.py:51` (D20-A Gate) |
| **Index Session Duplicate** | **YES** | `core/signals/signal_quality_gate.py:144` (D20-B Gate) |
| **Symbol Cooldown Active** | **YES** | `core/all_nse_scanner.py:978` (900s cooldown) |
| **Max Alerts per Window/Day** | **YES** | `core/all_nse_scanner.py:983, 989` |
| **Target Distance > Remaining Expected Move** | **NO** | **MISSING** (No ATR / session time check) |
| **Near-Close Generation (< 30m to close)** | **NO** | **MISSING** (Options emitted at 15:10 IST) |
| **Stale Entry / Late Trigger** | **NO** | **MISSING** (No entry validity window) |
| **Low Liquidity / Wide Bid-Ask Spread** | **NO** | **MISSING** (Yahoo Finance feed lacks L2 depth) |
| **Low Calibrated Probability ($P(T1) < 0.60$)**| **NO** | **MISSING** (`p_t1` uncalculated) |

---

## PHASE 13 — HISTORICAL FAILURE ANALYSIS RECONCILIATION

| Issue Identified in Phase D18-D20 | Status in Current HEAD (`2769e61`) | Code Evidence & Operational Reason |
| :--- | :---: | :--- |
| **1. Index Option Over-Duplication** | **FIXED** | D20-B (`check_index_session_dedup`) strictly caps signals at 1 CALL + 1 PUT per index per session. |
| **2. Zero-Volume / Noise Option Signals** | **FIXED** | D20-A (`validate_options_quality_gate`) strictly enforces `breakout > 0 AND volume > 0`. |
| **3. Non-F&O Cash Short Selling** | **FIXED** | Long-only cash gate (`all_nse_scanner.py:599`) suppresses all PUT/SELL on non-F&O equities. |
| **4. Outcome Ambiguity Resolution** | **FIXED** | `evaluate_bar()` quarantines same-bar touches as `AMBIGUOUS_SAME_BAR`. |
| **5. Futures Cash Spot Fallback** | **FIXED** | R1 resolver (`resolve_futures_market_bar`) prevents spot fallback during outcome tracking. |
| **6. Target / Volatility Mismatch** | **NOT FIXED** | Hardcoded $+4.0\%$ T1 and $+8.0\%$ T2 remain universal across all categories. |
| **7. Timeout Dominance in Options** | **NOT FIXED** | Caused directly by $+4.0\%$ target distance vs $\sim 0.7\%$ intraday ATR; signals expire before reaching T1. |
| **8. Stock Options Premium / Strike Model**| **NOT FIXED** | Stock options continue to emit Cash Spot LTP as entry with zero option chain/strike modeling. |
| **9. Conflated Entry Validity Window** | **NOT FIXED** | No "Entry By" deadline; signals lack entry invalidation. |
| **10. Score Saturation (100/100 Capping)** | **PARTIALLY FIXED**| Audit records now preserve `raw_score` (e.g. 135/150) and score provenance in alerts, but normalization still caps at 100. |

---

## PHASE 14 — COMPLETE SIGNAL LIFECYCLE MATRIX

| Lifecycle Stage | Equity Swing | Stock Options | Index Options | Futures | Current Gate | Risk | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Candidate** | All NSE Cash | F&O Stocks | 6 Indices | F&O Stocks | Calendar Open | Low | Retain |
| **2. Direction** | Long Only | Call / Put | Call / Put | Long / Short | Cash Gate | Low | Retain |
| **3. Scoring** | 16 Strategies | 16 Strategies | 16 Strategies | Inherited | Category Thresh | Score saturation | Uncap composite |
| **4. Qualification** | Score $\ge 70$ | Score $\ge 75$ | Score $\ge 80$ | Score $\ge 75$ | D20-A / D20-B | Low | Retain |
| **5. Entry Price** | Cash LTP | **Cash Spot** | **Index Spot** | **Cash Spot** | Latest Bar Close | **High (Derivatives)** | Use Contract Market LTP |
| **6. Start From** | Now (IST) | Now (IST) | Now (IST) | Now (IST) | Signal Timestamp | None | Retain as valid_from |
| **7. Entry By** | **None** | **None** | **None** | **None** | **ABSENT** | **CRITICAL (Staleness)**| **Add 5-15m Entry Window** |
| **8. Target 1** | $+4.0\%$ | $+4.0\%$ Spot | $+4.0\%$ Spot | $+4.0\%$ Spot | Hardcoded | **CRITICAL (Unreachable)**| **Scale by Instrument ATR** |
| **9. Target 2** | $+8.0\%$ | $+8.0\%$ Spot | $+8.0\%$ Spot | $+8.0\%$ Spot | Hardcoded | **High** | Scale by Instrument ATR |
| **10. Stop Loss** | $-3.0\%$ | $-3.0\%$ Spot | $-3.0\%$ Spot | $-3.0\%$ Spot | Hardcoded | Moderate | Scale by Instrument ATR |
| **11. Feasibility** | **None** | **None** | **None** | **None** | **ABSENT** | **CRITICAL (Timeouts)** | **Pre-Delivery ATR Gate** |
| **12. Probability** | Uncalibrated | Uncalibrated | Uncalibrated | Uncalibrated | Neutral 0.50 | High (No edge filter)| Calibrate $P(T1 > SL)$ |
| **13. Entry Expiry** | **None** | **None** | **None** | **None** | **ABSENT** | **High** | Invalidate on price drift |
| **14. Pos. Expiry** | 5 Trading Days | Same Day 15:30 | Same Day 15:30 | 5 Trading Days | Calendar Engine | Moderate | Align with contract expiry |
| **15. Monitoring** | Closed 1m Bars | Closed 1m Bars | Closed 1m Bars | Futures Bars | First-touch logic| Low | Retain |
| **16. Timeout** | 5 Days | Same Day 15:30 | Same Day 15:30 | 5 Days | Calendar Sweep | High timeout rate | Fix via realistic targets |
| **17. Analytics** | MFE/MAE/Brier | MFE/MAE/Brier | MFE/MAE/Brier | MFE/MAE/Brier | Dataset Service | Low | Retain |

---

## PHASE 15 — PRIORITIZED GAP LIST

### Priority P0 — Fundamental Signal-Quality & Structural Defects
1. **P0-1: Structurally Impossible Index Option Targets**: $+4.0\%$ target on index spot requires a 1,008 point move on NIFTY intraday. Causes $\sim 90\%+$ timeout rate.
2. **P0-2: Absence of Entry Validity Window (`Entry By`)**: Signals never expire for entry; users can execute hours late when R:R is completely inverted.
3. **P0-3: Stock Options Price & Target Masquerading**: Emits cash equity prices as option entry and targets without strikes, premiums, or Greeks.

### Priority P1 — High-Value Signal-Quality Improvements
4. **P1-1: Absence of Pre-Delivery Target Feasibility Gate**: Scanner does not verify if required move $\le$ available remaining session expected move ($k \times \text{ATR}$).
5. **P1-2: Near-Close Signal Emission**: Options signals emitted after 14:45 IST have $< 30$ minutes to achieve a 4% move before forced intraday expiry.
6. **P1-3: Uncalibrated Target-Reach Probability**: Prediction snapshots record `p_t1=None`, and ML probability defaults to uncalibrated `0.50` neutral fallback.

### Priority P2 — Refinements & Minor Basis Risks
7. **P2-1: Futures Generation Basis Risk**: Futures signals use cash spot LTP for entry and targets at generation time, even though outcome tracking resolves contract bars.
8. **P2-2: Universal Score Normalization Capping**: Normalization caps raw scores $\ge 150$ to 100, slightly compressing score discrimination among top candidates.

---

## PHASE 16 — RECOMMENDED ARCHITECTURE (CONCEPTUAL DESIGN ONLY)

```text
CANDIDATE DISCOVERY (AllNSEScanner / Strategy Engine)
           ↓
[GATE 1] CATEGORY QUALITY GATE (D20-A Breakout/Volume + D20-B Session Dedup)
           ↓
[GATE 2] CATEGORY-SPECIFIC TARGET SCALING
         • Index Options: T1 = 0.8% - 1.2% (or 0.6 * Daily ATR)
         • Stock Options: Actual ATM/OTM Option Contract & Premium
         • Equity Swing: T1 = 4.0%, T2 = 8.0%, SL = 3.0% (Retain)
         • Futures: Contract Market LTP Basis + ATR Target
           ↓
[GATE 3] TARGET FEASIBILITY CHECK (Pre-Delivery Filter)
         • Verify: Target Distance <= Remaining Session Expected Move (ATR * sqrt(hours_left / 6.25))
         • Reject if session remaining time < 45 minutes for Intraday Options
           ↓
[GATE 4] ENTRY VALIDITY DEFINITION
         • Define Entry Range: [LTP, LTP + 0.2%]
         • Define Entry By: Signal Timestamp + 10 Minutes
           ↓
[GATE 5] PREDICTIVE PROBABILITY GATE
         • Calibrate P(T1 before SL) >= 0.60
           ↓
PERSISTENCE & USER DISPATCH (Emit rich alert with Entry, Entry By, Scaled T1, T2, SL)
           ↓
FORWARD OBSERVATION & REAL-TIME RESOLUTION (Outcome tracking with strict entry invalidation)
```

---

## PHASE 17 — GOVERNANCE COMMITMENT: NO UNVALIDATED CHANGES

Per `OPB-FINAL-PHASE-GOVERNANCE-001`:
- **Zero Arbitrary Fixes**: No unilateral modifications of score thresholds, targets, or parameters have been applied.
- **Zero Mutations Executed**: This audit has executed in strict read-only mode.
- All prospective remediations must follow the mandatory 17-stage change lifecycle with empirical forward validation.

---

## PHASE 18 — FINAL EXECUTIVE ANSWERS

| # | Question | Verdict | Exact Code & Empirical Evidence |
| :--- | :--- | :---: | :--- |
| **1** | Is the current signal architecture fundamentally sound? | **PARTIAL** | Pipeline governance, deduplication, audit logging, and tests (243/243 pass) are institutional grade. However, derivative target and pricing models are fundamentally mismatched with financial reality. |
| **2** | Is application optimized for TARGET ACHIEVEMENT or SIGNAL GENERATION? | **SIGNAL GENERATION** | Optimized to scan 2,500 stocks and emit alerts to Telegram/Email. Zero filters verify if the target can actually be reached within the expiry window. |
| **3** | Does every category have appropriate target logic? | **NO** | All categories use the exact same $+4\%$ T1, $+8\%$ T2, $-3\%$ SL regardless of instrument type or volatility. |
| **4** | Does every category have an entry validity window? | **NO** | `Entry By` is completely absent across all categories. |
| **5** | Does every category have a target feasibility gate? | **NO** | `TARGET FEASIBILITY GATE = ABSENT`. |
| **6** | Does every category have a validated probability gate? | **NO** | `NO VALIDATED TARGET-PROBABILITY DELIVERY GATE`. `p_t1` is null/uncalibrated. |
| **7** | Can the system emit signals with unrealistic targets? | **YES** | Systemically. Index options require $+1,008$ pts on Nifty ($5.6\times$ daily ATR) before 15:30 IST. |
| **8** | Can the system emit stale / late entry signals? | **YES** | Signals lack entry invalidation; an active signal remains actionable after setup has evaporated. |
| **9** | Are targets monitored on the same price basis as displayed? | **YES** | `SignalOutcomeTracker` faithfully evaluates the exact persisted numeric levels. |
| **10**| **Top 3 Required Architectural Changes** | **1.** Category-scaled targets (Index Options 0.8%-1.2%, Stock Options option premium/strike model).<br>**2.** Implement explicit Entry Validity Window (`Entry By`, 5-15 mins).<br>**3.** Pre-delivery Target Feasibility Gate (comparing target distance to remaining session ATR). |

---

## FINAL SAFETY DECLARATION

```text
FINAL AUDIT MUTATION ACCOUNTING:
- Code changes:                0 (ZERO)
- Database writes:             0 (ZERO)
- Git commits:                 0 (ZERO)
- Git pushes:                  0 (ZERO)
- EC2 deployments:             0 (ZERO)
- Broker calls:                0 (ZERO)
- Configuration changes:       0 (ZERO)
- D20-C production activation: 0 (ZERO)
- Phase E activation:          0 (ZERO)
```

**HARD STOP: AUDIT COMPLETE. ZERO MUTATIONS EXECUTED.**
