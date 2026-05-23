# Runbook: Database Corruption Recovery

| Field | Value |
|-------|-------|
| Runbook ID | `RB-003` |
| Severity | HIGH |
| Category | Persistence / Data |
| Last Updated | 2026-05-22 |

## Trigger Condition
- `sqlite3.DatabaseError` or `sqlite3.DatabaseCorruptionError` in logs
- Health check reports DB size anomaly or integrity check failure
- `PRAGMA integrity_check` returns errors

## Expected Symptoms
- ERROR logs: "database disk image is malformed", "database corruption"
- Trade journal queries fail or return incomplete data
- ML tracker, OI snapshots, or trade journal DB unreadable
- Startup reconciliation fails

## Initial Diagnosis

### Step 1: Identify which database is corrupted
```bash
python -c "
import sqlite3
dbs = ['trades.db', 'trade_journal.db', 'ml_tracker.db', 'oi_snapshots.db']
for db in dbs:
    try:
        conn = sqlite3.connect(db)
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        print(f'{db}: {integrity}')
        conn.close()
    except Exception as e:
        print(f'{db}: ERROR - {e}')
"
```

### Step 2: Check backup availability
```bash
dir /b backups\ 2>nul || echo "No backups directory found"
dir /b data\ 2>nul || echo "No data directory found"
```

### Step 3: Check WAL and SHM files for corruption source
```bash
dir /b *.db-wal 2>nul
dir /b *.db-shm 2>nul
```

## Resolution Steps

### 1: Stop all writer processes
Ensure no other process has the DB open:
```bash
python -c "
import sqlite3
conn = sqlite3.connect('trades.db')
conn.execute('PRAGMA locking_mode = EXCLUSIVE')
conn.commit()
conn.close()
print('Lock acquired (all writers blocked)')
"
```

### 2: Attempt in-memory recovery via `.clone`
```bash
python -c "
import sqlite3
try:
    src = sqlite3.connect('trades.db')
    dst = sqlite3.connect('trades_recovered.db')
    src.backup(dst, pages=1000)
    dst.close()
    src.close()
    print('Backup completed successfully')
except Exception as e:
    print(f'Backup failed: {e}')
"
```

### 3: Run integrity check on recovered copy
```bash
python -c "
import sqlite3
conn = sqlite3.connect('trades_recovered.db')
ok = conn.execute('PRAGMA integrity_check').fetchone()[0]
conn.close()
if ok == 'ok':
    print('Recovered DB is clean')
    # Replace corrupted DB
    import shutil, os
    os.replace('trades.db', 'trades_corrupted_' + __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S') + '.db')
    shutil.copy('trades_recovered.db', 'trades.db')
    print('Recovered DB deployed')
else:
    print(f'Recovery failed: {ok}')
"
```

### 4: If recovery fails — use last known good backup
```bash
python -c "
import shutil, glob, os
backups = sorted(glob.glob('backups/trades_*.db'), reverse=True)
if backups:
    shutil.copy(backups[0], 'trades.db')
    print(f'Restored from {backups[0]}')
else:
    print('No backup found — starting fresh (data loss)')
"
```

### 5: Verify recovery
```bash
python -c "
import sqlite3
conn = sqlite3.connect('trades.db')
row_count = conn.execute('SELECT COUNT(*) FROM trade_log').fetchone()[0]
print(f'Trade log entries: {row_count}')
ok = conn.execute('PRAGMA integrity_check').fetchone()[0]
print(f'Integrity: {ok}')
conn.close()
"
```

### 6: If no backup exists — start with fresh DB
```bash
python -c "
import sqlite3, os
if os.path.exists('trades.db'):
    os.rename('trades.db', f'trades_unrecoverable_{__import__(\"datetime\").datetime.now().strftime(\"%Y%m%d_%H%M%S\")}.db')
conn = sqlite3.connect('trades.db')
conn.execute('CREATE TABLE IF NOT EXISTS trade_log (id INTEGER PRIMARY KEY)')
conn.commit()
conn.close()
print('Fresh database created — historical data lost')
"
```

## Verification
- [ ] `PRAGMA integrity_check` returns "ok" on all databases
- [ ] Trade count matches expected (or gracefully handled if fresh DB)
- [ ] System can start without errors
- [ ] Reconciliation passes (even with partial data)

## Escalation Path
1. **Level 1** — Operator on duty — 10 minutes
2. **Level 2** — Trading lead — 30 minutes
3. **Level 3** — DBA / System architect — 1 hour

## Postmortem Required
Yes, if data loss occurred or recovery required >1 hour.

## Related Runbooks
- RB-001: Broker Outage
- RB-004: Stale Market Data Feed
