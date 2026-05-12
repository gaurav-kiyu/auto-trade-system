# 🗺️ Phased Migration & Rollback Plan v1.0
## Project: OPB Index Options Trading Platform

This document outlines the transition from the monolithic `index_trader.py` to the Hardened Modular Core.

## 1. Migration Strategy: The "Surgical Bridge"
Instead of a high-risk "Big Bang" rewrite, we implemented a **Strangler Fig Pattern** using **Proxy Objects**.

### The Bridge Mechanism:
- **State Bridge:** The legacy `S` (SessionState) object was replaced by a `StateProxy`. 
  - `S.capital` $\rightarrow$ `state_manager.get("capital")`
  - `S.net_daily_pnl = x` $\rightarrow$ `state_manager.set("net_daily_pnl", x)`
- **Position Bridge:** The `positions` dict was replaced by a `PositionProxy` that routes to the `OrderManager`.
- **Safety Bridge:** `_trip_hard_halt()` now routes directly to `risk_engine.trip_hard_halt()`.

## 2. Phased Rollout Sequence

| Phase | Component | Migration Action | Verification Method |
| :--- | :--- | :--- | :--- |
| **1.1** | **Time** | Replace `datetime.now()` $\rightarrow$ `time_provider.now()` | Log timestamp consistency check. |
| **1.2** | **State** | Replace `S` object $\rightarrow$ `state_manager` Proxy | Verify `trader_state.json` updates atomically. |
| **2.1** | **Broker** | Replace SDK calls $\rightarrow$ `broker_gateway` | Verify `Slippage` metrics in Prometheus. |
| **2.2** | **Orders** | Replace flags $\rightarrow$ `order_manager` State Machine | Verify `intent_id` prevents duplicate orders. |
| **3.1** | **Risk** | Replace inline checks $\rightarrow$ `risk_engine` | Trigger `MAX_DAILY_LOSS` and verify halt. |
| **4.1** | **ML** | Replace direct LGBM $\rightarrow$ `ml_inference` | Inject `NaN` feature $\rightarrow$ verify fallback. |

## 3. Rollback Strategy (The "Safety Net")

If a critical defect is found in a new module, the following rollback procedures must be followed:

### Level 1: Module Rollback (Low Risk)
If `ml_inference` fails:
- **Action:** Revert the `MLInferenceEngine` call in `index_trader.py` to the original `lgb.predict()` call.
- **Impact:** System loses regime-awareness and feature validation but regains basic prediction.

### Level 2: State Rollback (Medium Risk)
If `state_manager` corrupts the JSON:
- **Action:** 
  1. Stop Bot.
  2. Delete `trader_state.json`.
  3. Run `state_manager.recover_state_from_db()`.
  4. Revert `S` proxy to a plain `type("SessionState", ...)` object.

### Level 3: Full Core Rollback (High Risk)
If the "Surgical Bridge" causes systemic instability:
- **Action:** Restore `index_app/index_trader.py` from the last stable git commit (v2.42).
- **Impact:** System returns to the monolith. All new safety features (Atomic State, Order State Machine) are lost.

## 4. Verification Checklist
- [ ] `S.capital` updates are reflected in `trader_state.json` immediately.
- [ ] `time_provider` is used in all 4 critical paths (Signal, Risk, Order, Log).
- [ ] `broker_gateway` is the only module importing `kiteconnect`.
- [ ] `OrderManager` correctly identifies duplicate `intent_id`.
