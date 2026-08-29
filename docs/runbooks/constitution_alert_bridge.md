# Runbook: Constitution Alert Bridge Outage

| Field | Value |
|-------|-------|
| Runbook ID | `RB-015` |
| Severity | MEDIUM |
| Category | Governance |
| Last Updated | 2026-07-26 |

## Trigger Condition
- No constitution health alerts received for >2 hours during market hours
- `constitution_alert_bridge` log shows errors
- Dashboard intelligence summary shows `constitution_v4: error`
- Telegram/email alerts from constitution bridge stop arriving

## Expected Symptoms
- `ConstitutionAlertBridge` reports errors in logs
- `get_constitution_alert_bridge().get_stats()` shows `scheduler_running: false`
- No automatic notification when constitution health scores drop

## Initial Diagnosis

### Step 1: Check alert bridge status
```bash
python -c "
from core.constitution_alert_bridge import get_constitution_alert_bridge
bridge = get_constitution_alert_bridge()
stats = bridge.get_stats()
print(f'Enabled: {stats[\"enabled\"]}')
print(f'Scheduler running: {stats[\"scheduler_running\"]}')
print(f'Last check: {stats.get(\"last_check\", \"N/A\")}')
"
```

### Step 2: Check logs
```bash
grep "CAB\|constitution_alert_bridge" logs/*.log | tail -20
```

### Step 3: Run a manual check
```bash
python -c "
from core.constitution_alert_bridge import get_constitution_alert_bridge
bridge = get_constitution_alert_bridge()
result = bridge.check_and_alert()
print(f'Score: {result.overall_score}')
print(f'Status: {result.health_status}')
print(f'Alert sent: {result.alert_sent}')
print(f'Error: {result.error}')
"
```

## Resolution Steps

### 1: Restart the alert bridge scheduler
```bash
python -c "
from core.constitution_alert_bridge import get_constitution_alert_bridge, reset_constitution_alert_bridge
reset_constitution_alert_bridge()
bridge = get_constitution_alert_bridge()
bridge.start_scheduler()
print('Alert bridge scheduler restarted')
"
```

### 2: Check notification service
```bash
python -c "
from core.services.notification_service import NotificationService
ns = NotificationService()
print(f'Service status: {ns.get_service_status().value}')
print(f'Metrics: sent={ns.get_metrics().notifications_sent}, failed={ns.get_metrics().notifications_failed}')
ns.start()
"
```

### 3: Verify health check works standalone
```bash
python -c "
from core.constitution import get_validator
v = get_validator()
h = v.comprehensive_health_check()
print(f'Overall: {h[\"overall_score\"]}')
print(f'Categories: {h[\"total_categories\"]}')
print(f'Evidence: {h[\"total_evidence\"]}')
"
```

### 4: Force an alert test
```bash
python -c "
from core.constitution import get_validator
v = get_validator()
# Check alert bridge is responding
from core.constitution_alert_bridge import get_constitution_alert_bridge
bridge = get_constitution_alert_bridge()
result = bridge.check_and_alert()
print(f'Bridge check complete: score={result.overall_score}')
if result.alert_sent:
    print('Alert was sent')
else:
    print('No alert needed (health is healthy)')
"
```

## Verification
- [ ] `get_constitution_alert_bridge().get_stats()` shows `scheduler_running: true`
- [ ] Running `check_and_alert()` returns without error
- [ ] Constitution health data appears in dashboard intelligence summary
- [ ] Alert threshold can be tested by temporarily lowering `CONSTITUTION_WARN_THRESHOLD`

## Escalation Path
1. **Level 1** — Operator on duty — 15 minutes
2. **Level 2** — Governance team lead — 30 minutes
3. **Level 3** — System architect — 60 minutes

## Postmortem Required
Only if bridge is down for >1 hour during market hours.

## Related Runbooks
- RB-016: Constitution Self-Healing Bridge
- RB-013: Telegram Notification Outage
