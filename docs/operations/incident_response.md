# Incident Response Procedure

## Incident Severity Levels

| Level | Definition | Response Time |
|-------|------------|---------------|
| CRITICAL | Trading halted, positions at risk, data loss | ≤ 1 minute |
| HIGH | Broker disconnected, feed failure, DB error | ≤ 5 minutes |
| MEDIUM | Signal degradation, delayed notifications | ≤ 15 minutes |
| LOW | Non-critical errors, cosmetic issues | ≤ 60 minutes |

## Incident Response Flow

### 1. DETECT
- Automated alerts via Telegram (CRITICAL/HIGH)
- Health check failures
- Circuit breaker triggers
- Manual observation

### 2. ASSESS
```bash
# Check current state
python -m core.health_checker --format json
python index_app/index_trader.py --status

# Check recent errors
tail -100 logs/trading.log | grep -i "error\|critical\|fail"
```

### 3. RESPOND

**For execution failures:**
```bash
# Check order status
sqlite3 db/trades.db "SELECT * FROM trades ORDER BY id DESC LIMIT 10"

# Verify positions
python -m core.position_service --summary
```

**For broker disconnection:**
- Failover should auto-trigger (check broker_failover)
- If failover fails, restart broker adapter
- If persistent, switch to paper mode

**For data feed failure:**
- System auto-falls back to yfinance
- Check feed health with health_checker
- Restart feed adapter if needed

### 4. ESCALATE
If unable to resolve within SLA, escalate to:
- System Administrator
- Broker Support (for broker issues)
- Development Team (for code issues)

### 5. RESOLVE
- Document the incident
- Create postmortem
- Update runbooks
