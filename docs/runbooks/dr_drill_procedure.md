# Disaster Recovery Drill Procedure

**Version:** 1.0
**Last Updated:** 2026-06-26
**Target RTO:** < 5 minutes
**Target RPO:** < 1 minute

---

## 1. Prerequisites

Before running any DR drill, verify:

| Item | Check |
|------|-------|
| Supervisord installed | `supervisord --version` |
| Docker + docker-compose installed | `docker --version && docker-compose --version` |
| Backup databases exist | `ls -la backups/` or `python scripts/backup_databases.py --check` |
| Configuration files backed up | `ls -la config.json.backup.*` |
| Bot NOT in production live trading | Verify `EXECUTION_MODE != "production"` in config |
| All team members notified | Send `[DR DRILL]` message in team channel |

---

## 2. Drill Scenarios

### Scenario A: Process Crash (Supervisord Restart)

**Objective:** Validate supervisord auto-restart within 30 seconds.

**Steps:**

1. **Start monitoring:**
   ```bash
   # Terminal 1 - watch logs
   tail -f logs/opb.log | grep -i "restart\|crash\|error\|startup"
   
   # Terminal 2 - measure RTO
   python -c "
   import time, requests
   start = time.time()
   while True:
       try:
           r = requests.get('http://localhost:8765/api/system/health', timeout=2)
           elapsed = time.time() - start
           print(f'Recovered in {elapsed:.1f}s')
           break
       except:
           time.sleep(0.5)
   "
   ```

2. **Kill the process:**
   ```bash
   # Find the PID
   ps aux | grep index_trader
   
   # Kill it (simulates crash)
   kill -9 <PID>
   ```

3. **Verify recovery:**
   - Supervisord should restart within 5 seconds
   - Full startup sequence completes within 30 seconds
   - Health endpoint returns 200
   - Database connections are re-established
   - No data loss (RPO = 0 for in-memory state)

**Expected RTO:** < 30 seconds
**Recovery Method:** Automatic (supervisord autorestart)
**Risk Level:** Low — no external dependencies

---

### Scenario B: Full Service Restart (Docker Compose)

**Objective:** Validate docker-compose restart with state recovery under 5 minutes.

**Steps:**

1. **Take a pre-drill snapshot:**
   ```bash
   python scripts/backup_databases.py --retain 30
   cp trader_state.json trader_state.pre_drill.json
   cp config.json config.pre_drill.json
   ```

2. **Record pre-drill state:**
   ```bash
   python -c "
   from core.performance_metrics import load_trades
   trades = load_trades('trades.db')
   print(f'Pre-drill trade count: {len(trades)}')
   "
   ```

3. **Start RTO timer:**
   ```bash
   START_TIME=$(python -c "import time; print(time.time())")
   ```

4. **Stop and restart services:**
   ```bash
   docker compose down
   sleep 5  # simulate full outage
   docker compose up -d
   ```

5. **Poll for recovery:**
   ```bash
   python -c "
   import time, requests
   start = $START_TIME
   for i in range(60):
       try:
           r = requests.get('http://localhost:8765/api/system/health', timeout=2)
           if r.status_code == 200:
               elapsed = time.time() - start
               print(f'System recovered in {elapsed:.1f}s')
               print(f'Status: {r.json().get(\"status\")}')
               break
       except:
           pass
       time.sleep(5)
   else:
       print('FAILED: System did not recover within 5 minutes')
   "
   ```

6. **Verify data integrity:**
   ```bash
   python -c "
   from core.performance_metrics import load_trades
   trades = load_trades('trades.db')
   print(f'Post-drill trade count: {len(trades)}')
   
   from core.config_bootstrap import load_config
   cfg = load_config()
   print(f'Config keys: {len(cfg)}')
   print(f'Config valid: {cfg.get(\"BASE_CAPITAL\", 0) > 0}')
   "
   ```

**Expected RTO:** < 3 minutes (Docker images cached locally)
**Recovery Method:** `docker compose up -d`
**Risk Level:** Medium — requires Docker host

---

### Scenario C: Database Corruption

**Objective:** Validate recovery from SQLite database corruption.

**Steps:**

1. **Simulate corruption:**
   ```bash
   # Corrupt the trades database by truncating it
   dd if=/dev/urandom of=trades.db bs=1024 count=10 conv=notrunc
   ```

2. **Attempt recovery:**
   ```bash
   # SQLite's built-in recovery
   sqlite3 trades.db ".recover" | sqlite3 trades_recovered.db
   
   # If that fails, restore from backup
   python scripts/restore_databases.py --latest
   ```

3. **Verify integrity:**
   ```bash
   python -c "
   import sqlite3
   conn = sqlite3.connect('trades.db')
   try:
       cursor = conn.execute('SELECT COUNT(*) FROM trades')
       print(f'Database integrity OK - {cursor.fetchone()[0]} trades')
   except Exception as e:
       print(f'Database STILL corrupted: {e}')
       print('Restoring from backup...')
   finally:
       conn.close()
   "
   ```

**Expected RTO:** < 2 minutes (backup restore)
**Recovery Method:** SQLite `.recover` or backup restore
**Risk Level:** Medium — may lose recent trades

---

### Scenario D: Full Hardware/Node Failure

**Objective:** Validate complete rebuild on new hardware under 4 hours.

**Steps:**

1. **Prepare new node:**
   ```bash
   git clone <repository>
   cd opb_trading_bot
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Restore from off-site backup:**
   ```bash
   # Assuming backups are in cloud storage (S3/GCS/Azure Blob)
   aws s3 sync s3://opb-backups/production/ ./backups/
   
   # Restore databases
   cp backups/trades.db .
   cp backups/trade_journal.db .
   cp backups/ml_tracker.db .
   cp backups/oi_snapshots.db .
   cp backups/execution_state.db .
   ```

3. **Restore config:**
   ```bash
   # Restore from secret store (env vars or encrypted config)
   cp backups/config.json .
   export OPBUYING_DEFAULT_ADMIN_PASSWORD=$(aws secretsmanager get-secret-value --secret-id opb/admin-password --query SecretString --output text)
   ```

4. **Start services:**
   ```bash
   docker compose up -d
   ```

5. **Verify:**
   ```bash
   python scripts/verify_deployment.py --full
   ```

**Expected RTO:** < 4 hours (depends on backup download speed)
**Recovery Method:** Full rebuild from backups
**Risk Level:** High — requires off-site backup availability

---

## 3. Drill Schedule

| Frequency | Scenario | Responsible |
|-----------|----------|-------------|
| Weekly | A — Process Crash | Operations Team |
| Monthly | B — Full Restart | DevOps Team |
| Quarterly | C — DB Corruption | DBA / SRE |
| Annually | D — Full Node Failure | Infrastructure Team |

---

## 4. Post-Drill Checklist

After each drill, complete and sign off:

| Item | Status | Notes |
|------|--------|-------|
| RTO met? | [ ] Yes [ ] No | Actual: ___ seconds |
| RPO met? | [ ] Yes [ ] No | Data loss: ___ trades |
| No data corruption? | [ ] Yes [ ] No | |
| Config intact? | [ ] Yes [ ] No | |
| All services healthy? | [ ] Yes [ ] No | |
| Incident report filed? | [ ] Yes [ ] No | Link: ___ |
| Runbook updated? | [ ] Yes [ ] No | Changes: ___ |

---

## 5. Rollback Procedure

If a drill causes unexpected production impact:

1. **Stop the drill:**
   ```bash
   touch STOP_TRADING  # drops kill file
   python -c "from core.state_manager import trigger_hard_halt; trigger_hard_halt('DR drill rollback')"
   ```

2. **Restore pre-drill state:**
   ```bash
   # Restore databases from pre-drill backup
   python scripts/restore_databases.py --from-backup dr_drill_$(date +%Y%m%d)
   
   # Restore trader state
   cp trader_state.pre_drill.json trader_state.json
   
   # Restore config
   cp config.pre_drill.json config.json
   ```

3. **Restart:**
   ```bash
   docker compose restart
   ```

4. **Verify:**
   ```bash
   python scripts/verify_deployment.py --quick
   ```

---

## 6. Metrics Collection

Log all drill metrics to `docs/dr_drill_log.csv`:

```csv
date,scenario,rto_seconds,rpo_seconds,success,notes,engineer
2026-06-26,A,12,0,TRUE,Supervisord auto-restart passed,jdoe
```

---

*"Fail to plan, plan to fail." — Last updated 2026-06-26*
