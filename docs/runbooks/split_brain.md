# Runbook: Split Brain Detection

| Field | Value |
|-------|-------|
| Runbook ID | `RB-006` |
| Severity | CRITICAL |
| Category | Infrastructure / Consistency |
| Status | 🚧 **Skeleton — Full content needed before Phase 4** |
| Phase Required | Phase 4+ |

## Trigger Condition
Two instances of AD-KIYU detected accessing the same broker account simultaneously.

## Diagnosis
- Check all running processes: `ps aux | grep index_trader`
- Check Docker containers: `docker ps`
- Check all running terminals/sessions
- Verify broker session IDs for multiple active sessions

## Resolution
- **Immediate:** Kill all instances except one
- **Verify:** Check reconciliation for any duplicate orders
- **Contain:** Disable scheduler/Cron that auto-starts process
- **Fix:** Implement instance lock (DB advisory lock or file lock)
- **Recover:** Full reconciliation run to ensure no duplicate trades

## Runbook Status
⏳ **This runbook needs a detailed procedure before Phase 4 certification.**

## Related Runbooks
- RB-001: Broker Outage
- RB-003: DB Corruption
