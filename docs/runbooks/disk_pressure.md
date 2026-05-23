# Runbook: Disk Pressure

| Field | Value |
|-------|-------|
| Runbook ID | `RB-008` |
| Severity | MEDIUM |
| Category | Infrastructure / Storage |
| Status | 🚧 **Skeleton — Full content needed before Phase 4** |
| Phase Required | Phase 4+ |

## Trigger Condition
Disk free space < 10% or alert threshold configured in health_check_disk_warn_mb.

## Diagnosis
```bash
# Check disk space
df -h .
# Check log directory size
du -sh logs/
# Check DB sizes
ls -lh *.db
```

## Resolution
1. Run cleanup scheduler: `python -c "from core.data_governance import DataGovernor; DataGovernor({}).apply_all()"`
2. Archive old logs: move logs/archive/YYYY-MM-DD/
3. Check for unexpected large files: `find . -type f -size +100M`
4. Run SQLite VACUUM on large DBs: `python -c "import sqlite3; sqlite3.connect('trades.db').execute('VACUUM')"`
5. If critical (< 5%) → pause trading, inform operator

## Runbook Status
⏳ **This runbook needs a detailed procedure before Phase 4 certification.**

## Related Runbooks
- None standalone — data_governance module handles automated cleanup
