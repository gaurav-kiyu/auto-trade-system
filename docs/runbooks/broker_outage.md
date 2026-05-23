# Runbook: Broker Outage — Unreachable / No ACK

| Field | Value |
|-------|-------|
| Runbook ID | `RB-001` |
| Severity | CRITICAL |
| Category | Broker / Execution |
| Last Updated | 2026-05-22 |

## Trigger Condition
Broker API returns connection error, timeout (>5s), or HTTP 5xx for 3 consecutive calls.

## Expected Symptoms
- `ERROR` logs: "Broker connection failed", "Broker timeout", "Failed to place order"
- Circuit breaker trips for the affected broker
- Positions may not update (stale state)
- `health_checker` shows broker status = UNREACHABLE

## Initial Diagnosis

### Step 1: Verify the symptom
```bash
python -m core.health_checker --format json | python -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('broker',{}), indent=2))"
```

### Step 2: Check broker failover state
```bash
python -c "
from core.broker_failover import BrokerFailoverManager
mgr = BrokerFailoverManager({})
print(mgr.get_status())
"
```

### Step 3: Check system state
```bash
python -c "
from index_app.index_trader_interface import get_system_state
print(get_system_state().get('execution_mode'))
"
```

## Resolution Steps

### 1: Verify network connectivity
```bash
curl -s -o /dev/null -w "%{http_code}" https://api.kite.trade/health
```
- If HTTP 200: broker is healthy, issue may be auth-related → proceed to Step 3
- If connection refused: proceed to Step 2

### 2: Trigger broker failover
If primary broker is unreachable and a secondary broker is configured:
```bash
python -c "
from core.broker_failover import BrokerFailoverManager
mgr = BrokerFailoverManager({})
mgr.failover('kite')  # or current primary
print('Failover triggered. New active broker:', mgr.get_active_broker())
"
```
After failover, verify paper mode is NOT active for live execution.

### 3: Refetch auth token
```bash
python -c "
from core.token_refresh_service import refresh_token
refresh_token('kite')
print('Token refreshed')
"
```

### 4: Restart broker feed
```bash
python -c "
from core.kite_ticker_feed import KiteTickerFeed
feed = KiteTickerFeed({}, {})
feed.reconnect()
print('Feed reconnected')
"
```

### 5: Verify recovery
```bash
python -m core.health_checker --format json
```
- Broker status should be ONLINE or RECOVERED
- Position reconciliation should be consistent

### 6: If still unreachable after 15 minutes
Switch to SIGNAL_ONLY mode to prevent trades without broker connectivity:
```bash
python -c "
from index_app.index_trader_interface import set_execution_mode
set_execution_mode('SIGNAL_ONLY')
print('Switched to SIGNAL_ONLY mode')
"
```

## Verification
- [ ] Broker health endpoint returns HTTP 200 (or equivalent)
- [ ] `health_checker` reports broker as ONLINE
- [ ] Position reconciliation shows zero mismatch
- [ ] Paper mode is NOT active if live trading
- [ ] Circuit breaker is reset

## Escalation Path
1. **Level 1** — Operator on duty — 5 minutes
2. **Level 2** — Trading lead — 15 minutes
3. **Level 3** — System architect — 30 minutes

## Postmortem Required
Yes, if outage exceeds 15 minutes or results in skipped trades.

## Related Runbooks
- RB-002: Auth Token Expiry
- RB-003: Database Corruption Recovery
