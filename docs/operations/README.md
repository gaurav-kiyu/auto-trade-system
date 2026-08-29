# Operations — Standard Operating Procedures (SOP)

This directory contains operational procedures for running the OPB Index Options Buying Bot in production.

## Quick Reference

| Procedure | Document | Frequency |
|-----------|----------|-----------|
| Daily Startup | `daily_startup.md` | Daily before market open |
| Daily Shutdown | _not yet written — see `maintenance.md` for the closest existing EOD procedure_ | Daily after market close |
| Incident Response | `incident_response.md` | On-call |
| Recovery | `recovery.md` | As needed |
| Maintenance | `maintenance.md` | Weekly |
| Backup & Restore | `backup_restore.md` | Weekly |

## Operational SLOs

| Metric | Target |
|--------|--------|
| Recovery Time Objective (RTO) | ≤ 5 minutes |
| Recovery Point Objective (RPO) | ≤ 1 minute |
| Maximum downtime per session | ≤ 2 minutes |
| Alert response time (CRITICAL) | ≤ 1 minute |
| Alert response time (WARNING) | ≤ 5 minutes |

## Production Checklist

Before each trading session:

1. ✅ Verify service health via dashboard or CLI
2. ✅ Confirm broker connection status
3. ✅ Verify market data feeds are operational
4. ✅ Check risk limits and position exposure
5. ✅ Verify Telegram notifications are delivering
6. ✅ Check database integrity
7. ✅ Confirm trading hours and market calendar

## Quick Commands

```bash
# Health check
python -m core.health_checker

# Live readiness check
python -m core.live_readiness_checker

# View trades
sqlite3 db/trades.db "SELECT COUNT(*), SUM(net_pnl) FROM trades"

# Check logs
tail -100 logs/trading.log

# Check Telegram delivery
python -m core.telegram_queue --status
```
