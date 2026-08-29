# Runbook: Data Provider Outage — yfinance / Yahoo Finance Unreachable

| Field | Value |
|-------|-------|
| Runbook ID | `RB-014` |
| Severity | CRITICAL |
| Category | Data / Market Feeds |
| Last Updated | 2026-07-18 |

## Trigger Condition
yfinance (Yahoo Finance) returns empty data, HTTP errors, or stale prices for 3 consecutive polling cycles.

## Expected Symptoms
- `ERROR` logs: "yfinance fetch failed", "Empty bars returned", "Stale LTP detected"
- Signal generation stops (no data → no signals → no trades)
- `health_checker` shows data provider status = UNREACHABLE or DEGRADED
- Dashboard shows stale price data (last update > 60 seconds)
- NSE feed (if configured) may still be working independently

## Initial Diagnosis

### Step 1: Verify yfinance reachability
```bash
python -c "
import yfinance as yf
nifty = yf.Ticker('^NSEI')
hist = nifty.history(period='1d')
print('Last price:', hist['Close'].iloc[-1] if not hist.empty else 'EMPTY')
"
```
- If empty data: yfinance/yahoo is down or rate limited → proceed to Resolution
- If valid price: issue may be specific to the polling code → check logs for errors

### Step 2: Check data provider health
```bash
python -c "
from core.health_checker import run_full_health_check
import json
report = run_full_health_check({})
providers = report.get('data_providers', {})
print('Total:', providers.get('total', 0))
print('Connected:', providers.get('connected', 0))
print('Status:', providers.get('status', 'UNKNOWN'))
"
```

### Step 3: Check LTP cache staleness
```bash
python -c "
from core.ltp_resolver import get_ltp_cache
cache = get_ltp_cache()
print('NIFTY:', cache.get('NIFTY', 'No data'))
print('BANKNIFTY:', cache.get('BANKNIFTY', 'No data'))
print('Cache age (s):', cache.get('_last_update_age', 'N/A'))
"
```

### Step 4: Check fallback data sources
```bash
python -c "
from core.data_freshness_guard import DataFreshnessGuard
guard = DataFreshnessGuard({})
status = guard.check_all()
for provider, info in status.items():
    print(f'{provider}: {\"OK\" if info[\"healthy\"] else \"STALE\"} (age={info.get(\"age\", \"N/A\")}s)')
"
```

## Resolution Steps

### 1: Wait for automatic retry
yfinance fetches have built-in retry logic (3 attempts with exponential backoff).
Check if retry is still in progress:
```bash
tail -20 logs/opbuying_*.log | grep -i "yfinance\|yf_retry\|data_fetch"
```

### 2: Switch to alternative data provider
If yfinance is down but NSE direct or broker API are available, the system uses data source priority:
1. **yfinance** (default, free)
2. **NSE direct** (requires NSE session — currently blocked by Akamai)
3. **Broker API** (requires broker account — Kite Connect WebSocket)

Force a specific data source:
```bash
# Restart with data source override
export OPBUYING_DATA_SOURCE=broker   # or nse, yfinance
python index_app/index_trader.py --paper
```

### 3: Use cached data if available
The LTP cache (`core/ltp_resolver.py`) retains the last known prices:
```bash
python -c "
from core.ltp_resolver import force_cache_read
data = force_cache_read()
if data:
    print('Using cached LTP data:', len(data), 'symbols')
else:
    print('No cached data available')
"
```

### 4: Restart the data polling loop
```bash
python -c "
from index_app.index_trader_interface import restart_data_polling
restart_data_polling()
print('Data polling restarted')
"
```

### 5: Run in signal-only mode (no live prices)
If data is completely unavailable but you want the bot to keep running:
```bash
# The bot will use last known prices for position monitoring
# But will NOT generate new signals
python -c "
from index_app.index_trader_interface import set_execution_mode
set_execution_mode('SIGNAL_ONLY')
print('Switched to SIGNAL_ONLY mode - no new signals')
"
```

### 6: Switch to BROKER data feed (if available)
If a broker API is configured and the WebSocket feed is active:
```bash
python -c "
from core.kite_ticker_feed import KiteTickerFeed
feed = KiteTickerFeed({}, {})
print('Feed active:', feed.is_connected())
print('Tokens:', feed.get_active_tokens())
"
```

### 7: If still down after 15 minutes
Yahoo Finance data outages are rare but can last hours. Plan accordingly:
- If broker feed is available → switch to broker-only mode
- If no alternative data source → stop the bot to prevent stale-price trading
```bash
# Emergency stop if no reliable data
python -c "
from core.safety_state import trip_hard_halt
trip_hard_halt('Data provider outage - no reliable market data', source='runbook')
print('Hard halt triggered')
"
```

## Prevention

### Configure data source redundancy
In `json/config.json`:
```json
{
  "yfinance_enabled": true,
  "nse_direct_enabled": false,
  "broker_data_enabled": false,
  "data_freshness_guard_enabled": true,
  "data_freshness_max_age_seconds": 60
}
```
Enable multiple data sources when available for automatic failover.

### Monitor data feed health
```bash
# Add to crontab (runs every 5 minutes during market hours)
python -m core.data_freshness_guard --alert
```

## Verification
- [ ] yfinance Python package returns valid price data
- [ ] `health_checker` reports data providers as ONLINE
- [ ] LTP cache updated within last 60 seconds
- [ ] Signal generation resumes with fresh data
- [ ] Dashboard shows current prices

## Escalation Path
1. **Level 1** — Operator on duty — 5 minutes
2. **Level 2** — Trading lead — 15 minutes
3. **Level 3** — System architect — 30 minutes (if extended outage)

## Related Runbooks
- RB-004: Stale Feed
- RB-005: Network Jitter
- RB-003: Database Corruption Recovery
