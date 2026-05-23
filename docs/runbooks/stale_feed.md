# Runbook: Stale Market Data Feed

| Field | Value |
|-------|-------|
| Runbook ID | `RB-004` |
| Severity | HIGH |
| Category | Market Data |
| Last Updated | 2026-05-22 |

## Trigger Condition
- LTP timestamp is >5 seconds old
- `data_freshness_guard` logs: "Stale data detected"
- `realtime_performance_monitor` reports feed_lag > threshold
- WebSocket disconnects and does not reconnect within 10 seconds

## Expected Symptoms
- Signal generation pauses (stale data guard blocks new entries)
- Existing positions continue to be monitored (positions use broker status, not LTP)
- ERROR logs: "Feed lagging", "Stale data", "WebSocket reconnecting"
- `GET /health` endpoint shows `data_freshness: STALE`

## Initial Diagnosis

### Step 1: Check feed lag
```bash
python -c "
from core.health_checker import HealthChecker
hc = HealthChecker({})
report = hc.run()
data = report.get('data_freshness', {})
print(f'Feed age: {data.get(\"max_age_seconds\", \"N/A\")}s')
print(f'Status: {data.get(\"status\", \"UNKNOWN\")}')
"
```

### Step 2: Check WebSocket status
```bash
python -c "
from core.kite_ticker_feed import get_ticker_status
status = get_ticker_status()
print(f'Ticker connected: {status.get(\"connected\", False)}')
print(f'Ticker tokens: {status.get(\"tokens\", 0)}')
"
```

### Step 3: Check Yahoo Finance fallback
```bash
python -c "
from core.yf_bar_fetch import fetch_latest_ltp
ltp = fetch_latest_ltp('NIFTY')
print(f'YF LTP: {ltp}')
"
```

## Resolution Steps

### 1: Trigger WebSocket reconnect
```bash
python -c "
from core.kite_ticker_feed import KiteTickerFeed
feed = KiteTickerFeed({}, {})
feed.reconnect()
print('WebSocket reconnection triggered')
"
```
Wait 10 seconds, then re-check feed lag.

### 2: If reconnect fails — switch to polling mode
```bash
python -c "
from core.mode_manager import ModeManager
mm = ModeManager({})
mm.set_data_source('POLLING')  # Switch from WS to REST polling
print('Switched to polling mode')
"
```

### 3: Verify Yahoo Finance fallback availability
```bash
python -c "
from core.yf_bar_fetch import fetch_yfinance_frames
df = fetch_yfinance_frames('^NSEI', interval='1m', period='1d')
if df is not None and len(df) > 0:
    print(f'YF fallback available: {len(df)} bars')
else:
    print('YF fallback unavailable')
"
```

### 4: If both WS and YF are down — emergency mode
```bash
python -c "
from index_app.index_trader_interface import set_execution_mode
set_execution_mode('SIGNAL_ONLY')
print('Switched to SIGNAL_ONLY — no new trades without market data')
"
```

### 5: Restart ticker feed completely
```bash
python -c "
from core.kite_ticker_feed import KiteTickerFeed
feed = KiteTickerFeed({}, {})
feed.stop()
feed.start()
print('Ticker feed restarted')
"
```

### 6: If feed remains stale >5 minutes — system restart
```bash
python -c "
from index_app.index_trader_interface import safe_restart
safe_restart(reason='Stale market data feed >5 minutes')
print('System restart initiated')
"
```

## Verification
- [ ] WebSocket connected and streaming ticks
- [ ] LTP timestamp is <2 seconds old
- [ ] Yahoo Finance fallback working as backup
- [ ] Signal generation resumed
- [ ] Health check reports data_freshness = FRESH

## Escalation Path
1. **Level 1** — Operator on duty — 5 minutes
2. **Level 2** — Data feed lead — 15 minutes
3. **Level 3** — Exchange connectivity team — 30 minutes

## Postmortem Required
No, unless feed outage >15 minutes during market hours.

## Related Runbooks
- RB-001: Broker Outage
- RB-002: Auth Token Expiry
