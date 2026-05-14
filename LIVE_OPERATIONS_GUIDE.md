# Live Operations Guide: Paper $\rightarrow$ Live Transition

## 1. Overview
This guide outlines the mandatory procedure for transitioning the OPB Index Options Bot from `PAPER` mode to `LIVE` execution.

**CRITICAL:** Live trading involves real financial risk. This transition must only be performed after the `LiveReadinessChecker` has issued a "READY" verdict and a human operator has manually approved the switch.

**Note:** This workspace is configured for a conservative live capital base of `BASE_CAPITAL = 5000` INR. The readiness thresholds below are intentionally tuned for this low-capital live deployment.

## 2. Pre-Flight Checklist (The "Gate")
Before switching to live, the following criteria must be met:

### A. Automated Readiness Check
Run the readiness checker:
```bash
python -m core.live_readiness_checker
```
**Blocking Criteria (Must be PASS):**
- **Min Paper Trades:** $\ge 50$ (Ensures statistical significance)
- **Win Rate:** $\ge 50\%$ (Ensures the strategy has a positive edge)
- **Profit Factor:** $\ge 1.3$ (Ensures wins meaningfully outweigh losses)
- **Max Drawdown:** $\le 15\%$ (Ensures risk profile is acceptable for ₹5,000 capital)
- **Trading Days:** $\ge 10$ (Ensures performance is consistent across different market days)

### B. Manual Audit
- [ ] Review the last 10 paper trades in `trades.db`.
- [ ] Verify that the `AdaptiveSignal` penalties are not suppressing too many valid signals.
- [ ] Confirm that the `AutoLearner` state is stable and not oscillating.
- [ ] Ensure the Broker API keys are correctly set in environment variables (`OPBUYING_KITE_API_KEY`, etc.).

## 3. Transition Procedure

### Step 1: Backup Current State
Backup the current `trader_state.json` and `config.json`.
```bash
cp config.json config.json.bak
cp trader_state.json trader_state.json.bak
```

### Step 2: Update Configuration
Change the execution mode in `config.json` or via environment variable:
- **Option A (Config File):** Set `"EXECUTION_MODE": "LIVE"`
- **Option B (Env Var):** `set OPBUYING_EXECUTION_MODE=LIVE` (Windows)

### Step 3: Start the Bot
Launch the bot and monitor the startup logs.
```bash
python index_app/index_trader.py
```
**Verify the following in logs:**
- `[CONFIG] Execution Mode: LIVE`
- `[BROKER] Connected to LIVE account`
- `[READINESS] Live Readiness Check: PASS`

## 4. Post-Live Monitoring (First 48 Hours)
During the first two days of live trading, the operator must:
1. **Monitor Slippage:** Compare live fill prices vs. paper mid-prices.
2. **Check Risk Limits:** Ensure `MAX_DAILY_LOSS` is strictly enforced.
3. **Audit Idempotency:** Verify no duplicate orders are being submitted.
4. **Daily Review:** At EOD, review the P&L and ensure it aligns with paper expectations.

## 5. Emergency Rollback
If unexpected behavior occurs (e.g., runaway orders, incorrect sizing):
1. **Immediate Halt:** Drop a file named `STOP_TRADING` in the project root.
2. **Revert Config:** Change `EXECUTION_MODE` back to `PAPER`.
3. **Restart Bot.**
