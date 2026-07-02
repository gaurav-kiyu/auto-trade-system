# STEP-BY-STEP USAGE GUIDE
## OPB Index Options Buying Bot v2.53.0
## From Zero to Trading — Complete Walkthrough

---

## HOW TO USE THIS GUIDE

This guide is written in **sequential steps**. Follow them in order. Each section builds on the previous one. If you already know a step, skip ahead — but don't skip steps you're unsure about.

**Who this is for:** Beginners who have never run the bot before, through experienced users who want to understand every feature.

**Time to complete:** ~30 minutes for basic setup, ~2 hours for full configuration and testing.

---

# PART 1: SETUP

---

## Step 1: Check Your Computer

### What You Need
| Requirement | Check | If Missing |
|------------|-------|------------|
| **Python** 3.10–3.19 | Open terminal: `python --version` | Download from [python.org](https://www.python.org/downloads/) |
| **Windows 10+** (or Linux/Mac) | You're reading this on it | N/A |
| **Internet connection** | Can you browse the web? | Required for market data |
| **Disk space** | 500 MB free | Free up space |
| **RAM** | 4 GB minimum | Close other applications |

### Step 1.1: Open a Terminal
- **Windows:** Press `Windows + R`, type `cmd`, press Enter
- **Mac:** Press `Cmd + Space`, type `terminal`, press Enter
- **Linux:** Press `Ctrl + Alt + T`

### Step 1.2: Verify Python
```bash
python --version
```
**Expected output:** `Python 3.10.x`, `3.11.x`, `3.12.x`, or `3.13.x`

**If you see "not recognized":**
- Try `python3 --version` instead
- Or reinstall Python and CHECK "Add Python to PATH"

---

## Step 2: Get the Bot Files

### Option A: Download as ZIP
1. Go to the repository page
2. Click **Code → Download ZIP**
3. Extract the ZIP to a folder (e.g., `C:\OPB_Bot`)

### Option B: Clone with Git
```bash
git clone <repository-url>
cd OPB_FINAL_MT
```

### Step 2.1: Navigate to the Bot Folder
```bash
cd <path-to-folder>
```
Example:
```bash
cd C:\OPB_Bot
```

---

## Step 3: Install Dependencies

### Step 3.1: Install Required Packages
```bash
pip install -r requirements.txt
```

**What this installs:**

| Package | Purpose | 
|---------|---------|
| `requests` | HTTP calls to NSE, Telegram |
| `yfinance` | Live market data from Yahoo Finance |
| `pandas` | Data manipulation |
| `numpy` | Math operations |
| `jsonschema` | Configuration validation |
| `flask` | Web dashboard (optional) |
| `lightgbm` | ML signal classifier (optional) |
| `scikit-learn` | ML support (optional) |
| `reportlab` | PDF reports (optional) |

### Step 3.2: Verify Installation
```bash
python -c "import yfinance, pandas, numpy; print('All basic dependencies OK')"
```
**Expected output:** `All basic dependencies OK`

### Step 3.3: Run Tests (Optional but Recommended)
```bash
python -m pytest tests/ -q --tb=short
```
**Expected:** All tests pass (~2670 tests, ~4.5 minutes)

---

## Step 4: Configure the Bot

### Step 4.1: Understand the Config System

The bot uses a **4-layer configuration merge**:

```
Layer 1: index_config.defaults.json  (single source of truth, ~860 keys)
Layer 2: config.json                 (your personal overrides)
Layer 3: config.local.json           (machine-local secrets, gitignored)
Layer 4: OPBUYING_* env vars         (secrets — highest priority)
```

You only need to create **config.json** for basic usage.

### Step 4.2: Create Your Config File

Create a file called `config.json` in the project root folder with this content:

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
  "TRAIL_PCT": 0.93
}
```

### Step 4.3: Understand Each Setting

| Setting | Your Value | What It Does |
|---------|-----------|--------------|
| `EXECUTION_MODE` | `"PAPER"` | PAPER = simulated trading (safe). MANUAL = signals only. AUTO = live orders |
| `BROKER_API_ENABLED` | `false` | Keep `false` for paper/manual. Set `true` only when ready for live |
| `BASE_CAPITAL` | `5000` | Your virtual trading capital in INR |
| `MAX_DAILY_LOSS` | `-300` | Stop trading for the day if you lose more than Rs.300 |
| `MAX_DRAWDOWN` | `0.3` | Emergency stop if total losses exceed 30% of capital |
| `MAX_OPEN` | `1` | Maximum positions held at the same time |
| `MAX_TRADES_DAY` | `2` | Maximum trades to open in one day |
| `AI_THRESHOLD` | `60` | Minimum signal strength (0-100). Higher = fewer but stronger signals |
| `SCAN_INTERVAL` | `60` | Seconds between market scans |
| `SL_PCT` | `0.88` | Stop loss at 88% of entry price (12% loss on premium) |
| `TARGET_PCT` | `1.30` | Take profit at 130% of entry price (30% gain on premium) |
| `TRAIL_PCT` | `0.93` | Trailing stop at 93% of peak price |

### Step 4.4: Create config.local.json (Optional, for Secrets)

If you use Telegram, create `config.local.json`:

```json
{
  "BOT_TOKEN": "7012345678:AAH-your-bot-token-here",
  "CHAT_ID": "1234567890"
}
```

**⚠️ IMPORTANT:** `config.local.json` is already in `.gitignore` — it will never be committed.

---

## Step 5: Set Up Telegram (Optional)

### Why Telegram?
Telegram sends you alerts when:
- A strong trading signal is generated
- A position hits stop loss or target
- The market opens or closes
- An error or warning occurs

### Step 5.1: Create a Telegram Bot
1. Open Telegram on your phone or desktop
2. Search for `@BotFather`
3. Send: `/newbot`
4. Choose a name (e.g., "My Trading Bot")
5. Choose a username (e.g., `my_trading_bot_123`)
6. BotFather sends you a **token** — save it!

### Step 5.2: Get Your Chat ID
1. Start a chat with your new bot
2. Send any message (e.g., "Hello")
3. Visit this URL in your browser:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
4. Find `"chat":{"id":1234567890}` — that number is your Chat ID

### Step 5.3: Add to Config
Put both values in `config.local.json` (Step 4.4).

---

# PART 2: RUNNING THE BOT

---

## Step 6: Start the Bot — Paper Mode

### Step 6.1: Run Paper Mode
```bash
python -m index_app.index_trader --paper
```

**You should see:**
```
[INFO] Starting OPB Index Options Bot v2.53.0
[INFO] Execution mode: PAPER
[INFO] Config loaded successfully
[INFO] Market status: CLOSED (scanning will begin at 09:15 IST)
```

### Step 6.2: What Happens Next
- Before 9:15 AM IST: Bot waits silently
- 9:15 - 9:20 AM: Market opens, bot initializes
- 9:20 AM onwards: Bot scans indices every 60 seconds
- Signals appear in the console dashboard

### Step 6.3: Read the Dashboard

When the market is open, you'll see:

```
══════════════════════════════════════════════════════════════════
  INDEX OPTIONS BUYING BOT v2.53.0  [PAPER]  01-Apr-2026 11:30
  Capital: ₹5,000  Day P&L: ▲ +₹150  Trades: 1/2  Positions: 1/1
══════════════════════════════════════════════════════════════════

  ┌─ NIFTY ──────────────────────────────────────────────────┐
  │ Score: 78/60 | CALL | STRONG | ⭐⭐⭐                    │
  │ CMP: 23,500 | Premium Est: ₹180 | Risk: ₹432            │
  │ WHY: Trend UP on 5m+15m, Price > VWAP, Vol 1.8x         │
  └──────────────────────────────────────────────────────────┘
```

**Understanding the display:**

| Element | Meaning |
|---------|---------|
| `[PAPER]` | Mode — PAPER, MANUAL, or LIVE |
| `Capital: ₹5,000` | Your virtual account balance |
| `Day P&L: ▲ +₹150` | Today's profit/loss (▲ = profit, ▼ = loss) |
| `Trades: 1/2` | 1 trade opened out of 2 allowed today |
| `Positions: 1/1` | 1 position open out of 1 maximum |
| `Score: 78/60` | Signal score is 78, minimum threshold is 60 |
| `CALL` | Direction — CALL (bullish) or PUT (bearish) |
| `STRONG` | Signal strength — STRONG, MODERATE, or WEAK |
| `⭐⭐⭐` | Visual strength indicator (more stars = stronger) |
| `Premium Est: ₹180` | Estimated option premium cost |
| `Risk: ₹432` | Estimated risk in rupees |

### Step 6.4: Stop the Bot
Press `Ctrl + C` in the terminal.

---

## Step 7: Run in MANUAL Mode

### What's Different
- **PAPER mode**: Bot simulates trades, tracks virtual P&L
- **MANUAL mode**: Bot shows signals, YOU place orders in your broker

### Step 7.1: Start MANUAL Mode
```bash
python -m index_app.index_trader
```

### Step 7.2: When You See a Signal
```
NIFTY — Strong CALL  Score: 82/60
```

**Do this:**
1. Open your broker app (Zerodha, Angel, Groww, etc.)
2. Go to NIFTY options chain
3. Find the nearest weekly expiry
4. Select the ATM (At-The-Money) CALL option
5. Buy 1 lot at market price
6. Set Stop Loss at entry × 0.88
7. Set Target at entry × 1.30

---

## Step 8: Run with the GUI Launcher

### Step 8.1: Launch the GUI
Double-click `OPBuying_INDEX_Launcher.exe`

### Step 8.2: Select Mode
- **PAPER**: Simulated trading
- **MANUAL**: Signals only (you place orders)

### Step 8.3: Click START
The GUI shows:
- Real-time dashboard
- Current signals
- Open positions
- P&L summary

---

## Step 9: Run with Docker

### Step 9.1: Install Docker
Download from [docker.com](https://www.docker.com/products/docker-desktop/)

### Step 9.2: Start the Bot
```bash
docker compose up -d
```

### Step 9.3: View Logs
```bash
docker compose logs -f opb
```

### Step 9.4: Stop the Bot
```bash
docker compose down
```

---

# PART 3: UNDERSTANDING THE TRADING

---

## Step 10: How Signals Work

### Step 10.1: The Scoring System (0-100)

The bot analyzes 3 timeframes of market data:

| Timeframe | What It Detects |
|-----------|-----------------|
| **1-minute** | Current price, VWAP, immediate volatility |
| **5-minute** | Primary trend, RSI, MACD, short-term momentum |
| **15-minute** | Confirmation trend, longer-term context |

### Step 10.2: What Each Indicator Checks

| Indicator | What It Measures | Points |
|-----------|-----------------|--------|
| **Trend Agreement** | Do 5m and 15m trends agree? | ±20 |
| **VWAP Position** | Is price above/below average? | ±15 |
| **Price Momentum** | Is price moving in trend direction? | ±15 |
| **Volume** | Is volume above average (>1.2x)? | +10 |
| **ATR** | Is there enough volatility? | +5 |
| **Smart Money (OI)** | Are institutions aligned? | ±10 |
| **PCR** | Does options sentiment support the move? | ±5 |

### Step 10.3: Signal Strength

| Score | Strength | What It Means |
|-------|----------|---------------|
| 85-100 | ⭐⭐⭐⭐ STRONG | All indicators aligned — high confidence |
| 70-84 | ⭐⭐⭐ MODERATE | Good setup, some caution warranted |
| 60-69 | ⭐⭐ WEAK | Borderline — consider skipping |
| Below 60 | No signal | Stay out |

### Step 10.4: Direction Decision
```
If 5m EMA(5) > EMA(20) AND 15m EMA(5) > EMA(20) → CALL (bullish)
If 5m EMA(5) < EMA(20) AND 15m EMA(5) < EMA(20) → PUT (bearish)
If they disagree → NO SIGNAL
```

---

## Step 11: Risk Management Rules

### Step 11.1: What the Bot Enforces Automatically

| Rule | Value | What Happens |
|------|-------|-------------|
| **Max daily loss** | -Rs.300 (-6%) | New trades blocked for the day |
| **Max drawdown** | 30% of capital | Hard halt — emergency stop |
| **Max positions** | 1 at a time | No new entries until position closes |
| **Max trades/day** | 2 per day | No new entries after limit |
| **VIX > 27** | Blocks all trades | Market too volatile |
| **EOD cutoff** | 3:20 PM IST | No new entries |
| **Loss streak** | 3 losses in a row | 2-hour cooldown |

### Step 11.2: Exit Rules (Checked Every Scan)

The bot checks exits in this priority:
```
1. 3:20 PM → EXIT ALL (market closing)
2. Position age > 120 min → EXIT (stale trade)
3. Price ≤ Stop Loss → EXIT (max loss hit)
4. Price ≤ Trailing SL → EXIT (protect gains)
5. Price ≥ Target → EXIT (profit taken)
```

### Step 11.3: Position Sizing Formula
```
Risk per trade = your config (default Rs.200 for index)
Max lots = min(
    Risk / (Premium × (1 - SL_PCT) × Lot_Size),
    Capital × 0.85 / (Premium × Lot_Size)
)
```

---

## Step 12: Monitoring & Logs

### Step 12.1: Console Dashboard
The bot prints a live dashboard every scan cycle (default: every 60 seconds).

### Step 12.2: Trade History
```bash
python -m core.report_generator --days 30 --mode PAPER
```
Generates a PDF report with:
- Win rate, profit factor, Sharpe ratio
- Equity curve
- Breakdowns by index, score, exit reason

### Step 12.3: Health Check
```bash
python -m core.health_checker
```
Checks: database integrity, ML model, config validity, disk space.

### Step 12.4: Log Files
Located in `logs/` folder:
- Rotated at 50 MB
- Compressed with gzip
- Configurable retention

---

# PART 4: ADVANCED OPERATIONS

---

## Step 13: Running Backtests

### Step 13.1: Quick Backtest
```bash
python run_backtest.py --yf-quarter --yf-symbol ^NSEI --yf-days 30
```

### Step 13.2: Multi-Index Backtest Suite
```bash
python scripts/run_backtest_suite.py
```

### Step 13.3: Walk-Forward Validation
```bash
python -m core.walkforward_engine --csv tests/fixtures/replay_minute_bars.csv
```

### Step 13.4: Parameter Optimization
```bash
python -m core.param_optimizer --param SL_PCT --values 0.85,0.88,0.90,0.92
```

---

## Step 14: Live Trading Preparation

### Step 14.1: Run the Readiness Checker
```bash
python -m core.live_readiness_checker
```
**Must pass ALL 5 checks before going live:**
1. ✅ Paper trading scorecard > 7/10
2. ✅ Minimum 30 paper trades completed
3. ✅ Profit factor > 1.5
4. ✅ Win rate > 45%
5. ✅ Max drawdown < 15%

### Step 14.2: Configure Broker Connection
In `config.json`:
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

### Step 14.3: Test with PAPER Mode First
Keep `EXECUTION_MODE: "PAPER"` while `BROKER_API_ENABLED: true` — this tests the broker connection without real orders.

### Step 14.4: Switch to AUTO Mode
Only after all checks pass:
```json
{
  "EXECUTION_MODE": "AUTO",
  "BROKER_API_ENABLED": true
}
```

---

## Step 15: Recovery & Failover

### Step 15.1: If the Bot Crashes
```bash
# Just restart it
python -m index_app.index_trader --paper
```
The bot:
- Reads saved state from `trader_state.json`
- Reconciles open positions
- Continues from where it stopped

### Step 15.2: If You See HARD_HALT
A HARD_HALT means the bot detected a position mismatch.

**To recover:**
1. Check your broker — what positions are open?
2. Check the bot — what does it think is open?
3. If they differ, CLOSE the broker position manually
4. Restart the bot — it reconciles at startup

### Step 15.3: Emergency Stop
Create a file called `STOP_TRADING` in the project root folder.
The bot detects this file and halts immediately.

### Step 15.4: Kill File
The bot watches for `STOP_TRADING` in the root folder on every scan cycle.
If present, the bot:
1. Closes all open positions
2. Saves state
3. Exits

---

# PART 5: TROUBLESHOOTING

---

## Step 16: Common Problems and Solutions

| Problem | Likely Cause | Solution |
|---------|-------------|----------|
| **"No data"** message | Market closed or yfinance rate limit | Wait for market hours (9:15-3:30 IST) |
| **Python import errors** | Missing packages | `pip install -r requirements.txt` |
| **Telegram not working** | Wrong token/chat ID | Check BOT_TOKEN and CHAT_ID in config |
| **No signals all day** | Low volatility day | Normal — no trade is better than bad trade |
| **Score always below threshold** | Market is flat/choppy | Normal — bot avoids bad setups |
| **Dashboard shows "--"** | Market not open yet | Wait for 9:20 AM IST |
| **"yf.RateLimitError"** | Too many Yahoo requests | Wait 2-5 minutes, auto-recovers |
| **Config errors at startup** | Invalid config.json | Check for missing commas, quotes |
| **HARD_HALT message** | Position mismatch | Follow recovery steps (Step 15.2) |

---

## Step 17: Getting Help

### Documentation Files
| File | What It Covers |
|------|---------------|
| `SETUP_AND_TRADING_GUIDE.md` | Complete trading guide |
| `QUICK_START_GUIDE.md` | Quick reference |
| `SYSTEM_SETUP_GUIDE.md` | System setup |
| `CONFIG_EXPLANATIONS.md` | Every config key explained |
| `docs/deployment/DEPLOYMENT_GUIDE.md` | Production deployment |
| `docs/runbooks/` | Incident response procedures |

### CLI Tools
```bash
# Test everything works
python -m index_app.index_trader --selftest

# Print current config
python -m index_app.index_trader --print-config

# Health check
python -m core.health_checker

# Live readiness check
python -m core.live_readiness_checker
```

---

## Step 18: Upgrading

### Step 18.1: Backup Your Config
```bash
copy config.json config.json.backup
```

### Step 18.2: Update Code
```bash
git pull
```

### Step 18.3: Update Dependencies
```bash
pip install -r requirements.txt --upgrade
```

### Step 18.4: Run Tests
```bash
python -m pytest tests/ -q
```

### Step 18.5: Start in PAPER Mode
Always run in PAPER mode first after an upgrade to verify everything works.

---

# PART 6: APPENDIX

---

## Appendix A: Quick Command Reference

| Task | Command |
|------|---------|
| **Start paper trading** | `python -m index_app.index_trader --paper` |
| **Start manual mode** | `python -m index_app.index_trader` |
| **Run self-test** | `python -m index_app.index_trader --selftest` |
| **Generate PDF report** | `python -m core.report_generator --days 30` |
| **Health check** | `python -m core.health_checker` |
| **Live readiness** | `python -m core.live_readiness_checker` |
| **Run backtest** | `python run_backtest.py --yf-quarter` |
| **Run tests** | `python -m pytest tests/ -q` |
| **Print config** | `python -m index_app.index_trader --print-config` |
| **Trade replay** | `python -m core.trade_replayer --id 42` |
| **Sensitivity analysis** | `python -m core.sensitivity_analyzer --param SL_PCT` |

## Appendix B: File Reference

| File | Purpose |
|------|---------|
| `index_app/index_trader.py` | Main trading bot |
| `launcher.py` | GUI launcher |
| `core/services/execution_service.py` | Order execution |
| `core/services/risk_service.py` | Risk management (contains CapitalManager) |
| `core/services/paper_trader.py` | Paper fill simulator |
| `index_config.defaults.json` | All configuration defaults (~860 keys) |
| `config.json` | Your personal overrides |
| `config.local.json` | Local secrets (gitignored) |
| `trader_state.json` | Saved trading state |
| `trades.db` | Trade log database |
| `docs/` | All documentation |

## Appendix C: Market Schedule (IST)

| Time | What Happens |
|------|-------------|
| Before 09:15 | Bot waits |
| 09:15 - 09:20 | Market opens (too noisy for signals) |
| **09:20 - 15:20** | **Active trading window** |
| 15:20 - 15:30 | Positions closed, no new entries |
| After 15:30 | Bot sends EOD report, waits for next day |

## Appendix D: Lot Sizes

| Index | Lot Size | Strike Gap |
|-------|----------|------------|
| NIFTY | 25 | ₹50 |
| BANKNIFTY | 15 | ₹100 |
| FINNIFTY | 40 | ₹50 |

---

*End of Step-by-Step Guide*
*Last updated: June 2026 | OPB Index Options Bot v2.53.0*
