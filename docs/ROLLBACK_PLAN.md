# Rollback Plan — OPB Institutional Platform v2.53.0

**Generated:** 2026-06-20  
**Classification:** CRITICAL — Operations

---

## 1. Rollback Principles

1. **Safety first** — Never leave open positions unmonitored during rollback
2. **Data preservation** — Never overwrite trade/state data without backup
3. **Validate first** — Always verify rollback in paper mode before live
4. **Fail closed** — If rollback is uncertain, halt trading, not continue

---

## 2. Rollback Scenarios

### 2.1 Code Rollback (Software Regression)

**Trigger:** New deployment causes unexpected crashes, incorrect signals, or risk violations.

| Step | Action | Duration | Owner |
|------|--------|----------|-------|
| 1 | **HALT** all new entries: set `MANUAL_SIGNALS_ONLY=true` | Immediate | Operator |
| 2 | Square off existing positions via manual mode | 5–15 min | Operator |
| 3 | Save current state: `copy trader_state.json trader_state.json.pre_rollback` | 1 min | Operator |
| 4 | Checkout previous version: `git checkout release/v2.52.0` | 1 min | DevOps |
| 5 | Revert dependencies: `pip install -r requirements.txt` | 2 min | DevOps |
| 6 | Verify in paper mode: `python index_app/index_trader.py --paper --debug` | 5 min | DevOps |
| 7 | Restore state: `copy trader_state.json.pre_rollback trader_state.json` | 1 min | Operator |
| 8 | Restart in live mode | 1 min | Operator |

**Fallback:** If `git checkout` fails, use `git stash` + `git checkout` from a tagged release:
```bash
git stash
git checkout tags/v2.52.0
pip install -r requirements.txt
```

### 2.2 Config Rollback

**Trigger:** Invalid config values cause risk violations, signal failure, or startup errors.

| Step | Action | Duration |
|------|--------|----------|
| 1 | Restore previous config: `git checkout HEAD~1 -- config.json` | 1 min |
| 2 | Validate: `python scripts/validate_config_schema.py` | 30s |
| 3 | Soft-reload: `touch STOP_TRADING; restart` | 2 min |
| 4 | Verify signals in paper mode | 5 min |

**Config backup locations:**
- `config.json.bak` — Automatic backup on every config change
- `config_audit.jsonl` — Complete config change history

### 2.3 Database Rollback

**Trigger:** Data corruption, migration failure, or schema mismatch.

| Scenario | Action | Duration |
|----------|--------|----------|
| Schema migration failure | `python -c "from core.db_migration import rollback_last; rollback_last()"` | 1 min |
| Data corruption | Restore from backup: `copy trades.db.bak trades.db` | 1 min |
| WAL corruption | `python -c "from core.wal.journal import recover; recover()"` | 2 min |

**Database backup locations:**
- `trades.db.bak` — Last known-good backup
- `backups/trades_YYYYMMDD.db` — Daily backup
- `trader_state.json` — Session state (auto-saved)

### 2.4 Broker API Rollback

**Trigger:** Broker API breaking changes, auth failures, or rate limit violations.

| Step | Action | Duration |
|------|--------|----------|
| 1 | Switch to backup broker: set `BROKER_DRIVER: ANGEL` → `KITE` | 1 min |
| 2 | Or switch to paper mode: restart with `--paper` | 1 min |
| 3 | Fall back to manual-only: `MANUAL_SIGNALS_ONLY=true` | Immediate |
| 4 | Square off positions through backup broker | 5–15 min |

### 2.5 Infrastructure Rollback

**Trigger:** VM failure, disk full, network outage, or Docker crash.

| Scenario | Action | Duration |
|----------|--------|----------|
| Docker container crash | `docker compose restart opb` | 30s |
| VM unreachable | Failover to backup VM (requires DNS update) | 5 min |
| Disk 100% full | Delete rotated logs + run VACUUM | 2 min |
| Network outage | Continue in offline mode (cached data) | Auto |

---

## 3. Rollback Decision Tree

```
                                     ┌──────────┐
                                     │ Incident │
                                     └────┬─────┘
                                          │
                                    ┌─────▼──────┐
                                    │ Can trade   │
                                    │ continue?   │
                                    └─────┬──────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │                     │                     │
               ┌────▼────┐          ┌────▼────┐          ┌────▼────┐
               │ YES     │          │ UNSURE  │          │ NO      │
               │ (minor) │          │         │          │         │
               └────┬────┘          └────┬────┘          └────┬────┘
                    │                     │                     │
              ┌─────▼──────┐        ┌─────▼──────┐        ┌─────▼──────┐
              │ Set MANUAL │        │ HALT all    │        │ HALT all    │
              │ mode       │        │ entries     │        │ entries     │
              │ Continue   │        │ Monitor     │        │ Square off  │
              │ monitoring │        │ positions   │        │ positions   │
              └─────┬──────┘        └─────┬──────┘        └─────┬──────┘
                    │                     │                     │
              ┌─────▼──────┐        ┌─────▼──────┐        ┌─────▼──────┐
              │ Fix &      │        │ Investigate│        │ Rollback   │
              │ deploy     │        │ & test     │        │ immediately│
              │ fix        │        │ in paper   │        │ & restart  │
              └────────────┘        └────────────┘        └────────────┘
```

---

## 4. Rollback Automation

```bash
# Quick rollback to last-known-good version
python scripts/rollback.py --version v2.52.0

# Database rollback
python scripts/rollback.py --db --backup-file trades.db.bak

# Config rollback
python scripts/rollback.py --config --restore config.json.bak
```

### Rollback Script (`scripts/rollback.py`)

The rollback script performs:
1. **HALT** — Sets `_HARD_HALT` event to block all entries
2. **BACKUP** — Saves current state to `backups/pre_rollback_*`
3. **ROLLBACK** — git checkout, pip install, config restore
4. **VALIDATE** — Runs tests, verifies paper mode
5. **RESTART** — Removes HALT, restarts in paper mode

---

## 5. Rollback Testing Schedule

| Frequency | Test | Success Criteria |
|-----------|------|------------------|
| **Weekly** | Config rollback test | `python scripts/rollback.py --config --test` |
| **Monthly** | Code version rollback simulation | Rollback completes in <10 min |
| **Quarterly** | Full DR exercise | Rollback + recovery in <30 min |
| **Pre-release** | Rollback from new to old | All tests pass after rollback |

---

## 6. Rollback Contacts & Escalation

| Role | Name | Responsibility |
|------|------|---------------|
| **Primary operator** | On-call trader | Execute rollback steps 1-3 |
| **DevOps** | On-call engineer | Execute rollback steps 4-6 |
| **Authorizer** | Release manager | Authorize rollback for production |
| **Emergency override** | CTO | Authorize emergency shutdown |

### Escalation
1. Operator executes steps 1-3 immediately (no approval needed)
2. DevOps is paged for steps 4-6
3. Release manager is notified within 5 minutes
4. CTO is notified if rollback takes >15 minutes

---

## 7. Post-Rollback Actions

1. **Incident report** — Create postmortem in `docs/operations/postmortem_template.md`
2. **Root cause analysis** — Determine why rollback was needed
3. **Fix deployment** — Address root cause and redeploy
4. **Rollback drill** — Schedule practice rollback within 1 week
5. **Process improvement** — Update rollback plan based on lessons learned

---

## 8. Appendix: Rollback-Ready Checklist

Before every production deployment:
- [ ] `git tag` created for previous version
- [ ] Database backup exists (`trades.db.bak`)
- [ ] Config backup exists (`config.json.bak`)
- [ ] Rollback script tested: `python scripts/rollback.py --test`
- [ ] Paper mode verified working on current version
- [ ] All ~2,670 tests pass on current version
- [ ] Release notes document rollback instructions

---

*This rollback plan must be reviewed and updated before every production deployment. Every operator must be familiar with the rollback decision tree.*
