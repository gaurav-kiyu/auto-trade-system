# System Recovery Procedure

## Recovery from Crash

1. **Assess Damage**
   ```bash
   # Check last known state
   cat json/trader_state.json
   
   # Check trades DB
   sqlite3 db/trades.db "SELECT COUNT(*), SUM(net_pnl) FROM trades WHERE ts > datetime('now', '-1 day')"
   
   # Check open positions
   python -m core.position_service --open
   ```

2. **Restart System**
   ```bash
   python index_app/index_trader.py --paper
   ```
   - System auto-recovers state from `json/trader_state.json`
   - WAL journal ensures no duplicate orders
   - Event store replays for reconciliation

3. **Verify Recovery**
   - Check that all open positions are accounted for
   - Verify P&L continuity (no gaps)
   - Confirm risk limits are re-applied
   - Check Telegram for recovery notification

## Recovery from Hardware Failure

1. **Restore latest backup**
   ```bash
   # Restore config
   copy backups\json/config.json.%DATE% json/config.json
   
   # Restore databases
   copy backups\db/trades.db.%DATE% db/trades.db
   copy backups\json/trader_state.json.%DATE% json/trader_state.json
   ```

2. **Start in paper mode first**
   - Verify data integrity
   - Check P&L reconciliation
   - Run live readiness check

3. **Switch to live** only after verification

## Recovery Time Objectives
- **RTO**: ≤ 5 minutes
- **RPO**: ≤ 1 minute
