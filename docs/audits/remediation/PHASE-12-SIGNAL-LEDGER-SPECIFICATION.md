# 🏛️ OPB SUPER-PLATFORM: PHASE 12 PROSPECTIVE SIGNAL LEDGER SPECIFICATION

**Audit Standard**: Immutable Append-Only Signal Persistence  
**Storage Engine**: SQLite WAL mode (`data/signals.db` -> Table `signal_audit_ledger`)  

---

## 📋 1. SCHEMA DEFINITION

```sql
CREATE TABLE IF NOT EXISTS signal_audit_ledger (
    signal_id TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    timestamp_ist TEXT NOT NULL,
    instrument TEXT NOT NULL,
    exchange TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    direction TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    final_score INTEGER NOT NULL,
    score_components_json TEXT NOT NULL,
    market_regime TEXT NOT NULL,
    entry_reference REAL NOT NULL,
    stop_loss REAL NOT NULL,
    target_1 REAL NOT NULL,
    target_2 REAL NOT NULL,
    risk_reward REAL NOT NULL,
    estimated_cost_r REAL NOT NULL,
    human_action TEXT NOT NULL DEFAULT 'PENDING',
    outcome_5m_r REAL,
    outcome_15m_r REAL,
    outcome_30m_r REAL,
    outcome_60m_r REAL,
    outcome_eod_r REAL,
    mfe_r REAL,
    mae_r REAL,
    status TEXT NOT NULL
);
```
