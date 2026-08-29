# Security Policy — OPB Index Options Buying Bot

**Version:** 2.54.0  
**Last Updated:** 2026-07-18  

---

## Supported Versions

| Version | Supported | Notes |
|---------|-----------|-------|
| 2.54.x  | ✅ Active development | Current release branch |
| 2.53.x  | ✅ Bug fixes only | Previous stable |
| < 2.53  | ❌ End of life | No longer supported |

---

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability in the OPB trading bot,
please report it privately **before** disclosing it publicly.

### Process

1. **DO NOT** file a public GitHub issue
2. **DO NOT** discuss the vulnerability in public forums
3. **Email** the project maintainers or contact via encrypted channel
4. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Affected versions and components
   - Potential impact
   - Suggested fix (if available)

### Response Timeline

- **Acknowledgment**: Within 24 hours
- **Triage**: Within 3 business days
- **Fix release**: Critical vulnerabilities within 7 days
- **Public disclosure**: After fix is deployed (typically 14 days)

---

## Security Architecture

### Authentication & Authorization

- **Session-based auth**: httpOnly cookies with secure flag over HTTPS
- **Role-based access control (RBAC)**: admin, operator, viewer roles
- **Password hashing**: bcrypt (via `core/auth/handler/password.py`)
- **Session TTL**: Configurable (default 3600 seconds), auto-purged every 15 minutes
- **CSRF protection**: Token-based, `X-CSRF-Token` header required for mutations
- **Rate limiting**: 60 req/min (general), 20 req/min (admin endpoints)

### Secrets Management

- **Never in json/config.json**: All secrets via `OPBUYING_*` environment variables
- **Placeholder convention**: `__OPBUYING_*_ENV__` in template configs
- **Redaction**: Secrets automatically redacted in all log output
- **Audited access**: Every secret access logged via `get_secret()` method
- **Example env vars**: `OPBUYING_BOT_TOKEN`, `OPBUYING_CHAT_ID`, `OPBUYING_KITE_API_KEY`

### API Security

| Measure | Implementation |
|---------|---------------|
| HTTPS/TLS | Optional via `web_ssl_certfile`/`web_ssl_keyfile` config |
| HSTS | `max-age=31536000; includeSubDomains; preload` (HTTPS only) |
| CSP | Nonce-based script-src, unsafe-inline style-src |
| CORS | Configurable allowed origins |
| SQL Injection | All queries use parameterized statements |
| XSS | CSP, output encoding in templates |
| Clickjacking | `X-Frame-Options: DENY` |
| MFA | Optional multi-factor authentication support (`core/auth/mfa.py`) |

### Trade Safety

| Feature | Description |
|---------|-------------|
| Hard Halt | Emergency kill switch - blocks all trading immediately |
| Daily Loss Limit | Configurable max daily loss (default Rs 2,000) |
| Max Drawdown | Configurable max drawdown percentage (default 20%) |
| Circuit Breaker | Broker/NSE failure rate gate |
| Position Sizing | Risk-based position sizing with volatility adjustment |
| Consecutive Loss Protection | Auto-halt after N consecutive losses |
| Paper Mode | Complete broker isolation - never reaches real API |
| WAL Journal | Write-Ahead Intent Journal for exactly-once execution |

### ML Model Security

- **SHA-256 integrity verification**: Model checksums tracked across loads
- **Safe unpickling**: Restricted to known-safe classes (LightGBM only)
- **Tamper detection**: Warning logged if model checksum changes between loads
- **AI governance**: Model registry tracks version, checksum, and metadata
- **Pre-implementation check**: AI agents must pass constitution acknowledgment

### Infrastructure Security

| Component | Measure |
|-----------|---------|
| Docker | Non-root user, minimal base image |
| Kubernetes | Secrets via `k8s/secret.yaml`, network policies |
| Prometheus | Internal port only, no external exposure |
| Loki | 30-day retention, structured audit log parsing |
| Grafana | Auto-provisioned datasources, dashboard auth |

### Dependency Security

- **Dependabot**: Automated dependency vulnerability scanning (`.github/dependabot.yml`)
- **Requirements**: Pinned versions in `requirements-lock.txt`
- **Review**: All dependency updates reviewed before merging

---

## Data Protection

### Sensitive Data

| Data Type | Storage | Protection |
|-----------|---------|------------|
| Broker API keys | Environment variables | Never persisted to disk |
| Telegram tokens | Environment variables | Redacted in logs |
| Session tokens | SQLite (db/auth.db) | Hashed with bcrypt |
| Trade records | SQLite (db/trades.db) | File permissions |
| ML models | Pickle files | SHA-256 verification |
| Audit logs | JSONL files | File permissions |

### Data Retention

| Category | Retention | Cleanup |
|----------|-----------|---------|
| Trade journal | Indefinite | Manual archive |
| Audit logs | 30 days | Auto-purge |
| ML predictions | 1000 per feature | Auto-prune |
| Event store | Indefinite | Manual archive |
| Auth sessions | 1 hour TTL | Auto-purge |

### Audit Trail

- **Config changes**: Written to `json/config_audit.jsonl` with timestamp, user, old/new values
- **Authentication**: Login/logout events logged to audit store
- **Trade execution**: All orders logged with broker order ID
- **Model operations**: Training, saving, loading logged with checksums
- **Kill switch**: Every kill/resume logged with triggering user and reason

---

## Compliance

### Trading Regulations

- The bot is designed for **NSE index options trading only**
- **Not financial advice**: This is a trading tool, not investment advice
- **Know your risk**: Live trading involves financial risk
- **Paper mode**: Always test in paper mode before live deployment

### Environment Separation

The bot supports 6 deployment environments with increasing guard rails:

| Environment | Data Source | Risk Limits | Purpose |
|-------------|-------------|-------------|---------|
| DEV | Simulated | None | Development |
| QA | Simulated | None | Testing |
| PAPER | Live (yfinance) | Simulated | Signal testing |
| SHADOW | Live | Real (no trades) | Dry run |
| STAGING | Live | Real (limited) | Pre-production |
| PRODUCTION | Live | Full | Live trading |

### Code of Conduct

This project follows a strict Code of Conduct. All contributors and users are expected to:
- Maintain confidentiality of sensitive system information
- Report security vulnerabilities responsibly
- Follow the established governance and change pipeline
- Respect the constitution scoring framework

---

## Security Contacts

| Role | Contact |
|------|---------|
| Security Lead | Project maintainers via GitHub |
| Incident Response | Trading lead (during market hours) |
| Emergency | Kill switch via dashboard or kill file |

---

## Related Documents

- `docs/AI_GOVERNANCE_GUIDE.md` — AI agent constitution and pre-implementation protocol
- `docs/operations/incident_response.md` — Incident response procedures
- `docs/deployment/DEPLOYMENT_GUIDE.md` — Secure deployment configuration
- `docs/deployment/disaster_recovery_plan.md` — Disaster recovery procedures
- `CONTRIBUTING.md` — Contribution guidelines and security expectations
- `core/auth/` — Authentication and authorization modules
- `.github/dependabot.yml` — Automated dependency security scanning
