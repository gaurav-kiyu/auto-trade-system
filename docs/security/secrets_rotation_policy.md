# Secrets Rotation Policy

**Version:** 1.0  
**Last Updated:** July 4, 2026  
**Classification:** CONFIDENTIAL — Internal

---

## Overview

This document defines the secrets rotation policy for the OPB Index Options Buying Bot. All secrets must be rotated on a regular schedule to minimize the risk of credential exposure.

## Secret Classification

| Level | Description | Examples | Max Rotation Interval |
|-------|-------------|----------|----------------------|
| **Critical** | Direct financial access | Broker API keys, access tokens, TOTP keys | 30 days |
| **High** | System access or notification | Telegram bot token, dashboard JWT secret | 90 days |
| **Medium** | Encryption material | DB encryption key | 180 days |
| **Low** | Configuration secrets | None (all other config is non-sensitive) | N/A |

## Rotation Schedule

### Broker Credentials (Critical — 30 days)

| Secret | Environment Variable | Rotation Procedure |
|--------|---------------------|-------------------|
| Kite API Key | `OPBUYING_BROKER_API_KEY` | 1. Generate new API key from broker dashboard |
| Kite Access Token | `OPBUYING_BROKER_ACCESS_TOKEN` | 2. Update `.env` file or K8s Secret |
| Kite TOTP Key | `OPBUYING_BROKER_TOTP_KEY` | 3. Restart bot to pick up new credentials |
| Angel Client ID | `OPBUYING_ANGEL_CLIENT_ID` | 4. Verify broker connectivity via health check |
| Angel PIN | `OPBUYING_ANGEL_PIN` | 5. Run `python -m core.live_readiness_checker` |

Broker credential setup (Zerodha Kite, Angel Broking) is documented in
`SYSTEM_SETUP_GUIDE.md` and `SECURITY.md`; broker calls route through
`core/adapters/broker_adapters.py` per `CLAUDE.md`'s Broker Abstraction rule.

### Telegram Bot Token (High — 90 days)

| Secret | Environment Variable | Rotation Procedure |
|--------|---------------------|-------------------|
| Bot Token | `OPBUYING_BOT_TOKEN` | 1. Generate new token from [@BotFather](https://t.me/botfather) |
| Chat ID | `OPBUYING_CHAT_ID` | 2. Update `.env` file or K8s Secret |
| | | 3. Restart bot |

Note: The bot sends a startup message to confirm the new token works. If the startup message is not received within 60 seconds, revert the token and check the configuration.

### Dashboard Credentials (High — 90 days)

| Secret | Environment Variable | Rotation Procedure |
|--------|---------------------|-------------------|
| JWT Secret | `OPBUYING_JWT_SECRET` | 1. Generate new secret: `openssl rand -base64 32` |
| Admin Password | `OPBUYING_DASHBOARD_ADMIN_PASSWORD` | 2. Update K8s Secret |
| | | 3. Restart dashboard pod |

### Database Encryption Key (Medium — 180 days)

| Secret | Environment Variable | Rotation Procedure |
|--------|---------------------|-------------------|
| Encryption Key | `OPBUYING_DB_ENCRYPTION_KEY` | 1. Generate new key: `openssl rand -hex 32` |
| | | 2. Re-encrypt existing data with new key |
| | | 3. Update `.env` file or K8s Secret |
| | | 4. Verify data readability after rotation |

## Rotation Procedures

### Automated Rotation (Linux / Docker)

```bash
#!/bin/bash
# Example automated rotation script for broker token

# 1. Source current environment
source .env

# 2. Generate new TOTP (example for Kite)
NEW_TOTP=$(python -c "import pyotp; print(pyotp.TOTP('$OPBUYING_BROKER_TOTP_KEY').now())")

# 3. Exchange for new access token
NEW_TOKEN=$(curl -s -X POST "https://kite.zerodha.com/connect/token" \
  -d "api_key=$OPBUYING_BROKER_API_KEY&request_token=$NEW_TOTP" | jq -r '.access_token')

# 4. Update environment
sed -i "s/OPBUYING_BROKER_ACCESS_TOKEN=.*/OPBUYING_BROKER_ACCESS_TOKEN=$NEW_TOKEN/" .env

# 5. Notify operators
curl -s -X POST "https://api.telegram.org/bot$OPBUYING_BOT_TOKEN/sendMessage" \
  -d "chat_id=$OPBUYING_CHAT_ID&text=BROKER_TOKEN_ROTATED"
```

### Manual Rotation (Windows)

1. Stop the bot gracefully (Ctrl+C or kill file)
2. Open `.env` file in a text editor
3. Update the relevant secret values
4. Save the file
5. Restart the bot
6. Verify the startup log shows no credential errors

### Kubernetes Rotation

```bash
# For K8s-deployed instances, update the Secret and restart Pods

# 1. Update the secret
kubectl create secret generic opb-secrets \
  --namespace opb-trading \
  --from-literal=kite-api-key='<NEW_VALUE>' \
  --from-literal=kite-access-token='<NEW_VALUE>' \
  --dry-run=client -o yaml | kubectl apply -f -

# 2. Roll the deployment to pick up new secrets
kubectl rollout restart deployment/opb-deployment -n opb-trading

# 3. Monitor rollout
kubectl rollout status deployment/opb-deployment -n opb-trading
```

## Emergency Rotation

If a secret is suspected compromised:

1. **Immediate**: Rotate the compromised credential at the source (broker dashboard, BotFather)
2. **Within 5 minutes**: Update the affected secret in all environments
3. **Within 15 minutes**: Rotate all other secrets as a precaution
4. **Within 1 hour**: Perform incident postmortem and document in `docs/operations/postmortem_template.md`

## Verification

After each rotation, verify:

1. **Broker connectivity**: `python -m core.health_checker` shows all checks passing
2. **Order placement**: Place a small paper trade via `python index_app/index_trader.py --paper`
3. **Telegram notifications**: Confirm startup message is received
4. **Dashboard access**: Log in to the web dashboard
5. **Reconciliation**: Run `python -m core.reconciliation_controller` to verify clean state

## Compliance

This policy is enforced by:

- **Environment validation**: `core/environment.py` blocks startup with placeholder values
- **Secret hygiene**: `core/secret_hygiene.py` scans config files for inline secrets
- **Audit logging**: `core/audit_engine.py` records all env var lookups
- **Constitution scoring**: RSK-01 through RSK-05 verify risk controls

## References

- `.env.example` — Template with all required environment variables
- `k8s/secret.yaml` — Kubernetes secret manifest
- `docs/runbooks/auth_expiry.md` — Runbook for token expiry incidents
- `core/token_refresh_service.py` — Automatic token refresh implementation

---

*End of Secrets Rotation Policy*
