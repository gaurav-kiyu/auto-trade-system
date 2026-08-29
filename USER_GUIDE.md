# OPB Index Options Trading Bot — Complete User Guide

**Version:** 2.58.0  
**Platform:** Windows (primary) / Linux / Docker  
**Target:** NIFTY, BANKNIFTY, FINNIFTY index options

---

## Table of Contents
1. [System Overview](#1-system-overview)
2. [Installation](#2-installation)
3. [Configuration](#3-configuration)
4. [Running Modes](#4-running-modes)
5. [Step-by-Step: First Run](#5-step-by-step-first-run)
6. [Step-by-Step: Paper Trading](#6-step-by-step-paper-trading)
7. [Step-by-Step: Live Trading](#7-step-by-step-live-trading)
8. [Telegram Setup](#8-telegram-setup)
9. [Web Dashboard](#9-web-dashboard)
10. [Risk Management](#10-risk-management)
11. [Monitoring & Alerts](#11-monitoring--alerts)
12. [Backtesting](#12-backtesting)
13. [Performance Reports](#13-performance-reports)
14. [Docker Deployment](#14-docker-deployment)
15. [Kubernetes Deployment](#15-kubernetes-deployment)
16. [Troubleshooting](#16-troubleshooting)
17. [FAQ](#17-faq)

---

## 1. System Overview

### What It Does
The OPB (Options Buying) Bot is an **automated NSE index options trading system**. It generates trading signals for NIFTY, BANKNIFTY, and FINNIFTY options, manages risk, and executes trades through a broker or paper trading simulator.

### Architecture (Simplified)
```
Market Feeds (NSE 2,500+ Stocks & 5 Indices) → 16-Strategy Quant Engine → ML Feature SLA → Risk Gates → Execution / Alerting
                                                      ↓
                                      11-Broker Dynamic OAuth Ingestion
                                                      ↓
                                   Instant Telegram & Gmail Real-Time Alerts
```

### Key Capabilities
| Feature | Description |
|---|---|
| **Full NSE Stock Universe** | Dynamically syncs & scans all 2,553+ listed NSE stocks daily (Penny, Micro, Small, Mid, Large-Cap, SME). |
| **16 Quant Strategies** | Multi-TF Trend, Greeks Tail Risk Hedging, Mean Reversion, VWAP, DCF, Volatility Arb, Supertrend, etc. |
| **11-Broker Ingestion** | Zerodha, Angel One, Upstox, Groww, Kotak, Dhan, Fyers, ICICI Direct, Motilal Oswal, IIFL, m.Stock. |
| **Live Options Chain** | Centered ATM strike grids for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX with CE/PE tables. |
| **Dual Alert Delivery** | Instant real-time signal dispatches via Telegram Bot API and Gmail SMTP TLS. |
| **ML Enhancement** | LightGBM with 16 tracked features + SHAP attribution explainability. |
| **Risk Management** | 15+ pre-trade gates, 3-layer safety, Circuit Breaker, News Sentinel. |
| **Real-time Dashboard** | Enterprise FastAPI web UI with live charts, trade journal, and data lineage. |

---

## 2. Installation

### Prerequisites
- **Python 3.10–3.19** (Windows or Linux)
- **pip** (Python package installer)
- **4 GB RAM minimum** (8 GB recommended)
- **Internet connection** (for market data)

### Quick Install (Windows)
```batch
git clone <repository-url>
cd OPB_FINAL_MT
pip install -e .
```

### With Virtual Environment (Recommended)
```batch
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Linux
pip install -e ".[dev]"
```

### Verify Installation
```bash
python -c "from core import *; print('Installation OK')"
```

---

## 3. Configuration

### Configuration Files
The system uses a 3-layer configuration merge:
1. `json/index_config.defaults.json` — Safe defaults (single source of truth)
2. `json/config.json` — User overrides
3. `json/config.local.json` — Local overrides (gitignored)
4. `OPBUYING_*` environment variables — Override any config key

### Required Settings
1. Copy the template:
   ```bash
   copy json/config.template.json json/config.json
   ```
2. Edit `json/config.json` with your settings:

```json
{
  "BOT_TOKEN": "YOUR_TELEGRAM_BOT_TOKEN",
  "CHAT_ID": "YOUR_TELEGRAM_CHAT_ID",
  "BASE_CAPITAL": 5000,
  "EXECUTION_MODE": "PAPER",
  "BROKER_API_ENABLED": false
}
```

### Environment Variables
All config keys can be overridden with `OPBUYING_` prefix:
```bash
set OPBUYING_BASE_CAPITAL=10000
set OPBUYING_EXECUTION_MODE=PAPER
set OPBUYING_BROKER_API_ENABLED=false
```

### Key Configuration Categories
| Category | Example Keys | Purpose |
|----------|-------------|---------|
| **Risk** | `MAX_DAILY_LOSS`, `MAX_DRAWDOWN`, `RISK_PER_TRADE` | Capital protection |
| **Signals** | `AI_THRESHOLD`, `SCAN_INTERVAL`, `COOLDOWN` | Signal tuning |
| **Execution** | `EXECUTION_MODE`, `SL_PCT`, `TARGET_PCT` | Trade execution |
| **Broker** | `BROKER_NAME`, `BROKER_BACKEND`, `BROKER_CONFIG` | Broker connection |
| **Telegram** | `BOT_TOKEN`, `CHAT_ID`, `TG_MAX_PER_MIN` | Notifications |
| **Database** | `DB_PROVIDER`, `DB_PATH`, `pg_host`, `pg_port` | Data storage |
| **Dashboard** | `web_dashboard_enabled`, `web_dashboard_port` | Web interface |

---

## 4. Running Modes

### Mode Comparison
| Mode | Broker Connection | Real Orders | Capital Risk | Use Case |
|------|:-----------------:|:-----------:|:------------:|----------|
| **MANUAL** | No | No | None | Signal monitoring only |
| **PAPER** | PaperBroker | No | None | Simulation with realistic fills |
| **SHADOW** | Real broker monitor | No | None | Compare signals vs live market |
| **LIVE** | Real broker | Yes | Real | Automated live trading |

### Setting Execution Mode
```bash
# Paper mode (default, safe)
python index_app/index_trader.py --paper

# Manual mode (signals only)
python index_app/index_trader.py --manual

# Live mode (requires broker config)
python index_app/index_trader.py
```

### Config File Mode Selection
In `json/config.json`:
```json
{
  "EXECUTION_MODE": "PAPER",
  "BROKER_API_ENABLED": false
}
```

---

## 5. Step-by-Step: First Run

### Step 1: Configure Telegram (Optional but Recommended)
```bash
# 1. Create a Telegram bot via @BotFather
# 2. Get your bot token
# 3. Get your chat ID
# 4. Update json/config.json:
#    "BOT_TOKEN": "your_bot_token",
#    "CHAT_ID": "your_chat_id"
```

### Step 2: Start in Paper Mode
```bash
python index_app/index_trader.py --paper
```

### Step 3: Observe Output
The bot will display:
```
[INFO] Starting OPB Index Trader v2.58.0
[INFO] Execution mode: PAPER
[INFO] Risk service initialized
[INFO] Signal engine started
[INFO] Scanning for signals...
```

### Step 4: Verify It's Working
- Check `db/trades.db` is created in the project root
- Check `json/trader_state.json` for state information
- Watch Telegram for alerts (if configured)

### Step 5: Stop Gracefully
Press `Ctrl+C` — the bot will:
- Exit current positions
- Save state to `json/trader_state.json`
- Log final summary

---

## 6. Step-by-Step: Paper Trading

### What is Paper Trading?
Paper trading simulates real trading without risking actual capital. The bot uses:
- Real-time market data (via yfinance)
- Realistic fill simulation (mid-price ± slippage%)
- OI (Open Interest) liquidity filter
- Full risk management enforcement

### Run Paper Trading
```bash
python index_app/index_trader.py --paper
```

### Paper Trading Configuration
In `json/config.json`:
```json
{
  "PAPER_TRACK_CAPITAL": true,
  "paper_slippage_pct": 0.5,
  "min_oi_threshold": 500,
  "min_volume_threshold": 100
}
```

### Analyze Paper Results
```bash
# Generate PDF report
python -m core.report_generator --days 30 --mode PAPER

# View performance metrics
python -m core.performance_metrics --days 30

# Replay a specific trade
python -m core.trade_replayer --id 42

# Run signal autopsy
python -m core.signal_autopsy --days 30
```

### Paper → Live Readiness Check
```bash
# Check if paper performance qualifies for live
python -m core.live_readiness_checker
```

Required minimums for live readiness:
- **50+ paper trades**
- **55% win rate**
- **1.5 profit factor**
- **15% max drawdown**
- **10+ trading days**

---

## 7. Step-by-Step: Live Trading

### Prerequisites
Before going live:
1. ✅ 50+ paper trades with 55%+ win rate
2. ✅ Live readiness check passed
3. ✅ Broker account configured
4. ✅ Telegram notifications working
5. ✅ Risk limits verified

### Step 1: Configure Broker
In `json/config.json`:
```json
{
  "BROKER_NAME": "Zerodha",
  "BROKER_BACKEND": "KITE",
  "BROKER_API_ENABLED": true,
  "BROKER_CONFIG": {
    "api_key": "your_api_key",
    "access_token": "your_access_token",
    "user_id": "your_user_id"
  }
}
```

### Step 2: Start in Manual Mode First
```bash
python index_app/index_trader.py --manual
```
This shows signals without placing orders.

### Step 3: Monitor for 1-2 Days
- Verify signals look correct
- Check Telegram alerts
- Review web dashboard

### Step 4: Switch to Automated Live
```bash
python index_app/index_trader.py
```

### Step 5: Monitor Closely (First Week)
- Watch for unexpected behavior
- Verify orders are placed correctly
- Check reconciliation reports
- Review daily performance

---

## 8. Telegram Setup

### Create a Bot
1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow prompts
3. Save the bot token

### Get Your Chat ID
1. Start a chat with your bot
2. Send any message
3. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find the `chat.id` value

### Configure in json/config.json
```json
{
  "BOT_TOKEN": "1234567890:ABCdefGHIjklmNOPqrstUVwxyz",
  "CHAT_ID": "123456789",
  "TG_TRADE_ONLY": true,
  "TG_MAX_PER_MIN": 20
}
```

### Available Bot Commands
This table was previously incomplete (listed 5 of the ~20 real commands);
corrected here to match `core/telegram_commander.py::_cmd_help()`.

| Command | Description |
|---------|-------------|
| `/signal {IDX} {CALL\|PUT} {SCORE} [reason]` | Submit a manual signal for review |
| `/signal_call {IDX} {SCORE}` / `/signal_put {IDX} {SCORE}` | Shorthand for the above |
| `/approve {id} [lots]` | Approve a pending manual signal |
| `/reject {id} [reason]` | Reject a pending manual signal |
| `/approve_all` | Approve every pending signal |
| `/pending` | List pending manual signals |
| `/cancel {id}` | Cancel a pending signal |
| `/status` | Bot health + P&L |
| `/balance` | Capital breakdown |
| `/positions` | Open positions |
| `/pnl` | Today's P&L |
| `/perf` | Performance + cumulative metrics |
| `/signals` | Recent signals |
| `/placed {signal_id}` | Mark a system-generated signal (from the admin Signal History report) as "I actually placed this order" — writes to the same record the dashboard's checkbox uses |
| `/unplaced {signal_id}` | Undo the above |
| `/emergency_stop` | Halt ALL trading immediately |
| `/exit`, `/exit_all`, `/move_sl`, `/partial_exit`, `/move_target` | Live position management — require `telegram_allow_live_position_cmds: true` (default `false`) |
| `/help` | Show this list from within Telegram |

Note: `/approve`/`/reject`/`/pending` operate on the **manual signal submission
queue** (new trade entries an analyst is proposing) — a different thing from
`/placed`/`/unplaced`, which mark a signal the *system already generated* as
one you traded, for the historical accuracy report.

---

## 9. Web Dashboard

### Enable Dashboard
In `json/config.json`:
```json
{
  "web_dashboard_enabled": true,
  "web_dashboard_host": "0.0.0.0",
  "web_dashboard_port": 8765
}
```

### Access Dashboard
- Open browser to: `http://localhost:8765`
- Login with admin credentials

### Dashboard Features
| Page | Description |
|------|-------------|
| Dashboard | System overview, capital, P&L — also shows the "Install as a mobile app" card (see Mobile Access below) |
| Signals | Generated trading signals, with daily/weekly/monthly/yearly filters and an "Order Placed?" checkbox per signal for your own historical record |
| Payoff Calculator | Build a multi-leg option strategy and see its P&L payoff curve, max profit/loss, and break-evens — read-only decision support, never places an order |
| Trades | Trade history with details |
| Risk | Risk metrics and limits |
| Health | System health check |
| Config | Configuration editor (admin) |
| Users | User management (admin) |
| Intelligence | All 27 intelligence modules |

### Mobile Access (Installable PWA)
The dashboard installs to a phone home screen like a normal app — no Play
Store or App Store involved. Open the dashboard's HTTPS address in Chrome
(Android: "Install app") or Safari (iPhone: "Add to Home Screen"). Full
detail, including the one real requirement (HTTPS, or `localhost` on the
same machine — a plain LAN IP won't trigger the install prompt) and two
practical ways to get HTTPS on your home network, is in
`docs/MOBILE_APP_PWA_GUIDE.md`.

### API Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/system/state` | System state |
| `GET` | `/api/system/trades` | Trade history |
| `GET` | `/api/system/health` | Health check |
| `GET` | `/api/system/signals` | Recent signals |
| `GET` | `/api/intelligence/summary` | All intelligence |
| `POST` | `/signals/inject` | Webhook signal |
| `GET` | `/chain/{index}` | Options chain |
| `POST` | `/api/auth/signals/{signal_id}/mark-order-placed` | Mark/unmark "I placed this order" on a signal |
| `POST` | `/api/payoff-calculator/compute` | Compute a payoff curve for a multi-leg option strategy |

This is a representative sample, not the full list — the dashboard is a
FastAPI app that auto-generates a complete, always-current endpoint
reference at `/docs` (Swagger UI) once `web_dashboard_enabled: true`. See
`docs/api_reference.md`.

---

## 10. Risk Management

### 3-Layer Risk Protection

**Layer 1: Pre-Trade**
| Check | Description |
|-------|-------------|
| Daily loss limit | Max -6% of capital per day |
| Max drawdown | 30% hard halt |
| VIX check | VIX > 27 blocks all entries |
| Expiry day cutoff | No entries after 13:30 IST |
| Correlation guard | Blocks correlated index entries |
| Liquidity check | Min OI + volume thresholds |
| Event calendar | Budget/RBI/FOMC day filter |

**Layer 2: In-Trade**
| Check | Description |
|-------|-------------|
| Stop loss | Entry × 0.88 |
| Target | Entry × 1.30 |
| Trailing stop | Peak price × 0.93 |
| Max position age | 120 minutes |
| Partial exit | Lock profit at entry × 1.15 |
| EOD squaring off | 15:20 IST |

**Layer 3: System**
| Check | Description |
|-------|-------------|
| Hard halt | Drawdown ≥ 30% |
| Kill file | Drop `STOP_TRADING` file |
| Watchdog thread | Monitors scan loop |
| Circuit breaker | API failure rate limit |
| Shutdown event | Graceful stop |

### Emergency Stop
```bash
# Method 1: Drop kill file
echo "stop" > STOP_TRADING

# Method 2: Telegram command
/kill

# Method 3: Keyboard interrupt
Ctrl+C
```

---

## 11. Monitoring & Alerts

### Telegram Alerts
The bot sends alerts for:
- **New signals** (with score and direction)
- **Trade entries** (with price and quantity)
- **Trade exits** (with P&L)
- **Risk violations** (loss limits, drawdown)
- **Errors** (API failures, data issues)
- **Daily summary** (EOD report)

### System Health Check
```bash
# Run health check
python -m core.health_checker

# JSON format
python -m core.health_checker --format json
```

### Prometheus Metrics
If enabled (default port 9090):
```bash
curl http://localhost:9090/metrics
```

### Logging
Logs are stored in `logs/` directory:
- 50 MB max file size
- Auto-rotation with gzip compression
- Error-only handler for critical issues
- Structured logging format available

---

## 12. Backtesting

### Run Backtest
```bash
# Default backtest
python run_backtest.py

# With custom config
python run_backtest.py --config config.backtest.json

# Specific date range
python run_backtest.py --start 2026-01-01 --end 2026-06-30
```

### Walk-Forward Analysis
```bash
# Anchored walk-forward
python -m core.walkforward_engine --mode anchored

# Rolling walk-forward
python -m core.walkforward_engine --mode rolling
```

### Monte Carlo Simulation
```bash
# Run Monte Carlo on trade results
python -m core.monte_carlo --n 1000 --seed 42
```

### A/B Strategy Testing
```bash
# Run control vs variant
python -m core.ab_strategy_tester

# Reset A/B state
python -m core.ab_strategy_tester --reset
```

### Parameter Sensitivity
```bash
# Test sensitivity of SL_PCT
python -m core.sensitivity_analyzer --param SL_PCT --days 60

# Test all parameters
python -m core.sensitivity_analyzer
```

### Backtest Performance Metrics
| Metric | Paper Performance (55 Trades) |
|--------|:----------------------------:|
| Win Rate | 54.5% |
| Profit Factor | 2.54 |
| Sharpe Ratio | 6.99 |
| Total PnL | ₹3,252 |
| Avg PnL/Trade | ₹59.13 |
| Max Drawdown | 0% |

---

## 13. Performance Reports

### Generate PDF Report
```bash
# Last 30 days
python -m core.report_generator --days 30

# All trades
python -m core.report_generator --days 365

# Specific mode
python -m core.report_generator --days 30 --mode PAPER
```

### Generate PowerPoint Presentation
```bash
# Generate all templates
python -c "
from core.presentation_generator import get_presentation_generator
gen = get_presentation_generator(output_dir='reports/presentations')
gen.generate_all({'version': '2.56.0'})
"
```

### View Performance Metrics
```bash
python -m core.performance_metrics --days 30
```

### Signal Autopsy
```bash
python -m core.signal_autopsy --days 30 --top 10
```

---

## 14. Docker Deployment

### Prerequisites
- Docker Desktop installed
- 4 GB RAM allocated to Docker

### Quick Start
```bash
docker compose up -d
```

### View Logs
```bash
docker compose logs -f opb
```

### Stop
```bash
docker compose down
```

### Custom Configuration
Set environment variables in `docker-compose.yml`:
```yaml
environment:
  - OPBUYING_BASE_CAPITAL=10000
  - OPBUYING_EXECUTION_MODE=PAPER
  - OPBUYING_BOT_TOKEN=${BOT_TOKEN}
  - OPBUYING_CHAT_ID=${CHAT_ID}
```

---

## 15. Kubernetes Deployment

### Prerequisites
- Kubernetes cluster (minikube, kind, or cloud)
- kubectl configured
- kustomize installed

### Deploy
```bash
# Apply all resources
kubectl apply -k k8s/

# Check pods
kubectl get pods -n opb-trading

# View logs
kubectl logs -n opb-trading deployment/opb-deployment
```

### Canary Deployment
```bash
# Deploy canary variant (with DatabaseProvider probes)
kubectl apply -f k8s/canary-deployment.yaml

# Monitor canary
kubectl get pods -n opb-trading -l track=canary
```

### Scale
```bash
# Scale stable deployment
kubectl scale deployment/opb-deployment -n opb-trading --replicas=3
```

---

## 16. Troubleshooting

### Common Issues

**Issue: "No module named 'core'"**
```bash
pip install -e .
```

**Issue: "Connection refused to NSE API"**
- NSE blocks automated requests (Akamai protection)
- The system gracefully falls back to yfinance
- This is expected behavior

**Issue: "Database is locked"**
- SQLite has single-writer limitation
- Use PostgreSQL for concurrent access:
  ```json
  {
    "DB_PROVIDER": "postgresql",
    "pg_host": "localhost",
    "pg_dbname": "opb_trades"
  }
  ```

**Issue: "No signals generated"**
- Check market hours (09:15-15:20 IST)
- Verify VIX is within range (12-27)
- Check if event calendar is blocking

**Issue: "Telegram not working"**
- Verify `BOT_TOKEN` and `CHAT_ID`
- Check internet connectivity
- Review logs for Telegram errors

**Issue: "Trader won't start"**
```bash
# Check Python version
python --version  # Must be 3.10-3.19

# Check dependencies
pip list | grep -E "numpy|pandas|fastapi"

# Check for lock file
del trader.lock  # Remove stale lock
```

### Logs Location
| Platform | Log Path |
|----------|----------|
| Windows | `logs/opbuying_YYYYMMDD.log` |
| Linux | `logs/opbuying_YYYYMMDD.log` |
| Docker | `docker compose logs opb` |
| K8s | `kubectl logs -n opb-trading deployment/opb-deployment` |

### Health Check Commands
```bash
# Quick health check
python -m core.health_checker

# Database health
python -c "from core.db_provider import get_database; print(get_database().health_check())"

# ML model health
python -c "from core.ml_performance_tracker import check_ml_health; print(check_ml_health())"
```

---

## 17. FAQ

**Q: What is the minimum capital required?**
A: ₹5,000 recommended for paper trading. ₹5,00,000 minimum for live.

**Q: Can I use this with any broker?**
A: Supports Zerodha Kite and Angel Broking. The PaperBroker can simulate any broker.

**Q: Is the system profitable?**
A: Paper trading shows 54.5% win rate with 2.54 profit factor. Past performance does not guarantee future results.

**Q: Does it work on weekends?**
A: No. The NSE is closed Saturday and Sunday. The bot sleeps until Monday 09:15 IST.

**Q: Can I customize the strategy?**
A: Yes. All parameters are configurable via `json/config.json`. See `CONFIG_EXPLANATIONS.md` for details.

**Q: How much time do I need to monitor?**
A: Paper mode: 30 min/day for review. Live mode: monitor first week closely, then 15 min/day.

**Q: What happens if the internet goes down?**
A: The bot will:
1. Detect connection loss
2. Log pending operations
3. Attempt reconnection with backoff
4. Resume trading when connection restores
5. Reconcile any missed orders

**Q: How do I migrate from SQLite to PostgreSQL?**
A: See `docs/MIGRATION_PLAN.md` for step-by-step instructions.

---

## Appendix A: Quick Reference

### CLI Commands
| Command | Purpose |
|---|---|
| `python -m core.all_nse_scanner` | Run full NSE 2,500+ stock universe strategy scan |
| `python index_app/index_trader.py --paper --equity` | Start paper trading with equity + index options |
| `python index_app/index_trader.py` | Start live trading |
| `python -m core.report_generator --days 30` | Generate PDF report |
| `python -m core.health_checker` | Run health check |
| `python -m core.performance_metrics --days 30` | View performance |
| `python -m core.trade_replayer --id 42` | Replay trade |
| `python -m core.sensitivity_analyzer` | Parameter sensitivity |
| `python -m core.live_readiness_checker` | Paper→Live gate |
| `python run_backtest.py` | Run backtest |

### File Locations
| File | Purpose |
|------|---------|
| `json/index_config.defaults.json` | Default configuration |
| `json/config.json` | User configuration |
| `json/trader_state.json` | Runtime state (restart recovery) |
| `db/trades.db` | Trade database |
| `json/trader_state.json` | Capital, PnL, flags |
| `STOP_TRADING` | Kill file (emergency stop) |

### Market Hours
| Event | Time (IST) |
|-------|:----------:|
| Pre-open | 09:00 |
| Market open | 09:15 |
| Continuous trading | 09:20 – 15:20 |
| Block new entries | 15:00 |
| Expiry cutoff | 13:30 |
| Market close | 15:30 |

---

*End of User Guide. For detailed configuration options, see `CONFIG_EXPLANATIONS.md`. For deployment details, see `docs/DEPLOYMENT_GUIDE.md`.*
