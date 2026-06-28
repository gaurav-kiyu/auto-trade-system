# Environment Provisioning Guide — Step-by-Step Deployment from Scratch

**Version:** 1.0
**Last Updated:** 2026-06-26
**Purpose:** Provision a fully functional OPB trading environment on a blank machine (bare metal, VM, or cloud instance).

---

## 1. Prerequisites

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|:-------:|:-----------:|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8 GB |
| Disk | 10 GB free | 50 GB SSD |
| Network | Broadband | Low-latency (>10 Mbps) |

### Supported OS

| OS | Version | Status |
|----|---------|--------|
| Ubuntu | 20.04 / 22.04 / 24.04 LTS | ✅ Primary target |
| Debian | 11 / 12 | ✅ |
| Windows | 10 / 11 / Server 2019+ | ✅ (via direct install) |
| macOS | 13+ (Ventura) | ✅ (development only) |
| Docker | 24+ | ✅ Cross-platform |

---

## 2. Fresh OS Installation

### 2.1 Ubuntu 22.04 LTS (Recommended)

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install essential tools
sudo apt install -y \
    git curl wget build-essential \
    python3 python3-pip python3-venv python3-dev \
    sqlite3 ca-certificates gnupg lsb-release

# Verify Python version (must be 3.10–3.19)
python3 --version
```

### 2.2 Docker Installation (Optional — for containerized deployment)

```bash
# Add Docker's official GPG key and repo
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Add your user to docker group (avoids sudo)
sudo usermod -aG docker $USER
newgrp docker  # or log out and back in

# Verify
docker --version && docker compose version
```

### 2.3 Windows Installation

```powershell
# Install Python from https://www.python.org/downloads/ (3.10+)
# Ensure "Add Python to PATH" is checked during installation

# Verify
python --version
pip --version

# Install Git from https://git-scm.com/download/win
git --version
```

---

## 3. Clone & Project Setup

### 3.1 Clone Repository

```bash
git clone <repository-url> opb_trading_bot
cd opb_trading_bot
```

For private repositories, configure SSH or PAT authentication:

```bash
# SSH key (recommended)
ssh-keygen -t ed25519 -C "your_email@example.com"
cat ~/.ssh/id_ed25519.pub
# Add to GitHub/GitLab SSH keys settings

# Or use personal access token
git clone https://<username>:<token>@github.com/org/opb_trading_bot.git
```

### 3.2 Verify Git State

```bash
git status
git log --oneline -5
cat VERSION  # Confirm version
```

---

## 4. Python Environment

### 4.1 Create Virtual Environment

```bash
# Linux/macOS
python3 -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Confirm active
which python   # Linux/macOS
where python   # Windows
```

### 4.2 Install Dependencies

```bash
# Core dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Optional — development dependencies
pip install -r requirements-dev.txt

# Verify all imports work
python -c "
import jsonschema, requests, yfinance, pandas, numpy
print('✅ Core imports OK')
"

# Verify optional feature imports (fail gracefully)
python -c "
try:
    import lightgbm, sklearn, reportlab, feedparser, scipy, prometheus_client
    print('✅ Optional imports OK')
except ImportError as e:
    print(f'⚠️  Optional import missing: {e}')
"
```

### 4.3 Verify Python Version Compliance

```bash
python -c "
import sys
ver = sys.version_info
assert (3, 10) <= (ver.major, ver.minor) <= (3, 19), \
    f'Python {ver.major}.{ver.minor} not supported'
print(f'✅ Python {ver.major}.{ver.minor}.{ver.micro} — compliant')
"
```

---

## 5. Configuration

### 5.1 Copy Template Configs

```bash
# Main config (copy from defaults if template exists)
cp config.template.json config.json

# Stock config
cp stock_config.template.json stock_config.json

# Index config defaults (should already be present)
ls -la index_config.defaults.json
```

### 5.2 Set Secrets via Environment Variables

Create `.env` file (NEVER commit this):

```bash
cat > .env << 'EOF'
# Telegram (required for notifications)
OPBUYING_BOT_TOKEN=your_telegram_bot_token
OPBUYING_CHAT_ID=your_telegram_chat_id

# Broker — Kite (optional, for live trading)
OPBUYING_KITE_API_KEY=
OPBUYING_KITE_ACCESS_TOKEN=
OPBUYING_KITE_USER_ID=
OPBUYING_KITE_PASSWORD=
OPBUYING_KITE_TOTP_KEY=

# Broker — Angel (optional, for live trading)
OPBUYING_ANGEL_API_KEY=
OPBUYING_ANGEL_CLIENT_ID=
OPBUYING_ANGEL_PASSWORD=

# Dashboard auth (optional, for web dashboard)
OPBUYING_ADMIN_USERNAME=admin
OPBUYING_DEFAULT_ADMIN_PASSWORD=changeme123
EOF

echo "⚠️  Edit .env with your actual secrets"
```

### 5.3 Configure Trading Parameters

Edit `config.json` for your risk preferences:

```json
{
  "BASE_CAPITAL": 100000,
  "MAX_DAILY_LOSS": -10000,
  "MAX_DRAWDOWN": 0.15,
  "PAPER_MODE": true,
  "SCAN_INTERVAL": 30
}
```

> **Always start with `PAPER_MODE: true`** — never skip this step.

---

## 6. Database Initialization

Databases are created automatically on first run, but you can pre-initialize:

```bash
# Verify SQLite is available
sqlite3 --version

# Pre-create and validate database files (optional)
python -c "
import sqlite3
for db in ['trades.db', 'trade_journal.db', 'ml_tracker.db', 'execution_state.db']:
    conn = sqlite3.connect(db)
    conn.execute('SELECT 1')
    conn.close()
    print(f'✅ {db} — OK')
"
```

Expected databases (auto-created):

| Database | Purpose | Location |
|----------|---------|----------|
| `trades.db` | Trade log | Project root |
| `trade_journal.db` | Execution quality | Project root |
| `ml_tracker.db` | ML predictions | Project root |
| `oi_snapshots.db` | OI history | Project root |
| `event_store.db` | Event hash chain | Project root |
| `execution_state.db` | State machine persistence | Project root |

---

## 7. Verification Checks

### 7.1 Quick Self-Test

```bash
# Run built-in self-test
python index_app/index_trader.py --selftest 2>&1 | tail -20

# Expected output: "Self-test: PASS" or similar
```

### 7.2 Configuration Validation

```bash
python -c "
from core.config_bootstrap import load_config
cfg = load_config()
print(f'✅ Config loaded: {len(cfg)} keys')
print(f'   Mode: {cfg.get(\"EXECUTION_MODE\", \"PAPER\")}')
print(f'   Capital: ₹{cfg.get(\"BASE_CAPITAL\", 0):,.0f}')
print(f'   Broker: {cfg.get(\"BROKER_DRIVER\", \"paper\")}')
"
```

### 7.3 System Health Check

```bash
# Comprehensive health check
python -m core.health_checker --format json 2>&1 | python -m json.tool

# Expected: all subsystems report healthy
```

### 7.4 Run Certification Gates

```bash
# Verify all certification gates pass
python -m core.certification.gate --json 2>&1 | tail -30
```

### 7.5 Run Test Suite

```bash
# Quick smoke test (subset, ~1 min)
python -m pytest tests/test_smoke.py tests/test_sanity_checks.py -q

# Full test suite (~2670 tests, ~4-5 min)
python -m pytest tests/ -q
```

---

## 8. Launch Trading

### 8.1 Paper Trading (First Run)

```bash
# Start in paper mode
python index_app/index_trader.py --paper

# Monitor first scan cycle
tail -f paper_trading.log | head -50
```

**Verify on first run:**

- [ ] No `ERROR` or `CRITICAL` log messages
- [ ] Signal generation produces output (or "No signal" decision)
- [ ] Paper trades execute (check `trades.db`)
- [ ] Telegram notifications arrive (if configured)
- [ ] Dashboard accessible at `http://localhost:8765` (if enabled)

### 8.2 Health Monitoring (Separate Terminal)

```bash
# Watch real-time metrics
watch -n 5 'python -c "
from core.performance_metrics import load_trades
trades = load_trades(\"trades.db\")
wins = [t for t in trades if t.get(\"net_pnl\", 0) > 0]
losses = [t for t in trades if t.get(\"net_pnl\", 0) <= 0]
print(f\"Trades: {len(trades)}\")
print(f\"Wins: {len(wins)}\")
print(f\"Losses: {len(losses)}\")
"'
```

### 8.3 Shadow/Live (After Paper Validation)

```bash
# Only after meeting ALL criteria:
# 1. 30+ days of successful paper trading
# 2. All certification gates pass
# 3. Pre-implementation check passes
# 4. No critical bugs in paper mode

# Start in shadow mode (monitoring only)
python index_app/index_trader.py

# Monitor closely for first 3 trading sessions
```

---

## 9. Day-2 Operations

### 9.1 Log Rotation Setup

```bash
# Verify log rotation is configured (settings in config_bootstrap)
tail -5 logs/opb.log

# Log files are auto-rotated at 50 MB, gzipped, retaining 5 backups
```

### 9.2 Backup Schedule

Set up a cron job for automatic backups:

```bash
# Edit crontab
crontab -e

# Add daily backup at 6 PM IST (before market close)
# 20 12 * * 1-5 cd /path/to/opb_trading_bot && python scripts/backup_databases.py --retain 30

# Add weekly full backup on Sunday
# 0 10 * * 0 cd /path/to/opb_trading_bot && tar -czf backups/full_$(date +\\%Y\\%m\\%d).tar.gz config.json data/
```

### 9.3 Daily Checklist

```bash
# Morning — before market open (08:30 IST)
python -m core.health_checker --quick
python -c "from core.exchange_calendar_engine import get_calendar_engine; e=get_calendar_engine(); print(e.get_market_status('NIFTY'))"

# Afternoon — monitor (12:00 IST)
tail -20 paper_trading.log | grep -i "signal\|entry\|exit\|error"

# Evening — review (16:00 IST)
python -m core.performance_metrics --days 1
```

### 9.4 Upgrade Procedure

```bash
# Step 1: Backup
python scripts/backup_databases.py --retain 30

# Step 2: Pull updates
git pull origin main

# Step 3: Update dependencies
pip install -r requirements.txt --upgrade

# Step 4: Verify
python -m pytest tests/ -q
python -m core.certification.gate

# Step 5: Start in paper mode
python index_app/index_trader.py --paper

# Step 6: Monitor for 1 trading session
```

---

## 10. Troubleshooting Guide

### 10.1 Installation Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `pip install` fails | Missing build deps | `sudo apt install python3-dev build-essential` |
| `sqlite3` module error | Missing SQLite | `sudo apt install sqlite3 libsqlite3-dev` |
| `yfinance` import error | Network blocked | Check firewall/proxy settings |
| `ModuleNotFoundError` | Incomplete install | `pip install -r requirements.txt --force-reinstall` |

### 10.2 Runtime Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Bot crashes on startup | Config key mismatch | `python -m core.config_bootstrap --validate` |
| No signals generated | Market closed | `python -c "from core.exchange_calendar_engine import get_calendar_engine; e=get_calendar_engine(); print(e.get_market_status('NIFTY'))"` |
| Broker connection fails | Invalid credentials | Check `OPBUYING_*` env vars |
| Dashboard not accessible | Port conflict | Change `web_dashboard_port` in config |

### 10.3 Diagnostic Commands

```bash
# Quick health check
python -m core.health_checker

# Configuration diagnostics
python -m core.config_bootstrap --validate

# Version compatibility
python -m core.version_compatibility --json

# Live readiness check
python -m core.live_readiness_checker --format json

# SLO governance check
python -m core.slo_governance --check --json
```

---

## 11. Security Hardening (Production)

```bash
# 1. Create dedicated service user
sudo useradd -r -s /bin/false opb-trader
sudo chown -R opb-trader:opb-trader /opt/opb_trading_bot

# 2. Restrict file permissions
find /opt/opb_trading_bot -type f -name "*.db" -exec chmod 600 {} \;
find /opt/opb_trading_bot -type f -name "config.json" -exec chmod 600 {} \;
chmod 700 /opt/opb_trading_bot/.env

# 3. Set up firewall (UFW)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 8765/tcp  # dashboard (if needed)
sudo ufw enable

# 4. Set up fail2ban
sudo apt install fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# 5. Enable audit logging
# Ensure core/audit_engine.py is active and jsonl audit trail is writing
tail -f logs/audit*.jsonl
```

---

## 12. Verification Checklist (Final)

Before considering the environment fully provisioned:

| # | Check | Command | Status |
|---|-------|---------|--------|
| 1 | Python version OK | `python --version` | ☐ |
| 2 | Dependencies installed | `pip list --format=columns` | ☐ |
| 3 | Config valid | `python -m core.config_bootstrap --validate` | ☐ |
| 4 | Databases initialized | `ls -la *.db` | ☐ |
| 5 | Self-test passes | `python index_app/index_trader.py --selftest` | ☐ |
| 6 | Certification gates pass | `python -m core.certification.gate` | ☐ |
| 7 | Tests pass | `python -m pytest tests/ -q` | ☐ |
| 8 | Health check OK | `python -m core.health_checker` | ☐ |
| 9 | Paper mode starts | `python index_app/index_trader.py --paper` (30s test) | ☐ |
| 10 | Version compatibility OK | `python -m core.version_compatibility --json` | ☐ |

---

## Appendix: Quick-Start (Fast Track)

For experienced operators who just want the minimal commands:

```bash
# 1. System
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git

# 2. Clone
git clone <repo> opb && cd opb

# 3. Python
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 4. Config
cp config.template.json config.json

# 5. Verify
python -m pytest tests/test_smoke.py -q
python -m core.certification.gate
python index_app/index_trader.py --selftest

# 6. Launch
python index_app/index_trader.py --paper
```

---

*"Provision once, trade reliably." — Last updated 2026-06-26*
