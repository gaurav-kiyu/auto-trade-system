# Backup & Restore Procedures

## Backup Schedule

| Data | Frequency | Retention | Location |
|------|-----------|-----------|----------|
| Config files (json/config.json, json/stock_config.json) | Daily | 30 days | backups/config/ |
| Trade database (db/trades.db) | Daily | 90 days | backups/trades/ |
| Event store (db/event_store.db) | Daily | 30 days | backups/events/ |
| ML tracker (db/ml_tracker.db) | Weekly | 90 days | backups/ml/ |
| Trader state (json/trader_state.json) | Real-time | 7 days | backups/state/ |
| Logs | Weekly | 90 days | logs/archive/ |
| Full system snapshot | Monthly | 12 months | backups/full/ |

## Automated Backup

```bash
# Run all backups
python scripts/backup.py --all

# Backup specific items
python scripts/backup.py --config --trades --events
python scripts/backup.py --ml --state
python scripts/backup.py --logs
```

## Manual Backup

```bash
# Config backup
copy json/config.json backups/config/config.json.%DATE%
copy json/stock_config.json backups/config/stock_config.json.%DATE%

# Database backup
copy db/trades.db backups/trades/trades.db.%DATE%
copy db/event_store.db backups/events/event_store.db.%DATE%
copy db/ml_tracker.db backups/ml/ml_tracker.db.%DATE%

# State backup
copy json/trader_state.json backups/state/trader_state.json.%DATE%
```

## Restore Procedures

### Restore Config
```bash
copy backups/config/config.json.<date> json/config.json
```

### Restore Trade Database
```bash
# Stop trading
python index_app/index_trader.py --stop

# Restore DB
copy backups/trades/trades.db.<date> db/trades.db

# Restart in paper mode first
python index_app/index_trader.py --paper --verify
```

### Full System Restore
1. Restore config files
2. Restore databases
3. Restore state files
4. Start in paper mode
5. Run reconciliation
6. Verify P&L continuity
7. Run live readiness check
8. Switch to live mode

## Backup Verification
```bash
# Verify backup integrity
python scripts/verify_backup.py --check-all

# Check trade count
sqlite3 db/trades.db "SELECT COUNT(*) FROM trades"

# Verify P&L consistency
sqlite3 db/trades.db "SELECT SUM(net_pnl) FROM trades"
```
