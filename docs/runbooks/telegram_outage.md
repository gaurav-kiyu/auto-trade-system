# Runbook: Telegram Outage — Notifications Unreachable

| Field | Value |
|-------|-------|
| Runbook ID | `RB-013` |
| Severity | HIGH |
| Category | Notifications / Communication |
| Last Updated | 2026-07-18 |

## Trigger Condition
Telegram Bot API returns timeout, HTTP 5xx, or connection error for 5 consecutive send attempts.

## Expected Symptoms
- `ERROR` logs: "Telegram send failed", "Bot API unreachable", "HTTP 502 from api.telegram.org"
- Telegram queue grows but messages are never delivered
- `health_checker` shows notifications status = UNREACHABLE
- Trade alerts, risk warnings, and heartbeats are silent

## Initial Diagnosis

### Step 1: Verify Telegram API is down
```bash
curl -s -o /dev/null -w "%{http_code}" https://api.telegram.org/bot<TOKEN>/getMe
```
- If HTTP 200: bot token is valid and API is reachable → issue may be network/auth → Step 2
- If connection timeout / HTTP 5xx: Telegram API is down → proceed to Resolution
- If HTTP 401: Token is invalid/revoked → proceed to Step 4

### Step 2: Check network connectivity
```bash
ping -n 3 api.telegram.org
```
- If ping fails: DNS/network issue → check proxy/firewall settings

### Step 3: Check bot token
```bash
python -c "
from core.telegram_queue import TelegramQueue
q = TelegramQueue({})
print('Queue size:', q.qsize())
print('Last error:', q.last_error)
"
```

### Step 4: Verify BOT_TOKEN is set
```bash
echo $OPBUYING_BOT_TOKEN
```
- If empty: Token environment variable is missing or not exported
- Check config for `__OPBUYING_BOT_TOKEN_ENV__` placeholder (should NOT be used)

## Resolution Steps

### 1: Wait and retry (if transient API outage)
Telegram API outages are typically brief (5-15 minutes). The bot uses an internal priority queue
(`core/telegram_queue.py`) that retries failed sends automatically. Wait 5 minutes and check again:

```bash
python -c "
from core.health_checker import run_full_health_check
import json
report = run_full_health_check({})
print(report.get('notifications', 'No data'))
"
```

### 2: Restart Telegram queue
If stuck messages in queue, reset the Telegram queue adapter:
```bash
python -c "
from core.telegram_queue import TelegramQueue
q = TelegramQueue({})
q.reset()
print('Telegram queue reset')
"
```

### 3: Switch to file-based audit logging fallback
Telegram is the primary notification channel. If unavailable, critical alerts still go to the
audit log file. Verify audit logging is active:
```bash
tail -f logs/audit/audit_trail_*.jsonl
```

### 4: Validate and refresh BOT_TOKEN
If the token is invalid or expired:
```bash
# Re-export the correct token
export OPBUYING_BOT_TOKEN="<your-new-telegram-bot-token>"

# Verify it works
curl -s -o /dev/null -w "%{http_code}" https://api.telegram.org/bot$OPBUYING_BOT_TOKEN/getMe

# If HTTP 200, restart the bot to pick up the new token
```

### 5: Check rate limiting
Telegram imposes rate limits (30 messages/second per chat). If the bot is sending too many messages:
```bash
python -c "
from core.telegram_queue import TelegramQueue
q = TelegramQueue({})
print('Rate limited:', q.is_rate_limited())
print('Messages in last minute:', q.message_count_last_min())
"
```
Rate limiting resolves automatically after 1 minute of reduced send rate.

### 6: If still down after 30 minutes
Switch to CRITICAL-only notifications to reduce volume or use an alternative notification method:
```bash
# Enable quiet mode (only CRITICAL alerts)
python -c "
from core.telegram_queue import TelegramQueue
q = TelegramQueue({})
q.set_quiet_mode(True)
print('Quiet mode enabled - only CRITICAL alerts will be sent')
"
```

## Verification
- [ ] `curl` to Telegram Bot API returns HTTP 200
- [ ] `health_checker` reports notifications as ONLINE
- [ ] At least one test message received in the Telegram chat
- [ ] No backlog in the Telegram queue

## Escalation Path
1. **Level 1** — Operator on duty — 5 minutes
2. **Level 2** — Trading lead — 15 minutes
3. **Level 3** — System architect — 30 minutes

## Related Runbooks
- RB-002: Auth Token Expiry
- RB-005: Network Jitter
- RB-006: Split Brain
