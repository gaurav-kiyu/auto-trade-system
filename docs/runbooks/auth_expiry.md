# Runbook: Auth Token Expiry

| Field | Value |
|-------|-------|
| Runbook ID | `RB-002` |
| Severity | HIGH |
| Category | Auth / Broker |
| Last Updated | 2026-05-22 |

## Trigger Condition
- Broker API returns HTTP 401 / 403 or `TokenException` / `AuthException`
- `token_refresh_service` logs: "Token refresh failed", "Token expired"
- Health check reports auth_status = EXPIRED

## Expected Symptoms
- Order placement fails with auth error
- `TokenException` logged in execution service
- Market data feed may continue (WS auth separate from REST auth)
- Existing positions can still be monitored (position API uses different auth path)

## Initial Diagnosis

### Step 1: Check auth status
```bash
python -c "
from core.health_checker import HealthChecker
hc = HealthChecker({})
report = hc.run()
print(report.get('auth', 'Auth check not available'))
"
```

### Step 2: Verify token file / environment variable
```bash
python -c "
import os
print('KITE_API_KEY present:', bool(os.environ.get('KITE_API_KEY', '')))
print('KITE_ACCESS_TOKEN present:', bool(os.environ.get('KITE_ACCESS_TOKEN', '')))
print('OPBUYING_KITE_API_KEY present:', bool(os.environ.get('OPBUYING_KITE_API_KEY', '')))
"
```

### Step 3: Check token age
```bash
python -c "
from core.token_refresh_service import get_token_age
age = get_token_age('kite')
print(f'Token age: {age} hours')
"
```

## Resolution Steps

### 1: Attempt automatic token refresh
```bash
python -c "
from core.token_refresh_service import refresh_token
success = refresh_token('kite')
print(f'Token refresh: {\"SUCCESS\" if success else \"FAILED\"}')
"
```

### 2: If auto-refresh fails — check login session
Manual step: Log in to broker web interface and check if session is active.
For Zerodha Kite: https://kite.zerodha.com/
Generate new request token if needed.

### 3: Set new token via environment variable
```bash
export OPBUYING_KITE_ACCESS_TOKEN="new_token_here"
```

### 4: Retry connection
```bash
python -c "
from core.adapters.broker_adapters import create_broker_adapter
broker = create_broker_adapter({}, runtime_context={})
profile = broker.get_profile()
print(f'Connected as: {profile.get(\"user_name\", \"unknown\")}')
"
```

### 5: If refresh successful — verify order placement
```bash
python -c "
from core.adapters.broker_adapters import create_broker_adapter
broker = create_broker_adapter({}, runtime_context={})
# Place a minimal test order to verify auth works (will be cancelled)
order_id = broker.place_order('NIFTY', 'BUY', 1, 0, 'MARKET', {'tag': 'auth_test'})
print(f'Order placed: {order_id}')
# Cancel immediately
broker.cancel_order(order_id)
print('Order cancelled — auth is working')
"
```

### 6: If all refresh attempts fail — safe shutdown for re-auth
```bash
python -c "
from index_app.index_trader_interface import safe_shutdown
safe_shutdown(reason='Auth token expired and could not be refreshed')
print('System shut down safely — restart after manual re-auth')
"
```

## Prevention
- Set `access_token_refresh_interval_minutes` to 60 (refresh every hour)
- Monitor `token_refresh_service` logs for early warnings
- Keep broker login credentials in secure env vars (OPBUYING_* prefix)

## Verification
- [ ] Token refresh succeeds (auto or manual)
- [ ] Order placement works after refresh
- [ ] Market data feed reconnects if affected
- [ ] Health check reports auth_status = VALID

## Escalation Path
1. **Level 1** — Operator on duty — 5 minutes
2. **Level 2** — Trading lead — 15 minutes
3. **Level 3** — Broker support contact — 30 minutes

## Postmortem Required
Yes, if token expiry caused missed trades or required manual re-auth.

## Related Runbooks
- RB-001: Broker Outage
- RB-004: Stale Market Data Feed
