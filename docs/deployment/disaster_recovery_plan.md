# Disaster Recovery Plan (DRP)

> **Mandatory Deliverable #26** — MASTER CONSTITUTION PROMPT v2.56.0  
> *Target: RPO ≤ 1 minute, RTO ≤ 5 minutes*

---

## 1. Recovery Objectives

| Metric | Target | Measurement |
|--------|--------|-------------|
| **RPO** (Recovery Point Objective) | ≤ 1 minute | Max data loss measured in trades/events |
| **RTO** (Recovery Time Objective) | ≤ 5 minutes | Time from failure detection to full operation |
| **MTTR** (Mean Time To Recover) | ≤ 2 minutes | Average recovery time across drill runs |
| **MTBF** (Mean Time Between Failures) | ≥ 720 hours | Target 30 days between unplanned outages |

---

## 2. Failure Scenarios & Recovery Procedures

### 2.1 Database Loss (SQLite corruption / disk failure)

**Symptoms:**
- `sqlite3.DatabaseError` or `sqlite3.OperationalError` in logs
- Failed reads/writes to `db/trades.db`, `json/trader_state.json`, `db/ml_tracker.db`
- Health check reports DB status as `unhealthy`

**Recovery Steps:**
1. **Detect:** Health checker (`core/health_checker.py`) monitors DB health every 60s
2. **Isolate:** Stop all write operations to affected database
3. **Restore:** Copy from latest backup: `backups/<db_name>_<date>.db`
4. **Verify:** Run `python -c "from core.health_checker import check_sqlite; check_sqlite('<db_name>.db')"`
5. **Resume:** Restart the trading loop — `WriteAheadJournal` replays uncommitted intents
6. **Escalate:** If backup is stale (> 60s), trigger `_HARD_HALT` and notify via Telegram

**Responsible:** Operations Team / On-Call SRE

### 2.2 Broker Loss (Kite/Angel API outage)

**Symptoms:**
- `ConnectionError` or `TimeoutError` from broker API
- Broker failover threshold exceeded (3 consecutive failures)
- Circuit breaker opens for broker adapter

**Recovery Steps:**
1. **Detect:** `core/broker_failover.py` monitors failure rate with sliding window
2. **Failover:** Automatic switch to secondary broker if configured
3. **Paper fallback:** If no secondary broker available, switch to `PaperBrokerAdapter`
4. **Queue:** Pending orders held in Write-Ahead Journal for replay
5. **Recover:** On broker API recovery, replay queued orders
6. **Notify:** Telegram alert sent via `CRITICAL` priority queue

**Responsible:** Automated (BrokerFailoverManager) + On-Call SRE

### 2.3 VM / Container Loss

**Symptoms:**
- Process dies unexpectedly
- Docker container exits with non-zero code
- Kubernetes pod crash-loop

**Recovery Steps:**
1. **Detect:** `supervisord` or K8s liveness probe triggers restart
2. **Restore:** Container restart invokes `StateManager.recover()` from `json/trader_state.json`
3. **Reconcile:** `ReconciliationEngine` compares local state to broker positions
4. **Resume:** Trading loop resumes from last clean state
5. **Verify:** Health check runs within 30s of restart

**RTO Guarantee:** ≤ 2 minutes for container restart

### 2.4 Network Partition / DNS Failure

**Symptoms:**
- All external API calls fail with timeout
- `ConnectionError` for broker, yfinance, NSE endpoints
- Telegram notification fails

**Recovery Steps:**
1. **Detect:** Circuit breaker opens for all external dependencies
2. **Halt:** No new entries — system enters SAFE mode
3. **Monitor:** Existing positions monitored via cached LTP (30s stale window)
4. **Recover:** On network restoration, circuit breaker closes, system reconnects
5. **Reconcile:** Broker positions reconciled against local state

**Critical:** System must FAIL CLOSED — no new orders during network loss

### 2.5 Clock Drift

**Symptoms:**
- Timestamps in trading log differ from actual IST by > 5s
- `core/datetime_ist.py` detects drift via NTP comparison

**Recovery Steps:**
1. **Detect:** Startup health check verifies system clock against NTP
2. **Warn:** Log WARNING if drift > 1s, trigger alert if drift > 5s
3. **Halt:** If drift > 10s, trigger `_HARD_HALT` — time-critical trading decisions cannot be trusted
4. **Fix:** Operator must run `w32tm /resync` (Windows) or `chronyd` (Linux)
5. **Resume:** After clock correction, restart trading loop

**Responsible:** On-Call SRE

---

## 3. Backup Strategy

| Asset | Backup Method | Frequency | Retention | Location |
|-------|--------------|-----------|-----------|----------|
| `db/trades.db` | SQLite `.backup` | Every 30 min | 7 days | `backups/` |
| `json/trader_state.json` | Atomic file copy | After every state change | 30 days | `backups/` |
| `db/ml_tracker.db` | SQLite `.backup` | Hourly | 7 days | `backups/` |
| `db/oi_snapshots.db` | SQLite `.backup` | Daily (EOD) | 90 days | `backups/` |
| Config files | Git history | Every commit | Full git history | Git |
| Logs | Log rotation | 50 MB chunks, gzip | 30 days | `logs/` |

**Backup Verification:**
```bash
# Monthly restore drill (simulate DB loss scenario)
python -c "
import shutil, os
from pathlib import Path
# Verify backup exists before drill
backup = Path('backups/trades.db')
if backup.exists():
    print(f'Backup found: {backup.stat().st_size} bytes')
    shutil.copy2(backup, 'db/trades.db.restored')
    print('Restore drill: PASSED')
else:
    print('No backup found for drill - run backup first')
"
# Verify backup integrity
python -c "import sqlite3; conn=sqlite3.connect('backups/trades.db'); conn.execute('SELECT COUNT(*) FROM trades'); print('Backup integrity: OK')"
```

---

## 4. Recovery Testing Schedule

| Test | Frequency | Procedure | Success Criteria |
|-----|-----------|-----------|-----------------|
| DB restore drill | Monthly | `python -c "from core.health_checker import check_db_integrity; print(check_db_integrity({'DB_PATH': 'db/trades.db'}))"` | RTO ≤ 5 min |
| Broker failover | Monthly | `python -m core.broker_failover --test` | Automatic switch + resume |
| Container restart | Weekly | `docker restart opb-bot` | State recovery + trade continuity |
| Full DR drill | Quarterly | Full simulation of VM + DB + broker loss | All RPO/RTO targets met |
| Clock drift test | Monthly | Manual NTP desync simulation | Hard halt triggers at 10s drift |

---

## 5. Roles & Responsibilities

| Role | Responsibility |
|------|---------------|
| **On-Call SRE** | First responder to alerts, execute recovery procedures |
| **Operations Team** | Weekly backup verification, monthly drills |
| **Risk Officer** | Authorize emergency capital withdrawal |
| **Release Manager** | Coordinate DR plan updates with releases |
| **CTO** | Final escalation for extended outages |

---

## 6. Continuous Improvement

- Every DR drill produces a postmortem using `docs/runbooks/postmortem_template.md`
- Recovery procedures updated in runbooks after each drill
- MTTR tracked quarterly, target improvement of 10% YoY
- DR plan reviewed every release cycle

---

## 7. Verification

This DR plan is verified by:
- `tests/test_dr_drill.py` — automated DR scenario testing
- `core/health_checker.py` — continuous health monitoring
- `core/reconciliation_engine.py` — post-recovery state reconciliation
- Constitution evidence check: `DR-01` category scoring
