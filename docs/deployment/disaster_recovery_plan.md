# Disaster Recovery Plan

## NSE Index Options Trading Platform — v2.53.0

| Detail | Value |
|--------|-------|
| **Document Owner** | Platform Engineering |
| **Classification** | Internal — Critical Infrastructure |
| **Last Updated** | 2026-05-30 |
| **RTO Target** | 15 minutes |
| **RPO Target** | 0 (zero data loss — WAL journal guarantee) |

---

## 1. Recovery Objectives

### Recovery Time Objective (RTO)
| Tier | Target | Scope |
|------|--------|-------|
| **Critical** | ≤ 5 min | Broker connection, risk engine, safety state |
| **High** | ≤ 15 min | Execution engine, order reconciliation, portfolio state |
| **Medium** | ≤ 60 min | ML models, dashboard, reporting |
| **Low** | ≤ 24 hr | Historical data rehydration, log archive |

### Recovery Point Objective (RPO)
| Data Store | RPO | Mechanism |
|------------|-----|-----------|
| `trades.db` (trade log) | 0 | Write-Ahead Intent Journal (WAL) + exactly-once certifier |
| `trader_state.json` | 0 | Atomic write + checksum validation |
| `trade_journal.db` (execution quality) | ≤ 1 sec | WAL mode + synchronous NORMAL |
| `ml_tracker.db` (ML predictions) | ≤ 5 sec | Batch flush on training cycles |
| `oi_snapshots.db` (OI history) | ≤ 5 sec | Batch flush every scan cycle |
| Config files (`config.json`, etc.) | 0 | Git-versioned; rollback via `git revert` |
| Logs | ≤ 60 sec | Buffered writes; loss non-critical |

---

## 2. Failure Scenarios & Recovery Procedures

### 2.1 Broker Outage

**Detection:**
- Circuit breaker trips (`broker.place_order` state → OPEN)
- Health checker reports unhealthy
- No ACK received within timeout window

**Immediate Response (within 30s):**
1. Circuit breaker blocks all new order submissions
2. Active orders enter MONITOR state (wait for ACK/fill/cancel)
3. System degrades to SIGNAL_ONLY mode (signals continue, no execution)
4. `_HARD_HALT` event NOT triggered (existing positions can be monitored)

**Recovery (within 5 min):**
- Broker failover manager attempts reconnect:
  1. Refresh auth token (if auth-expired)
  2. Re-establish WebSocket connection
  3. Reconcile open orders via `broker_truth_reconciliation`
  4. If primary broker down > 3 min: attempt failover to secondary broker (if configured)
- If failover succeeds: circuit breaker CLOSED, resume NORMAL mode
- If failover fails after 3 attempts: trip hard halt, notify admin via Telegram

**Post-Recovery:**
1. Run `python -m core.health_checker` to validate system health
2. Verify reconciliation output against broker positions
3. Resume normal operation if all checks pass

### 2.2 Auth Token Expiry

**Detection:**
- Broker adapter raises `AuthExpiredError` or `TokenException`
- Order submission returns 401/403

**Immediate Response (within 15s):**
1. Halt new order submissions (go SIGNAL_ONLY)
2. Initiate token refresh via token refresh service
3. Existing positions continue to be monitored

**Recovery (within 2 min):**
- Automatic token refresh via `core/token_refresh_service.py`
- If automatic refresh fails:
  1. Log CRITICAL alert
  2. Send Telegram notification to admin
  3. Prompt for manual TOTP re-authentication
- On successful refresh: verify new token works, resume NORMAL mode

### 2.3 Database Corruption

**Detection:**
- SQLite `OperationalError` or `DatabaseError` on write
- Integrity check failure (`PRAGMA integrity_check`)
- Checksum mismatch on `trader_state.json`

**Immediate Response (within 30s):**
1. Trip hard halt (capital preservation — fail closed)
2. Attempt emergency dump of in-memory state to JSON fallback
3. Log full corruption details to separate error log

**Recovery (within 15 min):**
1. Stop the application
2. Restore from latest backup: `data/` directory
3. Run integrity check: `python -c "import sqlite3; c=sqlite3.connect('trades.db'); print(c.execute('PRAGMA integrity_check').fetchall())"`
4. If backup unavailable: attempt WAL journal replay (`trades.db-wal`)
5. If WAL replay fails: use in-memory state dump (last resort)
6. Restart application in paper mode
7. Validate data consistency against broker records

**Prevention:**
- WAL journal mode enabled on all databases
- `PRAGMA synchronous = NORMAL` for write safety
- Periodic integrity checks via `core/health_checker.py`
- Backup schedule: every 6 hours during active trading

### 2.4 Stale Market Data Feed

**Detection:**
- Data freshness guard: last update > 30 seconds ago
- LTP sanity check: price deviation > 5% from previous tick
- YF bar fetch returns empty/stale data

**Immediate Response (within 5s):**
1. Halt new signal generation (go SIGNAL_ONLY)
2. Use last known valid price for existing position P&L calculation
3. Do NOT close positions based on stale data

**Recovery (within 2 min):**
- Attempt fallback data source (e.g., NSE API → Yahoo Finance → cached)
- If all sources stale: maintain SIGNAL_ONLY until fresh data received
- On data resumption: validate 3 consecutive fresh ticks before re-enabling signals

### 2.5 Network Outage (Total)

**Detection:**
- All outbound connections fail (broker, market data, Telegram)
- Socket timeouts on all external calls

**Immediate Response (within 30s):**
1. Trip hard halt if positions are open (capital protection)
2. Emergency dump of all in-memory state to local JSON
3. Attempt local-only operations (log, save state)
4. Positions cannot be closed or adjusted until network restored

**Recovery (within 15 min):**
- If network restored within 5 min: resume monitoring
- If network restored within 30 min: reconciliation required
- If network restored after 30 min: full reconciliation + position audit
- After any network recovery: run `python -m core.health_checker`

### 2.6 Application Crash

**Detection:**
- Process exits unexpectedly
- Watchdog thread (if active) detects hang
- Supervisor detects process down

**Immediate Response (within 10s):**
1. OS/container automatically restarts process
2. On restart: load state from `trader_state.json`
3. Reconcile open positions with broker

**Recovery (within 2 min):**
- Auto-restart via supervisord / Docker restart policy
- State recovery: `trader_state.json` → reconstruct open positions
- Broker reconciliation: reconcile state machine with actual broker state
- If recovery fails: trip hard halt, notify admin

### 2.7 Configuration Corruption

**Detection:**
- Config validation fails during bootstrap
- Schema validation fails
- Required keys missing

**Immediate Response (within 5s):**
1. Fall back to `index_config.defaults.json` (safe defaults)
2. Log CRITICAL config error
3. Do not start with invalid config

**Recovery (within 5 min):**
1. Restore from backup config file (`config.json.bak` or git)
2. Run `python scripts/validate_config_schema.py`
3. If no backup: use `config.template.json` + user reconfiguration
4. Re-deploy with validated config

### 2.8 ML Model Failure

**Detection:**
- Model loading fails (file not found, format error)
- Prediction returns NaN/Inf
- Feature mismatch (model trained with different features)

**Immediate Response (within 5s):**
1. Disable ML classifier (fall back to non-ML signal scoring)
2. Log warning with model version and feature count
3. Continue trading without ML signal enhancement

**Recovery (within 30 min):**
1. Repair model file from backup
2. Or retrain with current feature set
3. Validate predictions on historical data before re-enabling

---

## 3. Backup Procedures

### 3.1 Automated Backups

| Backup Type | Frequency | Retention | Target |
|-------------|-----------|-----------|--------|
| Database files | Every 6 hours | 7 days | `data/*.db` |
| Config files | On change (git) | Unlimited | `config/*.json` |
| State file | Every scan cycle | Last 10 | `trader_state.json` |
| Log files | On rotation (50MB) | 30 days | `logs/*.gz` |
| ML models | On retrain | Last 5 | `models/*.pkl` |

### 3.2 Manual Backup Procedure

```bash
# Full backup
python -c "
import shutil, datetime, os
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
backup_dir = f'backup_{ts}'
os.makedirs(backup_dir, exist_ok=True)
for f in ['trades.db', 'trade_journal.db', 'ml_tracker.db', 'oi_snapshots.db', 'trader_state.json']:
    if os.path.exists(f):
        shutil.copy2(f, f'{backup_dir}/{f}')
    if os.path.exists(f + '-wal'):
        shutil.copy2(f + '-wal', f'{backup_dir}/{f}-wal')
print(f'Backup created: {backup_dir}')
"
```

### 3.3 Backup Verification

Weekly automated verification via health checker:
1. Check database integrity: `PRAGMA integrity_check`
2. Verify backup files are non-empty
3. Validate state file checksum
4. Report results to admin via Telegram

---

## 4. Recovery Drills

### 4.1 Monthly Chaos Drill Schedule

| Week | Scenario | Procedure |
|------|----------|-----------|
| Week 1 | Broker outage | `tests/chaos/test_broker_outage.py` |
| Week 2 | DB corruption | `tests/chaos/test_db_corruption.py` |
| Week 3 | Auth expiry | `tests/chaos/test_auth_expiry.py` |
| Week 4 | Full restart mid-session | `tests/chaos/test_restart_mid_session.py` |

### 4.2 Drill Runbook

```bash
# Run all chaos tests
python -m pytest tests/chaos/ -v

# Verify system health after recovery
python -m core.health_checker

# Check reconciliation state
python -m core.execution.broker_truth_reconciliation --validate

# Generate drill report
python -m core.report_generator --drill-report
```

### 4.3 Post-Drill Checklist

- [ ] All chaos tests pass
- [ ] No residual state corruption
- [ ] State machine transitions are valid
- [ ] Reconciliation reports clean
- [ ] Circuit breaker resets correctly
- [ ] Telegram alerts fire correctly
- [ ] Health checker reports healthy

---

## 5. Communication Plan

### 5.1 Alert Severity Levels

| Level | Definition | Response Time | Channel |
|-------|------------|---------------|---------|
| **CRITICAL** | Capital at risk, halt required | Immediate | Telegram CRITICAL + SMS (if configured) |
| **HIGH** | Degraded operation, admin attention | ≤ 5 min | Telegram HIGH |
| **NORMAL** | Informational, no action needed | ≤ 30 min | Telegram NORMAL |
| **LOW** | Routine, next business day | ≤ 24 hr | Log only |

### 5.2 Escalation Chain

```
1. Automated recovery (0-2 min) — system handles automatically
2. Telegram notification (immediate) — admin alerted
3. Admin intervention (≤ 5 min) — manual recovery actions
4. Engineering escalation (≤ 30 min) — code/database repair
5. Platform halt (≤ 60 min) — full stop if recovery fails
```

### 5.3 Incident Report Template

After any DR event, file an incident report in `docs/incidents/YYYY-MM-DD-description.md`:

```markdown
# Incident Report: YYYY-MM-DD

## Summary
- **Date/Time:** YYYY-MM-DD HH:MM IST
- **Duration:** N minutes
- **Severity:** CRITICAL / HIGH / NORMAL
- **Impact:** Capital at risk? Positions affected? Data loss?

## Root Cause
[Description of what failed and why]

## Detection
[How the failure was detected]

## Response
[Timeline of actions taken]

## Recovery
[How the system was restored]

## Lessons Learned
[What went well, what could be improved]

## Action Items
- [ ] Fix #1
- [ ] Fix #2
```

---

## 6. Capacity & Resilience Planning

### 6.1 Redundancy Requirements

| Component | Redundancy | Failover Mechanism |
|-----------|------------|---------------------|
| Broker connection | Active-Passive | `core/broker_failover.py` — threshold + recovery window |
| Market data | Primary + Fallback | YF → NSE → cached |
| Database | Single instance (SQLite) | WAL journal for crash recovery |
| Config | Git-versioned | Template fallback on corruption |
| State file | Atomic writes | Checksum validation on restart |

### 6.2 Resource Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| Memory | 4 GB | 8 GB |
| CPU | 2 cores | 4 cores |
| Disk | 10 GB | 50 GB (SSD) |
| Network | 1 Mbps | 10 Mbps |

### 6.3 SLO Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Uptime (trading hours) | ≥ 99.9% | Health checker pings |
| Signal generation latency | ≤ 5 sec | Per-scan timing |
| Order submission latency | ≤ 2 sec | Broker ACK timing |
| Data feed staleness | ≤ 30 sec | Last update timestamp |
| Recovery time (broker outage) | ≤ 5 min | Time to resume NORMAL |
| Recovery time (crash) | ≤ 2 min | Time to reconcile state |

---

## 7. Prevention & Hardening

### 7.1 Automated Guards

| Guard | Purpose | Implementation |
|-------|---------|----------------|
| Circuit breaker | Blocks broker calls during failures | `core/circuit_breaker_service.py` |
| Data freshness guard | Blocks signals on stale data | `core/data_freshness_guard.py` |
| LTP sanity check | Rejects outlier fill prices | Inline in `enter_trade()` |
| Correlation guard | Blocks correlated entries | `core/correlation_guard.py` |
| Event calendar filter | Blocks entries on major events | `core/event_calendar.py` |
| Liquidity guard | Blocks entries with poor liquidity | `core/liquidity_guard.py` |

### 7.2 Monitoring & Observability

| Tool | Purpose | Frequency |
|------|---------|-----------|
| `core/health_checker.py` | Full system health | Every scan cycle + Sunday EOD |
| `core/live_readiness_checker.py` | Paper→LIVE gate | On startup |
| `core/telegram_engine.py` | Real-time alerts | Async on events |
| `core/metrics_exporter.py` | Prometheus metrics | Every 15 sec |
| Reviews: `docs/deployment/DEPLOYMENT_GUIDE.md` | Operational procedures | As needed |

---

## 8. Document Maintenance

| Activity | Frequency | Owner |
|----------|-----------|-------|
| DR drill execution | Monthly | Platform Engineering |
| DR plan review | Quarterly | Architecture Review |
| RTO/RPO validation | Quarterly | SRE Team |
| Backup restore test | Monthly | Operations |
| Contact list update | Quarterly | All |

---

*This disaster recovery plan must be reviewed and updated whenever significant architectural changes are made to the platform.*
