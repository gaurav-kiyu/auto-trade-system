# HOW TO USE THE OPB SYSTEM
## Complete Step-by-Step Guide
### From First Install to Full Production Trading

**System:** OPB Index Options Buying Bot v2.59.0  
**Target:** NSE Index Options (NIFTY / BANKNIFTY / FINNIFTY) + Equities, Futures, Commodities, Currency  
**Last Updated:** July 27, 2026

---

## TABLE OF CONTENTS

1. [What This System Does](#1-what-this-system-does)
2. [System Requirements](#2-system-requirements)
3. [Installation Guide](#3-installation-guide)
4. [Configuration Guide](#4-configuration-guide)
5. [First Run — Paper Trading](#5-first-run--paper-trading)
6. [Understanding the Dashboard](#6-understanding-the-dashboard)
7. [Manual Trading Workflow](#7-manual-trading-workflow)
8. [Advanced Features & CLI Tools](#8-advanced-features--cli-tools)
9. [Web Dashboard Setup](#9-web-dashboard-setup)
10. [Backtesting](#10-backtesting)
11. [Live Trading Preparation](#11-live-trading-preparation)
12. [Docker Deployment](#12-docker-deployment)
13. [Monitoring & Alerting](#13-monitoring--alerting)
14. [Recovery Procedures](#14-recovery-procedures)
15. [Troubleshooting](#15-troubleshooting)
16. [Certification & System Health](#16-certification--system-health)
17. [Appendix: Quick Command Reference](#17-appendix-quick-command-reference)
18. [Appendix: File Reference](#18-appendix-file-reference)
19. [Appendix: Configuration Key Reference](#19-appendix-configuration-key-reference)

---

## 1. WHAT THIS SYSTEM DOES

OPB (Options Buying Bot) is an **automated NSE index options trading system** that:

- **Scans** NIFTY, BANKNIFTY, and FINNIFTY indices every 60 seconds
- **Analyzes** 1-minute, 5-minute, and 15-minute market data using 14+ indicators

---

## 1.1 System URLs & Direct Batch Launchers

| Domain / Purpose | Web URL | Direct Batch Launcher | Role | Access Scope |
|---|---|---|---|---|
| 🔐 **Admin Dynamic Config** | **`http://localhost:8765/admin/config`** | **`open_admin.bat`** | Admin | Live strategy tuning, lot sizes, signal score cutoffs & broker settings. |
| 👥 **Admin User Control** | **`http://localhost:8765/admin/users`** | `open_admin.bat` | Admin | User management & role-based access control (Admin, Operator, Trader). |
| 🚨 **Admin Kill-Switch** | **`http://localhost:8765/admin/kill-switch`** | `open_admin.bat` | Admin | Emergency halt, order cancellation & system worker isolation. |
| 📈 **End-User Trading UI** | **`http://localhost:8765/`** | **`open_app.bat`** | End-User / Trader | Live market tick stream, signal feed & active positions. |
| 🧠 **AI SHAP Explainer** | **`http://localhost:8765/intelligence`** | `open_app.bat` | End-User / Trader | AI feature attribution (SHAP values) explaining every trade signal. |

The dashboard is `core/enterprise_dashboard/` (FastAPI + Jinja2 + RBAC), disabled by
default — set `web_dashboard_enabled: true` in `json/config.json` to activate it.
Batch launchers (`open_admin.bat`, `open_app.bat`) are at the repo root.
- **Generates** trading signals with a 0-100 score and direction (CALL/PUT)
- **Manages** positions with stop-loss, target, trailing stop, and partial exits
- **Tracks** P&L, risk metrics, and performance analytics
- **Supports** Paper (simulated), Manual (signals only), and Auto (live broker) modes
- **Multi-Asset Trading** Equities, Futures, Commodities (MCX), Currency (CDS)
- **Enterprise Dashboard** FastAPI web dashboard with RBAC, health monitoring, event store

### What It Does NOT Do (Important!)

- ❌ Does not guarantee profits — all trading involves risk
- ❌ Does not predict the future — it analyzes probabilities
- ❌ Does not work in flat/choppy markets — no signal is a valid signal
- ❌ Does not replace your judgment — always verify signals before trading

---

## 2. SYSTEM REQUIREMENTS

### Minimum Requirements

| Component | Requirement | Notes |
|-----------|-------------|-------|
| **Operating System** | Windows 10+, Linux, macOS | Windows is primary; Linux/Docker compatible |
| **Python** | 3.10 – 3.19 | Download from [python.org](https://python.org) |
| **RAM** | 4 GB minimum | 8 GB recommended |
| **Disk Space** | 500 MB free | For code, data, logs |
| **Internet** | Broadband connection | Required for market data (yfinance) |
| **Python Packages** | ~30 packages | See requirements.txt |

### Optional Requirements

| Component | Required For |
|-----------|-------------|
| **Telegram Account** | Real-time alerts and notifications |
| **Broker Account (Zerodha/Angel)** | Live automated trading |
| **Docker Desktop** | Containerized deployment |
| **Chrome/Firefox** | Web dashboard access |

### Step 2.1: Check Your Python Version

Open a terminal and run:
```bash
python --version
```

Expected output: `Python 3.10.x`, `3.11.x`, `3.12.x`, or `3.13.x`

> ⚠️ **Troubleshooting:** If `python` is not recognized, try `python3` or reinstall Python with "Add Python to PATH" checked.

---

## 3. INSTALLATION GUIDE

### Step 3.1: Get the Code

**Option A: Download ZIP**
1. Go to the repository page
2. Click **Code → Download ZIP**
3. Extract to a folder (e.g., `C:\OPB` or `~/OPB`)

**Option B: Clone with Git**
```bash
git clone <repository-url> opb
cd opb
```

### Step 3.2: Install Dependencies

```bash
# Navigate to the bot folder
cd C:\OPB   # Windows
cd ~/opb    # Linux/Mac

# Install required packages
pip install -r requirements.txt
```

**What gets installed:**

| Category | Packages |
|----------|----------|
| **Core** | requests, pandas, numpy, yfinance, jsonschema |
| **Web Dashboard** | flask, flask-socketio, fastapi, uvicorn |
| **ML Classifier** | lightgbm, scikit-learn, shap |
| **Reports** | reportlab, python-pptx |
| **Broker** | kiteconnect, pyotp, psycopg2-binary |
| **Monitoring** | prometheus-client, opentelemetry-* |
| **Database** | psycopg2-binary (PostgreSQL), duckdb |
| **CI/CD** | pytest, ruff, mypy, coverage |

### Step 3.3: Verify Installation

```bash
# Quick check
python -c "import yfinance, pandas, numpy; print('All OK')"

# Full test suite (~2670 tests, ~4.5 minutes)
python -m pytest tests/ -q
```

Expected test output: All tests pass (~2670 passed)

---

## 4. CONFIGURATION GUIDE

### Step 4.1: Understanding the Config System

The bot uses a **4-layer configuration merge**:

```
Priority (lowest → highest)
─────────────────────────────────────────
Layer 1: json/index_config.defaults.json   (all defaults, 974+ keys)
Layer 2: json/config.json                  (your personal overrides)
Layer 3: json/config.local.json            (machine-specific, gitignored)
Layer 4: OPBUYING_* environment vars  (secrets, highest priority)
```

> **Rule:** Never modify `json/index_config.defaults.json` directly. Create `json/config.json` for your changes.

### Step 4.2: Basic Configuration (json/config.json)

Create `json/config.json` in the project root:

```json
{
  "EXECUTION_MODE": "PAPER",
  "BROKER_API_ENABLED": false,
  "BASE_CAPITAL": 5000,
  "MAX_DAILY_LOSS": -300,
  "MAX_DRAWDOWN": 0.3,
  "MAX_OPEN": 1,
  "MAX_TRADES_DAY": 2,
  "AI_THRESHOLD": 60,
  "SCAN_INTERVAL": 60,
  "SL_PCT": 0.88,
  "TARGET_PCT": 1.30,
  "TRAIL_PCT": 0.93,
  "TRAIL_ACTIVATE_PCT": 1.10,
  "PARTIAL_EXIT_MULT": 1.15,
  "REPORT_EOD_AUTO_GENERATE": false
}
```

### Step 4.3: Key Settings Explained

| Setting | Default | What It Does |
|---------|---------|-------------|
| `EXECUTION_MODE` | `PAPER` | `PAPER`=simulated, `MANUAL`=signals only, `AUTO`=live trading |
| `BROKER_API_ENABLED` | `false` | Set `true` only when connecting to real broker |
| `BASE_CAPITAL` | 5000 | Virtual/live capital in INR |
| `MAX_DAILY_LOSS` | -300 | Hard stop: block new entries after this daily loss |
| `MAX_DRAWDOWN` | 0.30 | Emergency halt: 30% total capital loss |
| `MAX_OPEN` | 1 | Maximum simultaneous positions |
| `MAX_TRADES_DAY` | 4 | Maximum entries per day |
| `AI_THRESHOLD` | 60 | Minimum signal score (0-100) for trade entry |
| `SL_PCT` | 0.88 | Stop loss at 88% of entry premium |
| `TARGET_PCT` | 1.30 | Take profit at 130% of entry premium |
| `TRAIL_PCT` | 0.93 | Trailing stop at 93% of peak premium |
| `SCAN_INTERVAL` | 60 | Seconds between market scans |

### Step 4.4: Telegram Configuration (Optional)

**Get a Bot Token:**
1. Open Telegram, search for `@BotFather`
2. Send: `/newbot`
3. Follow prompts, save the token

**Get Your Chat ID:**
1. Message your bot
2. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find `"chat":{"id":1234567890}`

**Add to json/config.local.json:**
```json
{
  "BOT_TOKEN": "7012345678:AAH-your-token-here",
  "CHAT_ID": "1234567890"
}
```

> ⚠️ `json/config.local.json` is automatically gitignored — safe for secrets.

### Step 4.5: Broker Configuration (For Live Trading Only)

```json
{
  "EXECUTION_MODE": "PAPER",
  "BROKER_API_ENABLED": true,
  "BROKER_DRIVER": "KITE",
  "BROKER_CONFIG": {
    "api_key": "your_kite_api_key",
    "access_token": "your_access_token"
  }
}
```

> ⚠️ Keep `EXECUTION_MODE: "PAPER"` while testing broker connection. Switch to `"AUTO"` only after readiness checks pass.

---

## 5. FIRST RUN — PAPER TRADING

### Enhanced Paper Trading (v2.57.0)

The paper trading simulator now includes **live-like simulation features**:

| Feature | What It Simulates | Realism |
|---------|------------------|---------|
| **Bid-Ask Spread** | Market orders fill at ask (buy) or bid (sell) | ✅ NSE-style |
| **Random Walk Prices** | Prices evolve between calls with volatility scaling and mean reversion drift | ✅ Like real ticks |
| **Partial Fills** | Large orders (>1% of notional OI) get partial fills | ✅ Real exchange behavior |
| **Market Impact** | Orders >₹5L notional move price against the trader (0.1% per 1% OI) | ✅ Institution-grade |
| **Indian Broker Commission** | Full STT, exchange fees, GST 18%, SEBI turnover, stamp duty | ✅ Zerodha-style pricing |
| **Circuit Limits** | ±20% price limits matching NSE circuit filters | ✅ Exchange-grade |
| **Fill Delays** | Randomized 25ms-100ms network + exchange processing delay | ✅ Realistic |
| **Rate Limiting** | Max 20 fills per 5-minute rolling window per symbol | ✅ Market abuse prevention |

**Commission Breakdown Example** (NIFTY option trade, notional ₹4,500):
| Component | Amount |
|-----------|--------|
| Brokerage | ₹4.50 (0.03%, capped at ₹20) |
| STT | ₹2.25 (0.05% on sell) |
| Exchange | ₹0.09 (0.002%) |
| GST 18% | ₹0.83 (on brokerage + exchange) |
| SEBI Turnover | ₹0.004 (₹10/crore) |
| Stamp Duty | ₹0.09 (0.002%) |
| **Total** | **~₹7.77** |

### Step 5.1: Start the Bot

```bash
python -m index_app.index_trader --paper
```

You should see:
```
[INFO] Starting OPB Index Options Bot v2.57.0
[INFO] Execution mode: PAPER
[INFO] Config loaded successfully
[INFO] Market status: CLOSED (scanning will begin at 09:15 IST)
```

### Step 5.2: What Happens When Market Opens

| Time (IST) | Bot Behavior |
|------------|-------------|
| Before 09:15 | Bot waits silently |
| 09:15 - 09:20 | Market opens, bot initializes (too noisy for signals) |
| **09:20 - 15:20** | **Active trading — scanning every 60 seconds** |
| 15:20 - 15:30 | Positions closed, no new entries |
| After 15:30 | EOD report sent, waits for next day |

### Step 5.3: Alternative Startup Methods

```bash
# Console only (no GUI)
python -m index_app.index_trader --paper --nogui

# Custom config file
OPBUYING_INDEX_CONFIG=config.my.json python -m index_app.index_trader --paper

# Debug mode (verbose logging)
python -m index_app.index_trader --paper --debug

# GUI Launcher (Windows)
# Double-click: OPBuying_INDEX_Launcher.exe

# Low Capital Mode (Rs.5,000 pre-configured)
# Double-click: run_low_capital.bat
```

### Step 5.4: Stop the Bot

Press `Ctrl + C` in the terminal. The bot will:
1. Save trading state to `json/trader_state.json`
2. Close any cleanup tasks
3. Exit gracefully

---

## 6. UNDERSTANDING THE DASHBOARD

### Console Dashboard Layout

```
══════════════════════════════════════════════════════════════════
  INDEX OPTIONS BUYING BOT v2.57.0  [PAPER]  01-Apr-2026 11:30
  Capital: ₹5,000  Day P&L: ▲ +₹150  Trades: 1/2  Positions: 1/1
══════════════════════════════════════════════════════════════════

  ┌─ NIFTY ──────────────────────────────────────────────────┐
  │ Score: 78/60 | CALL | STRONG | ⭐⭐⭐                    │
  │ CMP: 23,500 | Premium Est: ₹180 | Risk: ₹432            │
  │ WHY: Trend UP on 5m+15m, Price > VWAP, Vol 1.8x         │
  └──────────────────────────────────────────────────────────┘
```

### Reading the Dashboard

| Element | Meaning |
|---------|---------|
| `[PAPER]` | Trading mode (PAPER/MANUAL/LIVE) |
| `Capital: ₹5,000` | Current virtual/real capital |
| `Day P&L: ▲ +₹150` | Today's profit (▲=up, ▼=down) |
| `Trades: 1/2` | 1 trade used out of 2 allowed today |
| `Positions: 1/1` | 1 position out of 1 maximum |
| `Score: 78/60` | Signal score 78, minimum threshold 60 |
| `CALL` | Direction: CALL (bullish) or PUT (bearish) |
| `STRONG` | Strength: WEAK / MODERATE / STRONG |
| `⭐⭐⭐` | Stars: visual strength indicator |
| `Premium Est: ₹180` | Estimated option premium cost |
| `Risk: ₹432` | Estimated maximum risk (premium × lot × risk%) |

### Understanding Signal Types

| Signal | Description |
|--------|-------------|
| **STRONG (⭐⭐⭐⭐)** | All indicators aligned, 85-100 score |
| **MODERATE (⭐⭐⭐)** | Good setup, 70-84 score |
| **WEAK (⭐⭐)** | Borderline, 60-69 score |
| **No Signal** | Below 60 or conflicting indicators |

---

## 7. MANUAL TRADING WORKFLOW

### Step 7.1: When You See A Signal

The dashboard shows an actionable signal like:
```
NIFTY — Strong CALL  Score: 82/60
```

### Step 7.2: Execute the Trade

1. **Open your broker app** (Zerodha Kite, Angel One, etc.)
2. **Go to NIFTY options chain**
3. **Select nearest weekly expiry**
4. **Choose ATM (At-The-Money) CALL option** — strike closest to current NIFTY price
5. **Buy 1 lot** at market price
6. **Set Stop Loss** at entry price × 0.88
7. **Set Target** at entry price × 1.30

### Step 7.3: Monitor the Position

The bot will track the position and display:
```
  Open Positions:
  Index   Side  Entry     CMP       P&L      %     Target   SL    Age
  NIFTY   CE    ₹180.0   ₹205.3  ▲ +₹632  +14.0%  ₹234.0  ₹158.4  22m
```

### Step 7.4: Exit Rules (Auto-Enforced by Bot)

The bot checks exits every scan cycle in this order:
```
1. 3:20 PM → EXIT ALL (market closing)
2. Position age > 120 min → EXIT (stale trade)
3. Price ≤ Stop Loss → EXIT (max loss hit)
4. Price ≤ Trailing SL → EXIT (protect gains)
5. Price ≥ Target → EXIT (profit taken)
```

### Step 7.5: Lot Sizes

| Index | Lot Size | Strike Gap |
|-------|----------|------------|
| NIFTY | 25 | ₹50 |
| BANKNIFTY | 15 | ₹100 |
| FINNIFTY | 40 | ₹50 |

---

## 8. ADVANCED FEATURES & CLI TOOLS

### Performance Reports
```bash
# Generate PDF report for last 30 days
python -m core.report_generator --days 30 --mode PAPER

# Performance metrics table
python -m core.performance_metrics --days 60 --db db/trades.db
```

### Trade Replay (Watch Past Trades)
```bash
# Replay specific trade
python -m core.trade_replayer --id 42

# View last 5 trades
python -m core.trade_replayer --last 5

# View worst 3 trades
python -m core.trade_replayer --worst 3
```

### Parameter Sensitivity Analysis
```bash
# Test how SL_PCT affects results
python -m core.sensitivity_analyzer --param SL_PCT --days 60

# Run full analysis on all params
python -m core.sensitivity_analyzer
```

### Health Checks
```bash
# System health check
python -m core.health_checker

# JSON format for scripting
python -m core.health_checker --format json
```

### Live Readiness Check
```bash
# Must pass ALL 5 checks before going live
python -m core.live_readiness_checker
```

### A/B Strategy Testing
```bash
# View current A/B test state
python -m core.ab_strategy_tester

# Reset A/B test
python -m core.ab_strategy_tester --reset
```

### Trade Journal & P&L Attribution
```bash
# P&L breakdown by direction/regime/session
python -m core.pnl_attribution --days 30
```

### Monte Carlo Simulation
```bash
# Run trade P&L simulations
python -m core.monte_carlo --n 1000 --days 60
```

### Parameter Optimization
```bash
# Sweep SL_PCT over values
python -m core.param_optimizer --param SL_PCT --values 0.85,0.88,0.90,0.92
```

### Governance Tools
```bash
# Constitution scoring (23 categories)
python scripts/score_system.py

# Pre-implementation check (before any code change)
python scripts/pre_implementation_check.py --files core/foo.py

# Release governance check
python scripts/release_governance.py --check
```

---

## 9. WEB DASHBOARD SETUP

### Step 9.1: Enable Dashboard

In `json/config.json`:
```json
{
  "web_dashboard_enabled": true
}
```

### Step 9.2: Start the Dashboard

```bash
# The dashboard starts automatically INSIDE the same process as the bot
# when web_dashboard_enabled is true - there is no separate standalone
# "python -m core.enterprise_dashboard" command (that module has no
# __main__.py). Just start the bot normally:
python -m index_app.index_trader --paper
```

### Step 9.3: Access the Dashboard

Open your browser: `http://localhost:8765`

### Dashboard Features

| Feature | Description |
|---------|-------------|
| **System State** | Current capital, P&L, open positions, mode |
| **Trade History** | All trades with search and filter |
| **Performance Charts** | Equity curve, win rate, Sharpe ratio |
| **Live Signals** | Current signals with score breakdown |
| **Risk Metrics** | VaR, drawdown, exposure, margin used |
| **Health Status** | Database, broker, ML model health |
| **Configuration** | View and edit config (admin only) |
| **Kill Switch** | Emergency stop button (admin only) |

### Authentication

The dashboard uses RBAC (Role-Based Access Control):
- **Admin:** Full access to config, users, kill switch
- **Operator:** View trades, signals, health
- **Viewer:** Read-only dashboard

Default login credentials are set during first dashboard startup.

---

## 10. BACKTESTING

### Quick Backtest
```bash
# Run 30-day backtest on NIFTY
python run_backtest.py --yf-quarter --yf-symbol ^NSEI --yf-days 30
```

### Multi-Index Suite
```bash
# Test all 3 indices
python scripts/run_backtest_suite.py
```

### Walk-Forward Validation
```bash
# Anchored walk-forward
python -m core.walkforward_engine --csv tests/fixtures/replay_minute_bars.csv
```

### JSON Output for Analysis
```bash
python run_backtest.py --yf-quarter --json
# Results in: reports/backtest_results.json
```

### Understanding Backtest Results

| Metric | What It Measures | Good Target |
|--------|-----------------|-------------|
| **Win Rate** | % of profitable trades | >45% |
| **Profit Factor** | Gross profit / gross loss | >1.5 |
| **Sharpe Ratio** | Risk-adjusted returns | >1.0 |
| **Max Drawdown** | Largest peak-to-trough decline | <15% |
| **Expectancy** | Average profit/loss per trade | Positive |
| **Total Trades** | Number of trades in period | >30 for significance |

---

## 11. LIVE TRADING PREPARATION

### Step 11.1: Paper Trading Scorecard

Before switching to live, run paper mode for a minimum of 30 trades and verify:

```bash
python -m core.live_readiness_checker
```

### Step 11.2: The 5 Gates to Live Trading

| Gate | Requirement | Check |
|------|-------------|-------|
| 1. Paper Score | Paper trading scorecard ≥ 7/10 | `live_readiness_checker` |
| 2. Trade Count | Minimum 30 paper trades completed | Check `db/trades.db` |
| 3. Profitability | Profit factor > 1.5 | `performance_metrics.py` |
| 4. Win Rate | Win rate > 45% | `performance_metrics.py` |
| 5. Risk Control | Max drawdown < 15% | `performance_metrics.py` |

### Step 11.3: Transition Checklist

- [ ] Run `python -m core.live_readiness_checker` — **all 5 gates pass**
- [ ] Create broker account (Zerodha/Angel)
- [ ] Configure broker credentials in `json/config.local.json`
- [ ] Set `BROKER_API_ENABLED: true` with `EXECUTION_MODE: PAPER` (test connection)
- [ ] Run paper mode for 24 hours with broker connection active
- [ ] Verify reconciliation logs show no errors
- [ ] Set `EXECUTION_MODE: AUTO`
- [ ] Start with small capital (₹5,000 - ₹10,000)
- [ ] Monitor first day closely

### Important Safety Rules

- **Never** start live with more capital than you can afford to lose
- **Always** have the Telegram alerts configured
- **Know** how to create the `STOP_TRADING` emergency file
- **Remember:** A missed trade is better than a wrong trade

---

## 12. DOCKER DEPLOYMENT

### Step 12.1: Install Docker

Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop/).

### Step 12.2: Configure for Docker

Create `json/config.local.json` in the project root:
```json
{
  "EXECUTION_MODE": "PAPER",
  "BROKER_API_ENABLED": false,
  "BOT_TOKEN": "your_telegram_token",
  "CHAT_ID": "your_chat_id"
}
```

### Step 12.3: Start the Bot

```bash
# Build and start (paper mode by default)
docker compose up -d

# View logs
docker compose logs -f opb

# Stop
docker compose down
```

### Step 12.4: Docker Volumes

| Host Path | Container Path | Purpose |
|-----------|---------------|---------|
| `./config.json` | `/app/config.json` | Configuration |
| `./config.local.json` | `/app/config.local.json` | Secrets |
| `./data/` | `/app/data/` | Persistent data |
| `./logs/` | `/app/logs/` | Log files |

---

## 13. MONITORING & ALERTING

### Telegram Alerts

Once Telegram is configured, you'll receive:

| Alert Type | Trigger | Example |
|-----------|---------|---------|
| **Signal Generated** | Strong signal detected | `🔵 NIFTY CALL Score: 82 — STRONG` |
| **Trade Opened** | Position entered | `🟢 NIFTY 23500 CE @ ₹180 — Target ₹234 SL ₹158` |
| **Trade Closed** | Position exited | `🔴 NIFTY CE Closed: +₹632 (14.0%)` |
| **SL Hit** | Stop loss triggered | `🔴 NIFTY CE SL HIT: -₹432 (12.0%)` |
| **Target Hit** | Profit target reached | `🟢 NIFTY CE TARGET HIT: +₹1,350 (30.0%)` |
| **Daily Summary** | EOD report | `📊 Day: +₹1,250 | Win Rate: 60% | Trades: 5` |
| **Health Alert** | System issue | `⚠️ yfinance rate limit — using cache` |
| **Error Alert** | System error | `🚨 Risk check failed — no entry` |

### Health Monitoring

```bash
# Quick health check
python -m core.health_checker

# Automated check runs every Sunday EOD when bot is active
```

### Metrics Export (Prometheus)

If enabled in config, metrics are available at port 9090:
```
http://localhost:9090/metrics
```

Available metrics:
- `opb_capital` — Current capital
- `opb_daily_pnl` — Daily P&L
- `opb_open_positions` — Open positions count
- `opb_total_trades` — Total trades executed
- `opb_win_rate` — Historical win rate
- `opb_max_drawdown` — Current drawdown

---

## 14. RECOVERY PROCEDURES

### After a Crash

The bot auto-recovers on restart:
```bash
python -m index_app.index_trader --paper
```

Recovery process:
1. Reads saved state from `json/trader_state.json`
2. Reconciles open positions
3. Resumes monitoring

### Hard Halt Recovery

If you see `HARD_HALT`:
1. Check your broker — what positions are open?
2. Check the bot's stored state
3. If they differ, manually close broker positions
4. Restart the bot

### Emergency Stop

Create file `STOP_TRADING` in the bot's root folder:
```
echo > STOP_TRADING
```
The bot detects this and halts within 60 seconds.

### Kill Switch (Dashboard)

Admin users can trigger emergency stop via the web dashboard:
1. Login as admin
2. Navigate to System → Kill Switch
3. Click "EMERGENCY STOP"

---

## 15. TROUBLESHOOTING

### Common Issues

| Problem | Likely Cause | Solution |
|---------|-------------|----------|
| **No signals all day** | Low volatility or flat market | Normal — no signal is safer than bad signal |
| **Score always < threshold** | Market conditions unfavorable | Bot is working correctly — avoid forcing trades |
| **"No data" message** | Market closed or yfinance rate limit | Wait for market hours (9:15-3:30 IST) |
| **yf.RateLimitError** | Too many Yahoo requests | Wait 2-5 minutes (auto-recovers) |
| **ImportError: No module named...** | Missing package | `pip install -r requirements.txt` |
| **Config validation error** | Invalid json/config.json | Check for JSON syntax errors |
| **Telegram not working** | Wrong token/chat ID | Verify BOT_TOKEN and CHAT_ID |
| **HARD_HALT** | Position state mismatch | Follow recovery procedure (Section 14) |
| **Port already in use** | Dashboard already running | Stop other instance or change port |
| **Kite not connecting** | Token expired or API error | Regenerate access token |

### Log Files

All logs are stored in the `logs/` folder:
- **Format:** `trader_YYYY-MM-DD.log`
- **Max size:** 50 MB per file
- **Retention:** Configurable (default 30 days)
- **Compression:** gzip for old logs

### Getting Help

| Resource | Location | Content |
|----------|----------|---------|
| **No-Code Getting Started** | `docs/GETTING_STARTED_NO_CODE.md` | Click-only walkthrough for non-technical users - no terminal needed |
| **How To Use Guide** | This document (`docs/HOW_TO_USE_SYSTEM.md`) | Most current, comprehensive guide |
| **Quick Reference** | `docs/QUICK_START_GUIDE.md` | Fast setup reference |
| **System Setup** | `SYSTEM_SETUP_GUIDE.md` | Full system setup |
| **Runbooks** | `docs/runbooks/` | Incident response procedures |
| **ADRs** | `docs/adr/` | Architecture decisions |
| **Evidence Book** | `docs/certification/EVIDENCE_BOOK.md` | Full evidence trace for all 25+ tools |
| **Closure Certificate** | `docs/FINAL_CLOSURE_CERTIFICATE.md` | Enterprise certification (9.55/10.0) |
| **Docker Security** | `scripts/check_docker_security.py` | 16 CIS benchmark checks |

---

## 16. CERTIFICATION & SYSTEM HEALTH (v2.57.0)

### Automated Certification Pipeline

The system includes a **13-tool automated certification pipeline** for validating system health:

```bash
# Full certification (all 13 tools)
make certify
# Or: python scripts/run_certify.py

# Quick health check (skip slow benchmarks)
make certify-fast
# Or: python scripts/run_certify.py --fast

# CI mode (exit non-zero on failures)
python scripts/run_certify.py --ci
```

**What gets checked (in order):**
| # | Check | Tool | Critical |
|:-:|:------|:-----|:--------:|
| 1 | Database Integrity | `check_db_integrity.py` | ✅ Yes |
| 2 | Config Drift | `check_config_drift.py` | No |
| 3 | Code Quality | `run_code_quality_report.py` | No |
| 4 | Hygiene & Security | `run_hygiene_scan.py` | ✅ Yes |
| 5 | Thread Safety | `check_thread_safety.py` | ✅ Yes |
| 6 | Docker Security | `check_docker_security.py` | ✅ Yes |
| 7 | Print→Logging Migration | `migrate_print_to_logging.py` | No |
| 8 | Quantitative Validation | `quantitative_validation_report.py` | ✅ Yes |
| 9 | Production Preflight | `production_preflight_check.py` | ✅ Yes |
| 10 | Benchmarks (P50/P90/P95) | `run_benchmarks.py` | No |
| 11 | Flamegraph Profiling | `run_flamegraph_profiler.py` | No |
| 12 | Historical Comparison | `historical_comparison.py` | No |
| 13 | Mutation Tests | `run_mutation_tests.py` | No |

**Output:** Unified HTML dashboard at `reports/certification_report.html`

### Individual Health Tools

```bash
# Database integrity check
python scripts/check_db_integrity.py

# Docker CIS security benchmarks (16 checks)
python scripts/check_docker_security.py

# Thread safety analysis (lock ordering, deadlocks)
python scripts/check_thread_safety.py

# Config drift detection
python scripts/check_config_drift.py

# Backup & restore verification
python scripts/run_backup_rotation.py --list
python scripts/verify_restore.py --all

# Production readiness preflight (15-point check)
python scripts/production_preflight_check.py

# Performance benchmarks (P50/P90/P95/P99)
python scripts/run_benchmarks.py

# Quantitative validation (Sharpe, Sortino, Monte Carlo)
python scripts/quantitative_validation_report.py

# System stress testing (5 load scenarios)
python scripts/run_stress_test.py

# Flamegraph CPU profiling
python scripts/run_flamegraph_profiler.py

# Validation script tests (108+ parametrized tests)
python -m pytest tests/test_validation_scripts.py -v
```

---

## 17. APPENDIX: QUICK COMMAND REFERENCE

| Task | Command |
|------|---------|
| **Start paper trading** | `python -m index_app.index_trader --paper` |
| **Start manual mode** | `python -m index_app.index_trader` |
| **Debug mode** | `python -m index_app.index_trader --paper --debug` |
| **GUI Launcher** | `OPBuying_INDEX_Launcher.exe` |
| **Run tests** | `python -m pytest tests/ -q` |
| **Quick smoke test** | `python -m pytest tests/test_smoke.py -v` |
| **PDF Report** | `python -m core.report_generator --days 30` |
| **Health check** | `python -m core.health_checker` |
| **Live readiness** | `python -m core.live_readiness_checker` |
| **Backtest** | `python run_backtest.py --yf-quarter` |
| **Trade replay** | `python -m core.trade_replayer --id 42` |
| **Sensitivity analysis** | `python -m core.sensitivity_analyzer --param SL_PCT` |
| **Print config** | `python -m index_app.index_trader --print-config` |
| **Self-test** | `python -m index_app.index_trader --selftest` |
| **Monte Carlo** | `python -m core.monte_carlo --n 1000` |
| **P&L Attribution** | `python -m core.pnl_attribution --days 30` |
| **Governance score** | `python scripts/score_system.py` |
| **Pre-implementation check** | `python scripts/pre_implementation_check.py` |
| **Regenerate schemas** | `python scripts/generate_config_schemas.py` |
| **Start dashboard** | `python -m core.enterprise_dashboard` |
| **Docker start** | `docker compose up -d` |
| **Docker logs** | `docker compose logs -f opb` |

---

## 18. APPENDIX: FILE REFERENCE

| File/Directory | Purpose |
|---------------|---------|
| `index_app/index_trader.py` | Main trading brain |
| `launcher.py` | GUI launcher wrapper |
| `run_backtest.py` | Backtest runner |
| `json/config.json` | Your configuration overrides |
| `json/config.local.json` | Local secrets (gitignored) |
| `json/index_config.defaults.json` | All default settings (974+ keys) |
| `json/trader_state.json` | Saved trading state |
| `db/trades.db` | Trade log |
| `db/trade_journal.db` | Execution quality |
| `db/ml_tracker.db` | ML prediction tracking |
| `db/oi_snapshots.db` | OI history |
| `core/services/risk_service.py` | Risk management (position sizing, controls) |
| `core/services/execution_service.py` | Order execution |
| `core/services/paper_trader.py` | Enhanced paper fill simulator — bid-ask spread, random walk, Indian broker commissions |
| `core/adaptive_signal.py` | Signal scoring pipeline |
| `core/pure_index_signal.py` | Base signal generation |
| `core/ml_classifier.py` | LightGBM ML classifier |
| `core/adapters/broker_adapters.py` | Broker abstraction layer |
| `core/strategy/plugin_framework.py` | Strategy plugin system |
| `core/monte_carlo.py` | Monte Carlo simulation |
| `core/kelly_sizer.py` | Kelly Criterion sizing |
| `core/var_calculator.py` | Value at Risk calculator |
| `core/stress_tester.py` | Stress test engine |
| `core/report_generator.py` | PDF report generation |
| `core/telegram_commander.py` | Telegram command interface |
| `core/web_dashboard.py` | Web dashboard (legacy) |
| `core/enterprise_dashboard/` | Enterprise web dashboard (FastAPI) |
| `core/logging.py` | Structured logging |
| `core/metrics_exporter.py` | Prometheus metrics |
| `core/constitution/` | Constitution validation engine |
| `core/auth/` | Authentication (RBAC, MFA, SSO) |
| `scripts/run_certify.py` | 13-tool master certification runner |
| `scripts/check_docker_security.py` | 16 CIS Docker benchmark checks |
| `scripts/check_db_integrity.py` | Database integrity check |
| `scripts/check_thread_safety.py` | Thread safety analysis |
| `scripts/check_config_drift.py` | Config drift detection |
| `scripts/verify_restore.py` | Backup restore verification |
| `scripts/run_stress_test.py` | System stress tester |
| `scripts/run_benchmarks.py` | P50/P90/P95/P99 benchmarks |
| `scripts/production_preflight_check.py` | 15-point preflight checklist |
| `docs/` | All documentation |
| `tests/` | Test suite (546 files) |
| `scripts/` | Governance and utility scripts |
| `logs/` | Runtime logs |
| `Dockerfile` | Docker build |
| `docker-compose.yml` | Docker Compose config |
| `k8s/` | Kubernetes manifests |
| `Makefile` | `make certify` / `make certify-fast` targets |

---

## 19. APPENDIX: CONFIGURATION KEY REFERENCE

### Core Trading Settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `EXECUTION_MODE` | string | `"PAPER"` | `PAPER`, `MANUAL`, `AUTO`, `SHADOW` |
| `BROKER_API_ENABLED` | bool | `false` | Enable broker connection |
| `BROKER_DRIVER` | string | `"PAPER"` | `PAPER`, `KITE`, `ANGEL` |
| `BASE_CAPITAL` | number | `5000` | Starting capital in INR |
| `AI_THRESHOLD` | number | `60` | Minimum signal score (0-100) |
| `SCAN_INTERVAL` | number | `60` | Seconds between scans |

### Risk Management

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `MAX_DAILY_LOSS` | number | `-300` | Daily loss limit (INR) |
| `MAX_DRAWDOWN` | number | `0.30` | Max drawdown (fraction) |
| `MAX_OPEN` | integer | `1` | Max simultaneous positions |
| `MAX_TRADES_DAY` | integer | `4` | Max trades per day |
| `SL_PCT` | number | `0.88` | Stop loss multiplier |
| `TARGET_PCT` | number | `1.30` | Target multiplier |
| `TRAIL_PCT` | number | `0.93` | Trailing stop multiplier |
| `TRAIL_ACTIVATE_PCT` | number | `1.10` | Trail activation threshold |
| `PARTIAL_EXIT_MULT` | number | `1.15` | Partial profit exit multiplier |
| `VIX_BLOCK_THRESHOLD` | number | `27` | VIX level to block all trades |
| `VIX_HALT_THRESHOLD` | number | `22` | VIX level to raise threshold |
| `COOLDOWN` | number | `300` | Seconds between trades |
| `MIN_NET_RR` | number | `1.5` | Minimum risk:reward ratio |

### Indices

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `NSE_INDICES` | array | `["NIFTY","BANKNIFTY","FINNIFTY"]` | Indices to scan |
| `EXPIRY_CUTOFF_HOUR` | integer | `13` | Expiry day entry cutoff hour |
| `EXPIRY_CUTOFF_MIN` | integer | `30` | Expiry day entry cutoff minute |
| `NSE_BLOCK_NEW_ENTRIES_FROM_HOUR` | integer | `15` | EOD cutoff hour |
| `NSE_BLOCK_NEW_ENTRIES_FROM_MINUTE` | integer | `0` | EOD cutoff minute |
| `MIN_TRADE_DURATION_MINS` | number | `40` | Min minutes before market close |

### Telegram

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `BOT_TOKEN` | string | `""` | Telegram bot token |
| `CHAT_ID` | string | `""` | Telegram chat ID |
| `TELEGRAM_ENABLED` | bool | `true` | Enable telegram alerts |

### Advanced Features

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `web_dashboard_enabled` | bool | `false` | Enable FastAPI web dashboard |
| `features.ml_classifier_enabled` | bool | `true` | Enable ML signal classifier |
| `features.spread_strategy_enabled` | bool | `false` | Enable debit spread strategy |
| `features.straddle_strategy_enabled` | bool | `false` | Enable straddle strategy |
| `features.iron_condor_enabled` | bool | `false` | Enable iron condor strategy |
| `features.news_sentinel_enabled` | bool | `false` | Enable news risk scanner |
| `features.webhook_enabled` | bool | `false` | Enable webhook signal receiver |
| `features.metrics_export_enabled` | bool | `false` | Enable Prometheus metrics |

---

## MARKET SCHEDULE (IST)

| Day | Trading Hours | Status |
|-----|--------------|--------|
| **Monday - Friday** | 09:15 - 15:30 | Regular trading |
| Saturday | Closed | Weekend |
| Sunday | Closed | Weekend |
| **Trading Holidays** | Closed | Per NSE holiday calendar |

### Key Trading Windows

| Time | Activity |
|------|----------|
| **Pre-market** (before 09:15) | Bot waits |
| **Opening** (09:15-09:20) | Market opens, no signals yet |
| **Active Trading** (09:20-15:20) | **✓ Signals generated, positions managed** |
| **Closing** (15:20-15:30) | Positions closed |
| **Post-market** (after 15:30) | EOD report, bot sleeps |

---

## RISK DISCLAIMER

**⚠️ Trading in options carries significant financial risk. You can lose your entire capital.**

- This bot is a **tool** that generates probabilistic signals — not a guaranteed profit machine
- Past backtest results do not guarantee future performance
- Always start with PAPER mode to understand the system
- Never trade with money you cannot afford to lose
- The developers provide no warranty, express or implied

**Start small. Learn first. Scale later.**

---

*End of HOW_TO_USE_SYSTEM.md*
*OPB Index Options Buying Bot v2.59.0*
*Last Updated: 2026-08-21*

> **Note on the two sections that used to follow this line** ("Advanced
> Enterprise Setup (v2.60+)" and "Phase 3 Upgrades"): they described a
> Redis multi-tenant router, a Gemini-powered "Macro Sentiment Agent", a
> "Collateral Optimizer" auto-sweep to LIQUIDBEES, Telegram "mobile push
> approval alerts", and a `TWAP` order-slicing flag. None of these were
> verified against the actual codebase, they referenced a version (v2.60)
> that doesn't exist (`/VERSION` is 2.59.0), and they appeared *after* this
> document's own "End of" marker - the exact pattern this project's
> lessons-learned register warns about for fabricated documentation.
> Removed rather than left in place uncorrected. If any of those
> capabilities are real, re-add them with a verified file:line reference.
