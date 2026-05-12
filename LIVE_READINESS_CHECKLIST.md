# 🛡️ LIVE READINESS CHECKLIST (LRC) v1.0
## Project: OPB Index Options Trading Platform

This checklist is the FINAL GATE. No system may move from `PAPER_MODE=true` to `LIVE_BROKER_EXECUTION=true` unless every item is checked and signed off.

### 1. Foundation & Truth Layer
- [ ] **Unified Clock:** All `datetime.now()` calls replaced by `time_provider.now()`.
- [ ] **Atomic State:** `StateManager` implemented with atomic write-ahead logging.
- [ ] **DB Recovery:** Verified that `recover_state_from_db()` correctly restores positions after a simulated crash.
- [ ] **Config Validation:** System fails-fast on startup if `index_config.defaults.json` is malformed.

### 2. Broker & Execution Layer
- [ ] **Air Gap:** Zero broker-specific SDK imports found outside `core/adapters/`.
- [ ] **State Machine:** Orders follow the strict `NEW` $\rightarrow$ `VALIDATED` $\rightarrow$ `SUBMITTED` $\rightarrow$ `FILLED` flow.
- [ ] **Idempotency:** Verified that duplicate `intent_id` does not result in duplicate orders.
- [ la ] **Slippage Guard:** `BrokerGateway` correctly handles and logs slippage via `observability.py`.

### 3. Risk & Safety Perimeter
- [ ] **Hard Halt:** `_trip_hard_halt()` verified to block all entries immediately.
- [ ] **Daily Loss Gate:** `MAX_DAILY_LOSS` is enforced at the kernel level in `RiskEngine`.
- [ ] **Exposure Cap:** `PORTFOLIO_MAX_SL_RISK_PCT` prevents any single trade from over-leveraging.
- [ ] **VIX Scaling:** Position sizes are dynamically reduced when VIX > 25.

### 4. Intelligence & ML Layer
- [ ] **Inference Abstraction:** ML model is wrapped in `MLInferenceEngine`.
- [ ] **Fallback Logic:** Verified that `NaN` features trigger a safe fallback to technical signals.
- [ la ] **Regime Awareness:** Confidence scores are penalized during `HIGH_VOL` regimes.

### 5. Observability & Forensics
- [ ] **Prometheus:** `/metrics` endpoint is active and reporting `Slippage` and `Latency`.
- [ la ] **Heartbeat:** Telegram alerts fire if the background scanner hangs.
- [ ] **Audit Trail:** Every order transition is logged with a correlation ID.

---

## 🚀 FINAL REGRESSION SIMULATION (₹5000 LIVE TEST)
**Objective:** Validate the end-to-end pipeline with real money, minimal risk.

### Test Parameters:
- **Capital Allocation:** ₹5,000 (Strict Limit)
- **Max Trades:** 3-5 trades
- **Mode:** `AUTO_TRADING_ENABLED=false` (Manual Approval for each trade)
- **Sizing:** Minimum lot size only.

### Success Criteria:
1. **Intent $\rightarrow$ Fill:** Order is placed exactly once per approved signal.
2. **Risk Gate:** RiskEngine correctly calculates the ₹5000-capped position size.
3. **Slippage:** Actual fill price is within 0.5% of the signal price.
4. **Exit:** SL/TP is triggered and executed by the `OrderManager` without manual intervention.
5. **State:** `trader_state.json` and `trades.db` are perfectly aligned after the trade.

**SIGN-OFF:**
`__________________________` (Architect)  Date: `____________`
