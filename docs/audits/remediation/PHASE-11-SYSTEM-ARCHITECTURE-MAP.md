# 🏛️ OPB SUPER-PLATFORM: PHASE 11 SYSTEM ARCHITECTURE MAP

**Audit Authority**: Independent Principal Quantitative Systems Auditor  
**Standard**: Full End-to-End Traceability Mapping  

---

## 🗺️ 1. END-TO-END DATA & SIGNAL FLOW

```text
1. MARKET DATA INGESTION
   ├── Sources: KiteConnect / SmartAPI / BlazeNet / CSV / Yahoo Feed
   └── Modules: core.data.market_data_feed, core.all_nse_scanner
         ↓
2. NORMALIZATION & PRE-GUARD VALIDATION
   ├── Verification: Timestamp alignment, tick validation, spread check
   └── Modules: core.quant.preguard_data_quality, core.datetime_ist
         ↓
3. FEATURE & INDICATOR COMPUTATION
   ├── Features: 1m/5m Deltas, VWAP distance, ATR, RSI, PCR, IV Rank
   └── Modules: core.feature_engine, core.market_calc, core.iv_rank
         ↓
4. MULTI-STRATEGY EVALUATION (16 MODULES)
   ├── Alpha Strategies: Momentum, Mean Reversion, Straddles, Condors
   └── Modules: core.pure_index_signal, core.strategy.*, core.straddle_strategy
         ↓
5. DETERMINISTIC SCORING & TIER CLASSIFICATION
   ├── Score Formula: S in [0, 100], Score >= 85 -> STRONG TIER
   └── Modules: core.pure_index_signal (compute_index_score), core.tier_engine
         ↓
6. RISK VETO & CIRCUIT BREAKER ARBITRATION
   ├── Gates: Expected Value >= +0.15R, Net R:R >= 1.0, Daily Loss Cap
   └── Modules: core.quant.risk_veto_engine, core.circuit_breaker
         ↓
7. SIGNAL GOVERNANCE & RATE LIMITING
   ├── Limits: User tier limits, category caps, daily/weekly frequency caps
   └── Modules: core.auth.user_signal_permissions, core.rate_limiting_service
         ↓
8. IMMUTABLE SIGNAL RECORDING & DISPATCH
   ├── Audit Ledger: Append-only SQLite persistence (data/signals.db)
   └── Modules: core.signals.signal_tracker, core.quant.signal_audit_record
         ↓
9. NOTIFICATION & AIR-GAPPED HUMAN REVIEW
   ├── Channels: Telegram Rich HTML, Email Digest, Enterprise Dashboard
   └── Modules: core.notifications.rich_signal_formatter, core.enterprise_dashboard
         ↓
10. DISCRETIONARY MANUAL BROKER EXECUTION
    └── Human trader inspects chart and manually enters order via Broker Terminal.
```
