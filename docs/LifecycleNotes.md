# Application Lifecycle Notes

**Generated:** June 21, 2026  
**Status:** Complete

---

## Startup Sequence

```
1. Python Runtime Check        (3.10–3.19 enforced)
2. Environment Validation      (DEV/QA/PAPER/SHADOW/STAGING/PRODUCTION)
3. Config Load & Merge         (defaults → config.json → local → env)
4. Config Schema Validation    (index_config.defaults.json)
5. DI Container Wiring         (core/di_container.py)
6. Database Initialization     (trades.db, trade_journal.db, ml_tracker.db, oi_snapshots.db)
7. DB Schema Migration         (core/db_migration.py — PRAGMA user_version)
8. EventStore Initialization   (event_store.db with hash-chain)
9. State Recovery              (trader_state.json — capital, PnL, flags)
10. Broker Connection          (Paper → no SDK, Live → Kite/Angel)
11. Market Data Connection     (yfinance priority, NSE fallback)
12. Warmup Period              (bar collection before signal generation)
13. Trading Loop               (scan cycle begins)
```

## Shutdown Sequence

```
1. Kill Switch Check           (STOP_TRADING file or _shutdown event)
2. Position Monitoring         (continues until all positions closed)
3. State Persistence           (trader_state.json written)
4. EventStore Finalization
5. Graceful Disconnect         (broker, market data, WebSocket)
6. Process Exit
```

## Key Lifecycle Events

| Event | Trigger | Action |
|-------|---------|--------|
| Hard Halt | Loss breach or kill switch | Blocks all entries, monitors positions only |
| Soft Shutdown | SIGINT/SIGTERM or `--shutdown` | Graceful stop, position monitoring continues |
| Watchdog Reset | Loop hang > 30s | Kills and restarts scan loop |
| Expiry Gate | Expiry day cutoff time | Blocks new entries after cutoff |
| Session Open | 09:15 IST each trading day | Resets daily counters, checks market day |
| Session Close | 15:20 IST | Final position check, EOD reporting |

## Recovery After Crash

1. Read `trader_state.json` for last known capital + PnL
2. Query broker for open positions (if live mode)
3. Read EventStore for unconfirmed orders
4. Reconcile broker state with persisted state
5. Resume trading from last consistent state

## Sunday Maintenance

- Weekly health check (Sunday EOD)
- ML model retraining (if configured)
- Data retention cleanup (logs, audit, old models)
- OI snapshot database maintenance
