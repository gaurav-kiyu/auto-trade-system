# Daily Startup Procedure

## Pre-Market (08:45 - 09:15 IST)

1. **Verify System Health**
   ```bash
   python -m core.health_checker
   ```
   - Confirm all 5 health checks pass
   - Check disk space, DB integrity, config validity

2. **Verify Broker Connection**
   ```bash
   python -m core.broker_failover --status
   ```
   - Confirm primary broker (Kite) is connected
   - Check failover status is healthy

3. **Check Market Calendar**
   - Verify today is a trading day (not a market holiday)
   - Check for any RBI/Budget/FOMC events

4. **Verify Data Feeds**
   ```bash
   python -m core.yf_bar_fetch --check
   ```
   - Confirm yfinance data is flowing
   - Check LTP for all tracked indices

5. **Start Trading Engine**
   ```bash
   python index_app/index_trader.py --paper
   ```
   - Or replace `--paper` with `--live` for live execution
   - Verify startup logs show no errors

## Market Open (09:15)

6. **Verify First Signals**
   - Check signal generation within first 5 minutes
   - Verify Telegram notifications are delivering

7. **Monitor First 15 Minutes**
   - Watch for unexpected behavior
   - Verify position sizing is correct
   - Confirm risk limits are enforced

## Startup Checklist

- [ ] System health check passed
- [ ] Broker connected
- [ ] Market is open today
- [ ] Data feeds operational
- [ ] Telegram delivering
- [ ] First signals generated
- [ ] Risk limits verified
