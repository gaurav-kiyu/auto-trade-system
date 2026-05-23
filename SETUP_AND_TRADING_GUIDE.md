# COMPLETE SETUP & TRADING GUIDE
## NSE Index Options Buying Bot v2.53.0

**Quick start:** see Section 4 (Running the Scripts) and Section 13 (Manual Trading Workflow).

---

## TABLE OF CONTENTS

1. [Prerequisites & Installation](#1-prerequisites--installation)
2. [File Structure — What Each File Does](#2-file-structure--what-each-file-does)
3. [Configuration — Step by Step](#3-configuration--step-by-step)
4. [Running the Scripts](#4-running-the-scripts)
5. [Understanding the Dashboard Output](#5-understanding-the-dashboard-output)
6. [Signal System — How Signals Are Generated](#6-signal-system--how-signals-are-generated)
7. [Trading Actions — When to Buy, When to Sell](#7-trading-actions--when-to-buy-when-to-sell)
8. [Stop Loss, Targets & Exit Rules](#8-stop-loss-targets--exit-rules)
9. [Position Management — Trailing, Partial Exit, EOD](#9-position-management--trailing-partial-exit-eod)
10. [Web Dashboard — Setup & Usage](#10-web-dashboard--setup--usage)
11. [Telegram Alerts — Setup & Reading](#11-telegram-alerts--setup--reading)
12. [Risk Management Rules](#12-risk-management-rules)
13. [Manual Trading Workflow — Step by Step](#13-manual-trading-workflow--step-by-step)
14. [Enhancement Phases — Advanced Features](#14-enhancement-phases--advanced-features)
15. [Troubleshooting & FAQ](#15-troubleshooting--faq)

---

## 1. PREREQUISITES & INSTALLATION

### Step 1: Install Python

- Python 3.10 or higher required
- Download from https://www.python.org/downloads/
- During install, CHECK "Add Python to PATH"
- Verify: open terminal, type `python --version`

### Step 2: Install Dependencies

Open terminal/command prompt in the script folder and run:

```
pip install -r requirements.txt
```

This installs:

| Package | Purpose | Required By |
|---------|---------|-------------|
| `requests` | HTTP calls to NSE, Telegram | All scripts |
| `yfinance` | Live index/VIX price data from Yahoo Finance | All scripts |
| `pandas` | OHLCV candle manipulation | All scripts |
| `numpy` | Indicator math | All scripts |
| `jsonschema` | Config validation | All scripts |
| `flask` | Web dashboard server | Dashboard only |
| `flask-socketio` | Real-time WebSocket updates | Dashboard only |
| `lightgbm` | ML signal classifier (Phase 5) — activates after 50 trades | Index bot |
| `scikit-learn` | Required by LightGBM's sklearn API | Index bot |
| `reportlab` | PDF trade report generator (Phase 6) | Index bot |

**Optional** (for live broker execution — NOT needed for paper/manual trading):
```
pip install kiteconnect pyotp
```

### Step 3: Verify Installation

```
python -c "import yfinance, pandas, numpy, flask, lightgbm, reportlab; print('All dependencies OK')"
```

Run the test suite to verify everything works end-to-end:

```
python -m pytest tests/ -q
```

Expected output: `554 passed` (takes ~2 minutes).

---

## 2. FILE STRUCTURE — WHAT EACH FILE DOES

### Core Trading Bots (Run Independently)

| File | What It Does |
|------|-------------|
| `STOCK_OPTION_BUYING_APP_1.0.py` | Scans **53 stocks** for options trading signals (CE/PE). Shows live prices, generates buy/sell signals with score, manages paper positions with SL/target/trailing. |
| `INDEX_OPTION_BUYING_APP_1.0.py` | Legacy single-file entry point (do not modify — use `index_app/index_trader.py` for development). |
| `index_app/index_trader.py` | **Main Index Bot brain v2.42** — 26-section, 8,000-line engine. Scans NIFTY/BANKNIFTY/FINNIFTY, runs the full signal pipeline, manages positions, enforces all risk rules. |
| `launcher.py` | GUI launcher wrapper (Windows) |
| `dashboard_server.py` | Flask web server — real-time browser dashboard for all 56 instruments. |

### Core Modules (`core/`)

| Module | What It Does |
|--------|-------------|
| `adaptive_signal.py` | Signal scoring pipeline — stacks IV rank, session, ML, and tier classification |
| `pure_index_signal.py` | Base signal generation (RSI, MACD, ADX, PCR, OI, breakout, VWAP, ORB) |
| `iv_rank.py` | IV Rank / IV Percentile from `^INDIAVIX` — adjusts score for premium cost |
| `session_classifier.py` | Time-of-day session bands (OPENING / TRENDING / CHOPPY / PRE_CLOSE) with score adjustments |
| `strike_selector.py` | ATM / OTM / DELTA strike selection with vega cap and DTE guard |
| `ml_classifier.py` | LightGBM win-probability classifier — trained on journal history, boosts/penalises score |
| `event_calendar.py` | Event day filter — blocks entries on Budget / RBI / FOMC / custom dates |
| `correlation_guard.py` | Blocks same-direction entry when a correlated index (NIFTY↔BANKNIFTY etc.) is already open |
| `report_generator.py` | ReportLab PDF report — equity curve, metrics table, insights |
| `config_bootstrap.py` | Config merge engine — defaults ← JSON ← local ← `OPBUYING_*` env vars |
| `performance_metrics.py` | Trade analytics — win rate, Sharpe, drawdown, profit factor, insights |
| `trade_journal.py` | Execution quality journal — slippage, fill delay, expected vs actual PnL |
| `risk_engine.py` | Position sizing — VIX scaling, drawdown scaling, fixed/pct risk modes |
| `adapters/broker_adapters.py` | Broker abstraction — `PaperBrokerAdapter` (slippage + liquidity) and live broker interface |

### Configuration Files

| File | What It Does |
|------|-------------|
| `config.json` | Your overrides for the index bot (capital, risk, Telegram token, etc.) |
| `config.local.json` | Machine-local secrets — gitignored, merged last (highest priority after env vars) |
| `index_config.defaults.json` | **Single source of truth** for all ~250 default config values — never edit directly |
| `config.template.json` | Annotated template showing every key with explanation |
| `schemas/index_config.schema.json` | Auto-generated JSON Schema — validated on every config load |
| `CLAUDE.md` | Claude Code context file — loaded automatically in every AI-assisted session |

### Data Files (Auto-Created on First Run)

| File | What It Does |
|------|-------------|
| `trader_state.json` | Saves capital, daily PnL, trade count, open positions — survives restarts |
| `trades.db` | SQLite trade log — primary source for analytics and reporting |
| `trade_journal.db` | Execution quality journal — slippage, fill delay, expected vs actual PnL |
| `models/signal_classifier.pkl` | Trained LightGBM model — created automatically after 50 trades |
| `reports/*.pdf` | EOD PDF performance reports (when `report_eod_auto_generate: true`) |
| `logs/*.log` | Timestamped session logs |

---

## 3. CONFIGURATION — STEP BY STEP

### 3A. Configure the STOCK Bot

Create file `stock_config.json` in the same folder:

```json
{
    "BOT_TOKEN": "YOUR_TELEGRAM_BOT_TOKEN",
    "CHAT_ID": "YOUR_TELEGRAM_CHAT_ID",
    "BASE_CAPITAL": 10000,
    "RISK_FIXED_AMOUNT": 400,
    "MAX_OPEN": 2,
    "MAX_TRADES_DAY": 6,
    "DAILY_TARGET": 800,
    "SL_PCT": 0.85,
    "TARGET_PCT": 1.35,
    "AI_THRESHOLD": 60,
    "SCAN_INTERVAL": 90
}
```

**KEY VALUES EXPLAINED:**

| Setting | Default | What It Means |
|---------|---------|---------------|
| `BASE_CAPITAL` | 10,000 | Your total trading capital in INR |
| `RISK_FIXED_AMOUNT` | 400 | Maximum risk per trade in INR |
| `MAX_OPEN` | 2 | Maximum simultaneous open positions |
| `MAX_TRADES_DAY` | 6 | Maximum trades per day |
| `DAILY_TARGET` | 800 | Stop trading when daily profit hits this amount |
| `SL_PCT` | 0.85 | Stop loss at 85% of entry (i.e., 15% loss on option premium) |
| `TARGET_PCT` | 1.35 | Target at 135% of entry (i.e., 35% profit on option premium) |
| `AI_THRESHOLD` | 60 | Minimum score needed to generate a signal (out of 100) |
| `SCAN_INTERVAL` | 90 | Seconds between each scan cycle |
| `MAX_DAILY_LOSS` | -4,000 | Hard stop — no new trades after this daily loss |
| `TRAIL_ACTIVATE` | 1.12 | Start trailing after 12% gain on premium |
| `TRAIL_PCT` | 0.92 | Trail stop at 92% of peak premium |
| `PARTIAL_EXIT_MULT` | 1.18 | Book partial profit at 18% gain |
| `MIN_TRADE_DURATION_MINS` | 40 | Don't enter if less than 40 mins to market close |
| `VIX_BLOCK_THRESHOLD` | 27 | Block ALL trades when India VIX > 27 |
| `VIX_HALT_THRESHOLD` | 22 | Raise score threshold when VIX > 22 |
| `COOLDOWN` | 300 | Wait 5 minutes between consecutive trades |
| `MIN_NET_RR` | 1.5 | Only take trades with risk:reward >= 1:1.5 |

### 3B. Configure the INDEX Bot

Create file `config.json` in the same folder:

```json
{
    "BOT_TOKEN": "YOUR_TELEGRAM_BOT_TOKEN",
    "CHAT_ID": "YOUR_TELEGRAM_CHAT_ID",
    "BASE_CAPITAL": 5000,
    "RISK_FIXED_AMOUNT": 200,
    "MAX_OPEN": 1,
    "MAX_TRADES_DAY": 4,
    "DAILY_TARGET": 400,
    "SL_PCT": 0.88,
    "TARGET_PCT": 1.30,
    "AI_THRESHOLD": 60,
    "SCAN_INTERVAL": 60
}
```

**INDEX BOT DIFFERENCES FROM STOCK BOT:**

| Setting | Stock Bot | Index Bot | Why |
|---------|-----------|-----------|-----|
| `BASE_CAPITAL` | 10,000 | 5,000 | Index options cost less per lot |
| `RISK_FIXED_AMOUNT` | 400 | 200 | Lower risk per trade |
| `MAX_OPEN` | 2 | 1 | Indices are correlated, avoid doubling risk |
| `MAX_TRADES_DAY` | 6 | 4 | Fewer quality setups on 3 indices |
| `DAILY_TARGET` | 800 | 400 | Proportional to capital |
| `SL_PCT` | 0.85 | 0.88 | Tighter SL (12% loss vs 15%) |
| `TARGET_PCT` | 1.35 | 1.30 | Slightly lower target (30% vs 35%) |
| `TRAIL_ACTIVATE` | 1.12 | 1.10 | Trail starts earlier |
| `PARTIAL_EXIT_MULT` | 1.18 | 1.15 | Partial profit earlier |

### 3C. How to Get Telegram Bot Token & Chat ID

1. Open Telegram, search for `@BotFather`
2. Send `/newbot`, follow prompts, get your **Bot Token** (looks like `7012345678:AAH...`)
3. Start a chat with your new bot
4. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
5. Send any message to your bot, refresh the URL
6. Find `"chat":{"id":1234567890}` — that's your **Chat ID**

---

## 4. RUNNING THE SCRIPTS

### 4A. Stock Bot

```
# Paper mode (recommended first — no real money)
python STOCK_OPTION_BUYING_APP_1.0.py --paper

# Paper mode without GUI window (console only)
python STOCK_OPTION_BUYING_APP_1.0.py --paper --nogui

# Self-test (verify everything works)
python STOCK_OPTION_BUYING_APP_1.0.py --selftest

# Generate config template
python STOCK_OPTION_BUYING_APP_1.0.py --print-config

# View trade history report
python STOCK_OPTION_BUYING_APP_1.0.py --report
```

### 4B. Index Bot (v2.42)

```
# Paper mode (recommended first — no real orders placed)
python index_app/index_trader.py --paper

# Paper mode with custom config file
OPBUYING_INDEX_CONFIG=config.dev.json python index_app/index_trader.py --paper

# Paper mode — console only, no GUI window
python index_app/index_trader.py --paper --nogui

# Live manual mode (signals only — you place orders yourself)
python index_app/index_trader.py

# Generate a PDF performance report (standalone)
python -m core.report_generator --days 30 --mode PAPER

# Regenerate config schemas after editing index_config.defaults.json
python scripts/generate_config_schemas.py
```

> **Note:** `INDEX_OPTION_BUYING_APP_1.0.py` is the legacy single-file entry point.
> Use `index_app/index_trader.py` for all v2.42 features.

### 4C. Web Dashboard

```
# Start dashboard (default port 5100)
python dashboard_server.py

# Custom port
python dashboard_server.py --port 8080

# Then open browser: http://localhost:5100
```

### 4D. Run Everything Together (Recommended)

Open 3 separate terminal windows:

```
# Terminal 1 — Stock Bot
python STOCK_OPTION_BUYING_APP_1.0.py --paper

# Terminal 2 — Index Bot
python INDEX_OPTION_BUYING_APP_1.0.py --paper

# Terminal 3 — Web Dashboard
python dashboard_server.py
```

### Market Hours (IST)

| Time | Status | What Happens |
|------|--------|-------------|
| Before 09:15 | PRE | Script waits, no scanning |
| 09:15 - 09:20 | OPEN | Market open but no signals yet (settling) |
| **09:20 - 15:20** | **TRADING WINDOW** | **Active scanning, signals generated** |
| 15:20 - 15:30 | CLOSING | EOD exit of positions, no new entries |
| After 15:30 | CLOSED | Daily summary sent, script waits for next day |
| Saturday/Sunday | WEEKEND | Script sleeps |

---

## 5. UNDERSTANDING THE DASHBOARD OUTPUT

### Console Dashboard (Stock Bot)

When running, the stock bot prints a refreshing dashboard every scan cycle:

```
══════════════════════════════════════════════════════════════════════════════════════
  STOCK OPTION TRADER v1.4   01-Apr-2026 11:30:15 AM IST   [OPEN] [PAPER]
  Capital: ₹10,000   Day P&L: ▲ +₹350   Trades: 2/6   Positions: 1/2
══════════════════════════════════════════════════════════════════════════════════════
```

**Header line tells you:**
- Current capital, daily P&L (▲ = profit, ▼ = loss)
- Trade count vs max allowed
- Open position count vs max allowed
- Market status and mode (PAPER/LIVE)

### OPEN POSITIONS Section

```
  Stock        Side   Entry      CMP        P&L       %      Target     SL    Age
  RELIANCE     CE     ₹  45.0   ₹  52.3   ▲  +₹1825  +16.2%  ₹  60.8  ₹ 38.3   22m
     Exit: Target ₹60.8 | SL ₹38.3 | Trail ₹48.1 | EOD 3:20pm
```

**How to read:**
- **Side CE** = Call option (bullish). **PE** = Put option (bearish)
- **Entry** = Price you entered at
- **CMP** = Current Market Price of the option
- **P&L** = Unrealized profit/loss (entry to CMP × quantity)
- **Target** = Price where auto-exit happens for profit
- **SL** = Price where auto-exit happens for loss
- **Trail** = Trailing stop (moves up as price increases)
- **Age** = How many minutes the position has been open

### ACTION ALERTS Section

```
  ⭐⭐⭐⭐ RELIANCE — Strong Buy CE  Score: 88/60  |  CE (Buy Call)
     CMP: ₹1,375  Lot: 250  Est.Premium: ~₹41.3  Risk: ~₹295
     WHY: Trend UP on 5m+15m, Price > VWAP, Volume high, RSI 55 (healthy)
```

**This is the most important section for manual trading. It tells you:**
- **Stock name** and **direction** (CE = Call = Bullish, PE = Put = Bearish)
- **Score/Threshold** — How strong the signal is vs minimum required
- **Stars** — More stars = stronger signal (5 = strongest)
- **CMP** — Current stock price
- **Lot** — F&O lot size for this stock
- **Est. Premium** — Estimated ATM option premium (~3% of stock price)
- **Risk** — Estimated risk in INR
- **WHY** — Plain English explanation of what's driving the signal

### WATCHLIST Section

Stocks approaching a signal but not yet strong enough:

```
  Stock        Dir  Score     CMP       RSI  Reason
  ICICIBANK     CE  55/60    ₹1,217    42   Trend UP, near VWAP
```

These are "almost ready" — keep watching them.

### LIVE MARKET Section

All 53 stocks with current prices, grouped by sector:

```
  Stock        CMP         Chg        %     Day H     Day L  Signal  Score  Sector
  --- BANK --------------------------------------------------
  HDFCBANK     ₹  746.3   ▼  -1.7   -0.2%  ₹  750.1  ₹  742.0     CE     55  BANK
  ICICIBANK    ₹1,216.8   ▼ -12.0   -1.0%  ₹1,230.0  ₹1,210.5     PE     72  BANK
```

---

## 6. SIGNAL SYSTEM — HOW SIGNALS ARE GENERATED

### What the Bot Analyzes

For each stock/index, the bot fetches 3 timeframes of live candle data:

| Timeframe | Period | Used For |
|-----------|--------|----------|
| **1-minute** | Today | Current price, VWAP, intraday S/R |
| **5-minute** | 5 days | Primary trend (EMA 5 vs 20), RSI, MACD, short-term momentum |
| **15-minute** | 1 month | Confirmation trend, EMA 200, longer-term context |

### The Scoring System (0-100 Points)

Each indicator adds or subtracts points:

**STOCK BOT SCORING:**

| Condition | Points | Weight |
|-----------|--------|--------|
| 5m and 15m trend AGREE (both UP or both DOWN) | **+15** | Critical — if they disagree, NO signal |
| Price above VWAP (for CALL) or below VWAP (for PUT) | **+12** | Important |
| 1-candle price delta aligns with trend | **+12** | Momentum |
| 5-candle price delta aligns with trend | **+8** | Sustained momentum |
| Volume ratio ≥ 1.2x average | **+8** | Confirms genuine move |
| ATR > 0.5 (enough volatility) | **+5** | Tradeable range |
| Smart money aligns (OI analysis) | **+8** | Institutional flow |
| PCR supports direction (>1.2 for CALL, <0.8 for PUT) | **+5** | Options market sentiment |
| RSI in healthy zone (40-70 for CALL, 30-60 for PUT) | **+8** | Not overbought/oversold |
| RSI overbought (>70 for CALL direction) | **-10** | Danger — reversal risk |
| RSI oversold (<30 for PUT direction) | **-10** | Danger — bounce risk |

**INDEX BOT SCORING** (slightly different weights):

| Condition | Points |
|-----------|--------|
| 5m and 15m trend agree | **+20** |
| Price vs VWAP aligns | **+15** |
| 1-candle delta aligns | **+15** |
| 5-candle delta aligns | **+10** |
| Volume ratio ≥ 1.2x | **+10** |
| ATR > 0.5 | **+5** |
| Smart money aligns | **+10** |
| PCR supports | **+5** |

### Dynamic Threshold Adjustment

The minimum score needed to trigger a signal is NOT fixed at 60 — it adjusts:

| Condition | Threshold Change | New Min |
|-----------|-----------------|---------|
| Normal market | Base 60 | 60 |
| Morning session (before 10:00) | +5 | 65 |
| Closing session (after 14:30) | +10 | 70 |
| After losing money today (>60% of max loss) | +15 | 75 |
| High VIX (>22) | +10 | 70 |
| Expiry day (Index bot only) | +10 | 70 |
| Expiry week (Index bot only) | +5 | 65 |
| VIX ≥ 27 | **BLOCKED** | No trades at all |

### Signal Strength Bands

| Score | Strength | Stars | What It Means |
|-------|----------|-------|---------------|
| 90-100 | STRONG | ⭐⭐⭐⭐⭐ | Very high confidence — all indicators align |
| 85-89 | STRONG | ⭐⭐⭐⭐ | High confidence — strong trend + good confirmation |
| 70-84 | MODERATE | ⭐⭐⭐ | Good setup but not all indicators agree |
| 60-69 | WEAK | ⭐⭐ | Borderline — only take with extra caution |
| Below 60 | NONE | — | No signal generated |

### CALL vs PUT Decision

This is NOT a guess. The direction is determined by EMA trend analysis:

```
IF EMA(5) > EMA(20) on 5-minute chart  →  5m trend = UP
IF EMA(5) > EMA(20) on 15-minute chart →  15m trend = UP

BOTH UP   → Direction = CALL (buy call option — bullish bet)
BOTH DOWN → Direction = PUT  (buy put option — bearish bet)
DISAGREE  → NO SIGNAL (conflicting trends, stay out)
EITHER FLAT → NO SIGNAL (no clear trend, stay out)
```

---

## 7. TRADING ACTIONS — WHEN TO BUY, WHEN TO SELL

### WHEN TO BUY (Enter a Trade)

**You should BUY when the dashboard shows an ACTION ALERT with:**

1. Score ≥ Threshold (e.g., 75/60 means score 75, threshold 60 — good)
2. Direction is clear (CE or PE)
3. Stars ≥ 3 (⭐⭐⭐ or more for safer trades)
4. The WHY explanation makes sense to you

**Step-by-step manual entry:**

1. See signal: `⭐⭐⭐⭐ RELIANCE — Strong Buy CE  Score: 88/60`
2. Open your broker (Zerodha/Angel/Groww)
3. Go to RELIANCE options chain
4. Select the **nearest weekly expiry**
5. Find the **ATM (At-The-Money) CE option** — strike closest to current stock price
6. **BUY** that option at market price
7. Immediately set:
   - **Stop Loss** = Entry price × 0.85 (Stock bot) or × 0.88 (Index bot)
   - **Target** = Entry price × 1.35 (Stock bot) or × 1.30 (Index bot)

**Example:**
```
Signal: RELIANCE CALL, Score 88/60
RELIANCE CMP: ₹1,375
ATM Strike: 1380 CE
Option Premium: ₹42
Lot size: 250

YOU BUY:  RELIANCE 1380 CE at ₹42
SL:       ₹42 × 0.85 = ₹35.70  (loss of ₹1,575 per lot)
TARGET:   ₹42 × 1.35 = ₹56.70  (profit of ₹3,675 per lot)
```

### WHEN TO SELL (Enter a Bearish Trade)

If the signal says PUT (PE):

```
Signal: HDFCBANK PUT, Score 82/60
HDFCBANK CMP: ₹1,750
ATM Strike: 1750 PE
Option Premium: ₹38

YOU BUY:  HDFCBANK 1750 PE at ₹38
SL:       ₹38 × 0.85 = ₹32.30
TARGET:   ₹38 × 1.35 = ₹51.30
```

**NOTE:** You are always BUYING options (CE or PE). You never need to "sell" or "short" options. CE = bullish bet, PE = bearish bet.

### WHEN TO STAY OUT (No Trade)

Do NOT trade when:

- Score < Threshold (e.g., 45/60 — too weak)
- Signal says "HOLD" or "No Signal"
- Strength = NONE or WEAK (for conservative traders)
- VIX > 22 (volatile market — threshold raised automatically; VIX > 27 blocks all trades)
- Less than 40 minutes to market close (3:20 PM)
- You already hit your daily target or daily loss limit
- Market is in the first 5 minutes (09:15-09:20) — too noisy

---

## 8. STOP LOSS, TARGETS & EXIT RULES

### Stock Bot Default Levels

| Level | Multiplier | Meaning | Example (Entry ₹42) |
|-------|-----------|---------|---------------------|
| **Stop Loss** | Entry × 0.85 | Exit at 15% loss | ₹35.70 |
| **Target** | Entry × 1.35 | Exit at 35% profit | ₹56.70 |
| **Trail Start** | Entry × 1.12 | Start trailing after 12% gain | ₹47.04 |
| **Trail Level** | Peak × 0.92 | Trail stop at 92% of highest price | Moves up |
| **Partial Exit** | Entry × 1.18 | Book half profit at 18% gain | ₹49.56 |
| **SL Warning** | Entry × 0.92 | Alert when approaching SL | ₹38.64 |

### Index Bot Default Levels

| Level | Multiplier | Meaning | Example (Entry ₹180) |
|-------|-----------|---------|----------------------|
| **Stop Loss** | Entry × 0.88 | Exit at 12% loss | ₹158.40 |
| **Target** | Entry × 1.30 | Exit at 30% profit | ₹234.00 |
| **Trail Start** | Entry × 1.10 | Start trailing after 10% gain | ₹198.00 |
| **Trail Level** | Peak × 0.93 | Trail stop at 93% of peak | Moves up |
| **Partial Exit** | Entry × 1.15 | Book half at 15% gain | ₹207.00 |
| **SL Warning** | Entry × 0.95 | Alert near SL | ₹171.00 |

### Signal Engine Levels (Web Dashboard)

The web dashboard uses ATR-based dynamic levels instead of fixed percentages. All values are configurable via `config_template.json`:

| Level | Calculation | Config Key | Default |
|-------|------------|------------|---------|
| **Stop Loss** | Entry ± (multiplier × ATR) | `ATR_SL_MULTIPLIER` | 1.5 |
| **TP1** | Entry ± (ratio × ATR) | `FIB_TP1_RATIO` | 0.618 |
| **TP2** | Entry ± (ratio × ATR) | `FIB_TP2_RATIO` | 1.0 |
| **TP3** | Entry ± (ratio × ATR) | `FIB_TP3_RATIO` | 1.618 |
| **Support** | Pivot-point based S1 | — | Dynamic |
| **Resistance** | Pivot-point based R1 | — | Dynamic |

### Exit Priority (Automatic in Paper Mode)

The bot checks exits in this order every scan cycle:

```
1. EOD (3:20 PM)        → EXIT ALL — Market closing
2. Position age > 120m  → EXIT — Trade has gone stale (zombie)
3. Price ≤ Stop Loss    → EXIT — Loss limit hit
4. Price ≤ Trailing SL  → EXIT — Protecting locked-in gains
5. Price ≥ Target       → EXIT — Profit target achieved
```

### For Manual Trading — What To Do At Each Level

| Price Reaches | Action | Why |
|--------------|--------|-----|
| **SL Warning level** | Tighten attention, consider manual exit | Getting close to max loss |
| **Stop Loss** | **EXIT IMMEDIATELY** — sell the option | Never hold below SL |
| **Partial level (18%/15% gain)** | Sell HALF your quantity | Lock in some profit, let rest run |
| **Trail Start (12%/10% gain)** | Move SL to breakeven or above | Eliminate risk of loss |
| **Target hit** | **EXIT** — sell remaining quantity | Take your profit |
| **3:20 PM** | **EXIT ALL** — sell everything | Don't carry overnight |

---

## 9. POSITION MANAGEMENT — TRAILING, PARTIAL EXIT, EOD

### How Trailing Stop Works

```
Entry: ₹42 (RELIANCE CE)
SL: ₹35.70 (85%)
Trail starts at: ₹47.04 (112%)

Price moves to ₹48:
  → Trail SL = ₹48 × 0.92 = ₹44.16 (above entry — risk free now!)

Price moves to ₹55:
  → Trail SL = ₹55 × 0.92 = ₹50.60 (locked in ₹8.60 profit per unit)

Price drops to ₹50:
  → Trail SL still at ₹50.60 (from peak of ₹55)
  → Price ₹50 < Trail ₹50.60 → EXIT (lock in profit)
```

**Key rule:** Trailing SL only moves UP (for CALL). It never moves down.

### How Partial Exit Works

```
Entry: ₹42, Lot: 250, Total Qty: 500 (2 lots)

Price hits ₹49.56 (118% of entry):
  → Sell 250 (1 lot) — book ₹1,890 profit
  → Keep 250 remaining with trailing SL
  → Move trail to at least ₹44.52 (106% of entry)
```

### EOD (End of Day) Rule

**At 3:20 PM IST, ALL open positions are closed.**

This is non-negotiable because:
- These are intraday options (MIS/NRML expiry-day)
- Holding overnight carries massive gap risk
- Broker will auto-square-off at 3:25 PM anyway (with penalties)

---

## 10. WEB DASHBOARD — SETUP & USAGE

### Setup

1. Edit `dashboard_config.json` (already included with sensible defaults):

```json
{
    "BOT_TOKEN": "",
    "CHAT_ID": "",
    "AI_THRESHOLD": 60,
    "SCAN_INTERVAL": 5,
    "SCAN_TIMEOUT": 45,
    "ALERT_COOLDOWN_SECONDS": 900,
    "OFF_HOURS_SLEEP": 60,
    "MARKET_OPEN_HOUR": 9,
    "MARKET_OPEN_MIN": 15,
    "MARKET_CLOSE_HOUR": 15,
    "MARKET_CLOSE_MIN": 30,
    "DASHBOARD_PORT": 5100,
    "DASHBOARD_HOST": "127.0.0.1",
    "DASHBOARD_DEBUG": false,
    "MAX_FETCH_WORKERS": 12,
    "MIN_OHLCV_BARS": 10
}
```

Leave `BOT_TOKEN` and `CHAT_ID` empty to run without Telegram alerts. Fill them in to receive alerts.

See `config_template.json` for ALL available keys including signal thresholds, Fibonacci ratios, and more.

2. Start the server:
```
python dashboard_server.py
```

3. Open browser: **http://localhost:5100**

### What the Dashboard Shows

The dashboard displays ALL 56 instruments (53 stocks + 3 indices) in a real-time table:

| Column | What It Shows |
|--------|-------------|
| **Stock** | Symbol name |
| **Live Price** | Current market price (updates every 5 seconds) |
| **Chg%** | Today's percentage change (green = up, red = down) |
| **Signal** | BUY / SELL / HOLD |
| **Strength** | STRONG / MODERATE / WEAK badge |
| **RSI** | RSI(14) value — below 30 = oversold, above 70 = overbought |
| **MACD** | MACD histogram — positive = bullish momentum |
| **EMA 20/50/200** | Exponential moving averages |
| **Vol Ratio** | Current volume vs 20-period average (>1.2 = high volume) |
| **Support** | Nearest support level |
| **Resistance** | Nearest resistance level |
| **Stop Loss** | ATR-based stop loss level |
| **TP1 / TP2 / TP3** | Three take-profit targets (Fibonacci-based) |
| **Signal Time** | When the signal was generated |
| **Action** | Click to see trade details |

### Dashboard Filters

- **Category:** INDEX, LARGE_CAP, MID_CAP, SMALL_CAP
- **Signal:** BUY only, SELL only, HOLD only
- **Strength:** STRONG only, MODERATE only, WEAK only
- **Sector:** BANK, IT, ENERGY, PHARMA, AUTO, etc.
- **Search:** Type any stock name

### Pause / Resume Live Updates

The dashboard auto-refreshes every 5 seconds. If you need to scroll through the full stock list without it jumping back to the top:

- Click the **PAUSE** button in the filter bar to freeze updates
- While paused, data keeps arriving in the background
- Click **RESUME** to apply all pending updates at once
- The dashboard also **auto-pauses** when you're actively scrolling (resumes after 3 seconds of inactivity)
- A small "Updates paused" or "Update ready (scrolling...)" indicator shows the current state

### Clicking a Row

Opens a detail panel showing:
- Full signal information with all indicators
- Entry price, SL, TP1, TP2, TP3
- PCR, Smart Money flow, VIX
- Plain English explanation (WHY)
- An action button (simulated — alerts in browser)

---

## 11. TELEGRAM ALERTS — SETUP & READING

### Alert Format

When a signal fires, you receive a Telegram message like:

```
🟢 BUY SIGNAL — STRONG

📊 Stock: RELIANCE
💰 Price: ₹1,375.40
📈 Signal: BUY (CE)
⚡ Strength: STRONG

🛑 Stop Loss: ₹1,355.00
🎯 Targets:
   TP1: ₹1,385.00
   TP2: ₹1,395.00
   TP3: ₹1,410.00

📉 RSI: 55.2
📊 MACD: +0.70
🕐 Time: 01-Apr-2026 11:30:00
🏭 Sector: ENERGY
```

### Alert Rules

| Rule | Value | Meaning |
|------|-------|---------|
| **Cooldown** | 15 minutes per stock | Won't spam same stock every scan |
| **Dedup** | Hash-based | Same signal with same score won't re-send |
| **Direction flip bypass** | Immediate | If CALL flips to PUT, sends immediately |
| **STRONG signals** | Pinned | High-strength alerts are pinned in chat |
| **HOLD signals** | Not sent | Only BUY and SELL signals trigger alerts |

### Multi-Channel Setup (Optional)

In `dashboard_config.json`, add channel routing:

```json
{
    "CHANNEL_MAP": {
        "INDEX": "-1001234567890",
        "LARGE_CAP": "-1001234567891",
        "STRONG": "-1001234567892",
        "DEFAULT": "-1001234567893"
    }
}
```

This routes index signals to one channel, large-cap to another, and all STRONG signals to a dedicated channel.

---

## 12. RISK MANAGEMENT RULES

### Hard Limits (Automatic)

| Rule | Stock Bot | Index Bot | Action |
|------|-----------|-----------|--------|
| Max daily loss | -₹4,000 | -₹800 | Stops all trading for the day |
| Max drawdown | 30% of capital | 30% of capital | Emergency stop |
| Max open positions | 2 | 1 | No new entries when full |
| Max trades per day | 6 | 2 | No new entries after limit |
| Daily target hit | ₹800 | ₹800 | Stops new entries (profit lock) |
| VIX ≥ 27 | Blocked | Blocked | No trades allowed |
| EOD cutoff | 40 min before close | 40 min before close | No new entries |

### Position Sizing

```
Risk per trade = RISK_FIXED_AMOUNT (₹400 stock / ₹200 index)
Max lot cost = BASE_CAPITAL × 0.50 (max 50% of capital in one trade)

Lots = min(
    Risk / (Premium × (1 - SL_PCT) × Lot_Size),
    Capital × MAX_LOT_CAPITAL_PCT / (Premium × Lot_Size)
)
```

### For Manual Trading — Your Checklist Before Every Trade

```
✅ Is the score above threshold? (e.g., 75/60)
✅ Is the strength MODERATE or STRONG? (avoid WEAK)
✅ Do I have capital available? (not already at max positions)
✅ Is it before 2:40 PM? (40 min buffer to close)
✅ Is VIX < 30? (or am I okay with extra risk?)
✅ Have I not already hit my daily target/loss limit?
✅ Does the WHY explanation make fundamental sense?
✅ Is volume above average? (Vol Ratio > 1.2)
✅ Is there enough time for the trade to play out?
✅ Have I set my SL and target in my broker?
```

---

## 13. MANUAL TRADING WORKFLOW — STEP BY STEP

### Morning Routine (Before 9:15 AM)

1. Start the scripts (see Section 4)
2. Wait for self-test to pass
3. Check Telegram for startup message confirming config
4. Open your broker app/terminal

### During Market Hours (9:20 AM - 3:20 PM)

#### When a BUY CE Signal Appears:

```
Step 1: READ the signal
        → "⭐⭐⭐⭐ RELIANCE — Strong Buy CE  Score: 88/60"
        → WHY: Trend UP on 5m+15m, Price > VWAP, Volume 1.8x, RSI 55

Step 2: VERIFY in your broker
        → Open RELIANCE chart, confirm price is trending up
        → Check the option chain

Step 3: SELECT the option
        → Find nearest weekly expiry
        → Pick ATM CE (strike closest to CMP)
        → E.g., RELIANCE 1380 CE at ₹42

Step 4: CALCULATE your position
        → Risk budget: ₹400
        → SL loss per unit: ₹42 - ₹35.70 = ₹6.30
        → Max lots: 400 / (6.30 × 250) = ~0.25 → 1 lot (250 qty)

Step 5: PLACE the order
        → BUY 1 lot RELIANCE 1380 CE at market
        → Set SL order: ₹35.70
        → Set target order: ₹56.70

Step 6: MONITOR
        → Watch the dashboard for price updates
        → If price hits ₹47 (trail start): move SL to ₹43.24 (breakeven+)
        → If price hits ₹49.56 (partial): consider selling half
        → If price hits ₹56.70 (target): exit remaining
```

#### When a BUY PE Signal Appears:

```
Same steps, but:
        → Pick ATM PE option instead of CE
        → E.g., HDFCBANK 1750 PE at ₹38
        → This PROFITS when stock price FALLS
```

#### When Signal Shows HOLD:

```
→ Do NOTHING
→ Wait for a clear BUY or SELL signal
→ Never force trades on HOLD signals
```

### End of Day (3:15 - 3:25 PM)

```
Step 1: At 3:15 PM, check all open positions
Step 2: EXIT all positions by 3:20 PM
Step 3: Do NOT carry options overnight
Step 4: Review daily P&L in Telegram summary
Step 5: Script will send EOD report automatically
```

---

## 14. ENHANCEMENT PHASES — ADVANCED FEATURES

This section describes the eight enhancement phases built into v2.42. All features are **opt-in via config** — defaults are safe and conservative. Each phase is fully isolated; a crash or missing dependency in any phase never affects core signal generation or trade execution.

---

### Phase 1 — Regime Filter (Market Condition Classifier)

**Module:** `core/regime_filter.py`  
**Config keys:** `regime_filter_enabled`, `regime_lookback_days`, `regime_trend_threshold`, `regime_vol_threshold`

Classifies the current market as TRENDING, RANGING, or VOLATILE using recent NIFTY returns and a volatility proxy. This feeds into signal gating and position sizing.

| Config Key | Default | Description |
|------------|---------|-------------|
| `regime_filter_enabled` | `true` | Enable/disable regime classification |
| `regime_lookback_days` | `5` | Days of history used to classify regime |
| `regime_trend_threshold` | `0.004` | Return magnitude to call a trend |
| `regime_vol_threshold` | `0.012` | Std-dev threshold for VOLATILE classification |

**Behaviour:** RANGING regime → score threshold raised by `regime_ranging_score_boost`. VOLATILE regime → position size multiplied by `regime_vol_size_mult`.

---

### Phase 2 — Sniper Entry (Volume-Confirmed Entry Filter)

**Module:** `core/sniper_entry.py`  
**Config keys:** `sniper_enabled`, `sniper_volume_mult`, `sniper_lookback_bars`, `sniper_require_breakout`

Validates that a signal bar has above-average volume and (optionally) a price breakout from recent range before allowing entry. Prevents entering on thin, low-conviction moves.

| Config Key | Default | Description |
|------------|---------|-------------|
| `sniper_enabled` | `true` | Enable sniper entry filter |
| `sniper_volume_mult` | `1.5` | Signal bar volume must be ≥ N × 20-bar avg |
| `sniper_lookback_bars` | `20` | Bars used for volume average |
| `sniper_require_breakout` | `false` | Also require close above/below recent high/low |

---

### Phase 3 — Session Classifier (Time-of-Day Filter)

**Module:** `core/session_classifier.py`  
**Config keys:** `session_classifier_enabled`, `session_open_end`, `session_midday_start`, `session_midday_end`, `session_close_start`, `session_open_score_boost`, `session_close_score_boost`, `session_midday_score_penalty`

Divides the trading day into OPEN (9:15–10:00), MIDDAY (10:00–14:00), and CLOSE (14:00–15:30) sessions. Each session applies a score adjustment: open and close sessions are higher-conviction; midday is penalised.

| Config Key | Default | Description |
|------------|---------|-------------|
| `session_classifier_enabled` | `true` | Enable session-based score adjustment |
| `session_open_score_boost` | `5` | Score points added during OPEN session |
| `session_midday_score_penalty` | `-3` | Score points deducted during MIDDAY |
| `session_close_score_boost` | `3` | Score points added during CLOSE session |

---

### Phase 4 — Adaptive Position Sizing (Kelly / Volatility-Scaled)

**Module:** `core/adaptive_position_sizing.py`  
**Config keys:** `adaptive_sizing_enabled`, `kelly_fraction`, `kelly_win_rate`, `kelly_payoff_ratio`, `vol_sizing_enabled`, `vol_target_daily_pct`, `max_size_lots`, `min_size_lots`

Replaces fixed lot-size entry with a volatility-adjusted and Kelly-fraction-bounded quantity. The Kelly component uses historical win rate and payoff ratio; the vol component scales down in high-vol regimes.

| Config Key | Default | Description |
|------------|---------|-------------|
| `adaptive_sizing_enabled` | `true` | Enable adaptive sizing |
| `kelly_fraction` | `0.25` | Fractional Kelly (1.0 = full Kelly; 0.25 recommended) |
| `kelly_win_rate` | `0.50` | Assumed win rate for Kelly calculation |
| `kelly_payoff_ratio` | `1.5` | Avg win / avg loss ratio for Kelly |
| `vol_sizing_enabled` | `true` | Apply volatility scalar on top of Kelly |
| `max_size_lots` | `4` | Hard cap on lots per trade |
| `min_size_lots` | `1` | Minimum lots per trade |

---

### Phase 5 — ML Signal Classifier (LightGBM Win-Probability Scorer)

**Module:** `core/ml_classifier.py`  
**Config keys:** `ml_classifier_enabled`, `ml_min_trades_to_train`, `ml_model_path`, `ml_score_adj_cap`, `ml_high_prob_threshold`, `ml_low_prob_threshold`, `ml_retrain_interval_hours`, `ml_journal_path`  
**Requires:** `lightgbm>=4.0.0`, `scikit-learn>=1.3.0`

Trains a binary LightGBM classifier on your trade journal (`trade_journal.db`) to predict win probability for each signal. The model adjusts the raw signal score up or down before the threshold gate.

**Feature set:** score, confidence, direction (CE/PE), strength tier (STRONG/MODERATE/WEAK), has_soft_blocks, day_of_week, hour_of_entry

| Config Key | Default | Description |
|------------|---------|-------------|
| `ml_classifier_enabled` | `true` | Enable ML score adjustment |
| `ml_min_trades_to_train` | `50` | Minimum closed trades before training begins |
| `ml_model_path` | `"models/signal_classifier.pkl"` | Persisted model cache path |
| `ml_score_adj_cap` | `10` | Max ± points the model can adjust the score |
| `ml_high_prob_threshold` | `0.65` | Win prob ≥ this → +score_adj_cap boost |
| `ml_low_prob_threshold` | `0.40` | Win prob ≤ this → -score_adj_cap penalty |
| `ml_retrain_interval_hours` | `24.0` | How often to retrain from updated journal |
| `ml_journal_path` | `"trade_journal.db"` | Journal DB used for training |

**Activation:** The model is inactive (silently skipped) until `ml_min_trades_to_train` closed trades exist. It trains automatically on first qualifying run, then retrains every `ml_retrain_interval_hours`.

---

### Phase 6 — PDF Report Generator (End-of-Day Performance Report)

**Module:** `core/report_generator.py`  
**Config keys:** `report_enabled`, `report_output_dir`, `report_default_days`, `report_mode`, `report_eod_auto_generate`  
**Requires:** `reportlab>=4.0.0`

Generates a multi-section PDF from `trades.db` covering: summary statistics (win rate, profit factor, Sharpe, drawdown), equity curve, breakdowns by score bin / index / exit reason / regime, and actionable insights.

| Config Key | Default | Description |
|------------|---------|-------------|
| `report_enabled` | `false` | Enable PDF report generation |
| `report_eod_auto_generate` | `false` | Auto-generate at EOD shutdown |
| `report_output_dir` | `"reports"` | Output directory for PDFs |
| `report_default_days` | `30` | Look-back window in days (0 = all time) |
| `report_mode` | `"ALL"` | Trade mode filter: `"PAPER"`, `"LIVE"`, or `"ALL"` |

**Manual generation:**
```bash
python -m core.report_generator --days 30 --mode ALL
python -m core.report_generator --days 0 --mode LIVE --out reports/live_all.pdf
```

---

### Phase 7A — Performance Metrics Engine

**Module:** `core/performance_metrics.py`  
**Config keys:** none (pure computation library)

Provides `load_trades()`, `compute_metrics()`, and breakdown functions used by the report generator and insights engine. Computes: win rate, profit factor, Sharpe (per-trade), max drawdown, recovery factor, max consecutive wins/losses, expectancy, and regime/score/index/exit-reason breakdowns.

---

### Phase 7B — Environment Variable Config Overrides

**Module:** `core/config_bootstrap.py` → `apply_env_overrides()`  
**Prefix:** `OPBUYING_`

Any config key can be overridden at runtime by setting an environment variable with the `OPBUYING_` prefix (case-insensitive). Values are JSON-decoded, so booleans, integers, and floats round-trip correctly.

**Examples:**
```bash
# Override score threshold and disable ML via env vars
OPBUYING_AI_THRESHOLD=75 OPBUYING_ML_CLASSIFIER_ENABLED=false python index_app/index_trader.py

# Docker usage
docker run -e OPBUYING_AI_THRESHOLD=80 -e OPBUYING_EXECUTION_MODE=PAPER opb:latest
```

Values are applied after JSON file merge and type coercion — they take highest precedence.

---

### Phase 7C — Trade Journal & Insights

**Module:** `core/trade_journal.py`  
**Config keys:** `journal_enabled`, `journal_path`

Writes every closed trade to a SQLite journal (`trade_journal.db`) with full signal metadata: score, confidence, tier, direction, entry/exit prices, hold duration, exit reason, regime, session, and net PnL. This journal feeds the ML classifier and PDF report.

---

### Phase 7D — Event Calendar Filter (High-Volatility Day Blocking)

**Module:** `core/event_calendar.py`  
**Config keys:** `event_calendar_enabled`, `event_day_block_entries`, `event_day_size_mult`, `event_dates`

Marks high-volatility event days (Union Budget, RBI policy, FOMC, expiry week surprises) as restricted. On event days the bot can either block entries entirely or apply a reduced position size multiplier.

| Config Key | Default | Description |
|------------|---------|-------------|
| `event_calendar_enabled` | `true` | Enable event calendar check |
| `event_day_block_entries` | `false` | Block all entries on event days |
| `event_day_size_mult` | `1.0` | Size multiplier on event days (e.g. 0.5 = half size) |
| `event_dates` | `[]` | List of event dates: `["2026-07-23", "2026-08-06"]` |

**Example — half-size on Budget day, block on RBI day:**
```json
"event_dates": ["2026-07-23", "2026-08-06"],
"event_day_block_entries": false,
"event_day_size_mult": 0.5
```

---

### Phase 8 — Correlation Guard (Multi-Index Duplicate Prevention)

**Module:** `core/correlation_guard.py`  
**Config keys:** `correlation_guard_enabled`, `correlation_threshold`, `correlation_warn_threshold`, `correlation_lookback_bars`

Computes rolling Pearson correlation between live 1-minute close prices of NIFTY, BANKNIFTY, and FINNIFTY. When two indices are highly correlated (r ≥ `correlation_threshold`) and already-open positions exist in the same direction, the bot blocks a new entry in the correlated index — preventing the portfolio from doubling up on the same underlying move.

| Config Key | Default | Description |
|------------|---------|-------------|
| `correlation_guard_enabled` | `true` | Enable correlation check |
| `correlation_threshold` | `0.85` | Block entry if r ≥ this |
| `correlation_warn_threshold` | `0.70` | Log a warning (no block) if r ≥ this |
| `correlation_lookback_bars` | `20` | 1-minute bars used for rolling correlation |

---

## 15. TROUBLESHOOTING & FAQ

### HARD_HALT Recovery Runbook

A **HARD_HALT** is tripped automatically when the reconciliation engine detects that the bot's internal position count does not match what your broker reports (quantity mismatch). When this fires, the bot **blocks all new trade entries** until the halt is manually cleared. No trades are lost — only new entries are prevented.

#### What triggers it

- Bot believes it has an open position, but the broker shows none (or a different quantity).
- This typically happens after a broker API timeout, a partial fill, or a manual position adjustment outside the bot.

#### Step-by-step recovery

```
Step 1 — STOP new entries (already done by the halt)
         The bot will log "HARD HALT tripped — position mismatch" and alert via Telegram.

Step 2 — VERIFY your broker positions
         Open your broker terminal or app.
         List all open NSE F&O positions for today.

Step 3 — VERIFY the bot's view
         Check the Telegram position summary or the bot console.
         Compare symbol, quantity, and side (CE/PE) against your broker.

Step 4 — RESOLVE the mismatch
         If the broker has a position the bot doesn't know about:
           → Manually close or square off that position in your broker.
         If the bot thinks it has a position but the broker doesn't:
           → The order likely failed silently. No action needed in broker.
           → You may need to reset the bot's state file (see below).

Step 5 — CLEAR the halt
         Once positions are confirmed aligned, restart the bot:
           python index_app/index_trader.py
         The bot runs reconciliation at startup. If positions now match,
         the halt clears automatically and normal signal operation resumes.

Step 6 — VERIFY normal operation
         Watch for "startup checks passed" in Telegram.
         Confirm no HARD_HALT message appears on the next scan cycle.
```

#### State file reset (only if Step 5 does not clear the halt)

If the bot's state file is stale (bot thinks a position is open when it isn't):

1. Stop the bot.
2. Locate the state file: `index_bot_state.json` (in the working directory).
3. Open it and find the `open_positions` key. Verify each entry against your broker.
4. Remove any entries that have no corresponding broker position.
5. Save the file and restart the bot.

> **Warning:** Only edit the state file when the market is closed or you have confirmed no live orders are pending. A wrong edit can cause the bot to take a duplicate position.

#### Prevent recurrence

- Keep `EXECUTION_MODE: "MANUAL"` (default). In manual mode, the bot never places orders, so position mismatches cannot occur from bot-side order failures.
- If you do use PAPER or AUTO mode, always let the bot manage its own state — do not manually adjust positions in the broker without also updating the bot.
- After any broker connectivity issue (API timeout, session expiry), restart the bot rather than letting it run in an uncertain state.

---

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| "No data (market closed?)" | Outside market hours or Yahoo rate limit | Wait for market to open, or wait 5 minutes for rate limit reset |
| "yf.RateLimitError" | Too many Yahoo Finance requests | Wait 2-5 minutes, will auto-recover |
| "NSE session refreshed" repeatedly | NSE cookie expired | Normal — auto-refreshes every few minutes |
| Score always below threshold | Market is flat/choppy | Normal — bot correctly avoids bad setups |
| No signals all day | Low volatility day | Normal — no trade is better than a bad trade |
| Telegram not working | Wrong token/chat ID | Re-check BOT_TOKEN and CHAT_ID in config |
| Dashboard shows "--" for prices | Market not open or data not yet fetched | Wait for first scan cycle (5-90 seconds) |
| "TATAMOTORS.NS delisted" | Yahoo Finance symbol issue | Harmless warning — other stocks work fine |

### FAQ

**Q: Can I run both bots at the same time?**
A: Yes. They use separate config files, databases, and state files. Run in separate terminals.

**Q: Do I need Telegram to use these?**
A: No. Telegram is optional. The bots work fully without it — you just won't get push alerts. Put fake values in BOT_TOKEN/CHAT_ID if you don't want Telegram.

**Q: Is the web dashboard required?**
A: No. Each bot has its own built-in console dashboard. The web dashboard is a bonus for a prettier view.

**Q: Can these bots auto-trade with my broker?**
A: The Index bot has broker integration built in (Zerodha Kite, Angel One, custom). Auto-trading is **disabled by default** — the system runs in MANUAL mode and sends signals for you to act on. To enable auto-trading, set `EXECUTION_MODE: "AUTO"`, `BROKER_DRIVER` to your broker (e.g., `"KITE"`), and provide credentials in `BROKER_CONFIG`. Run in PAPER mode first until you fully trust the signals and have verified the broker connection.

**Q: How much capital do I need?**
A: Stock bot default: ₹10,000. Index bot default: ₹5,000. These are for option premium purchases. Adjust in config to match your actual trading capital.

**Q: Should I follow every signal?**
A: No. Focus on STRONG signals (score ≥ 85, stars ≥ 4). WEAK signals have lower win rates. You can set AI_THRESHOLD higher (e.g., 70) to only see stronger signals.

**Q: What if VIX is very high?**
A: VIX > 22: Bot raises the score threshold (harder to trigger signals). VIX > 27: Bot blocks ALL signals entirely. This protects you from trading in crash/panic conditions. For manual trading, consider wider SLs or staying out entirely when VIX is elevated.

---

## QUICK REFERENCE CARD

### Signal Action Table

| Signal | Strength | Stars | Action |
|--------|----------|-------|--------|
| BUY CE | STRONG | ⭐⭐⭐⭐+ | **BUY the ATM Call option** |
| BUY CE | MODERATE | ⭐⭐⭐ | Buy with smaller size or wait for confirmation |
| BUY CE | WEAK | ⭐⭐ | Consider skipping unless other factors support |
| BUY PE | STRONG | ⭐⭐⭐⭐+ | **BUY the ATM Put option** |
| BUY PE | MODERATE | ⭐⭐⭐ | Buy with smaller size |
| BUY PE | WEAK | ⭐⭐ | Consider skipping |
| HOLD | NONE | — | **DO NOTHING** |

### Key Price Levels (Stock Bot)

```
ENTRY ──────────────────────── ₹42.00  (you buy here)
  │
  ├── SL Warning (92%)  ────── ₹38.64  (alert: getting close to SL)
  ├── STOP LOSS (85%)   ────── ₹35.70  (EXIT — max loss reached)
  │
  ├── Partial Exit (118%) ──── ₹49.56  (sell half, lock profit)
  ├── Trail Start (112%) ───── ₹47.04  (start protecting gains)
  ├── TARGET (135%)      ───── ₹56.70  (EXIT — take full profit)
```

### Key Price Levels (Index Bot)

```
ENTRY ──────────────────────── ₹180.00
  │
  ├── SL Warning (95%)  ────── ₹171.00
  ├── STOP LOSS (88%)   ────── ₹158.40
  │
  ├── Partial Exit (115%) ──── ₹207.00
  ├── Trail Start (110%) ───── ₹198.00
  ├── TARGET (130%)      ───── ₹234.00
```

### 53 Stocks Tracked (Stock Bot)

**BANK:** HDFCBANK, ICICIBANK, SBIN, KOTAKBANK, AXISBANK, INDUSINDBK, PNB, BANKBARODA
**IT:** TCS, INFY, WIPRO, HCLTECH, TECHM
**ENERGY:** RELIANCE, ONGC, BPCL, IOC, GAIL
**PHARMA:** SUNPHARMA, DRREDDY, CIPLA, DIVISLAB
**AUTO:** MARUTI, TATAMOTORS, M&M, HEROMOTOCO
**METAL:** TATASTEEL, JSWSTEEL, HINDALCO, SAIL
**FMCG:** ITC, HINDUNILVR, NESTLEIND, DABUR, TATACONSUM
**NBFC:** BAJFINANCE, BAJAJFINSV, PFC, RECLTD
**POWER:** NTPC, POWERGRID
**INFRA:** LT, ADANIPORTS, BHEL
**OTHERS:** TITAN, BHARTIARTL, ASIANPAINT, ULTRACEMCO, APOLLOHOSP, SBILIFE, HDFCLIFE, ADANIENT, COALINDIA

### 3 Indices Tracked (Index Bot)

| Index | Lot Size | Strike Gap |
|-------|----------|------------|
| NIFTY | 25 | ₹50 |
| BANKNIFTY | 15 | ₹100 |
| FINNIFTY | 40 | ₹50 |

---

---

## EXECUTION MODES — QUICK REFERENCE

The Index bot supports three execution modes, set via `EXECUTION_MODE` in `config.json`:

| Mode | `EXECUTION_MODE` | What happens |
|------|-----------------|-------------|
| **Manual** *(default)* | `"MANUAL"` | Bot sends Telegram signals; **you place orders yourself** in your broker. No broker API needed. |
| **Paper** | `"PAPER"` | Bot simulates trades internally. Useful for testing without a broker connection. |
| **Auto** | `"AUTO"` | Bot places orders automatically via broker API. Requires `BROKER_DRIVER` and `BROKER_CONFIG`. |

**Current default:** `EXECUTION_MODE = "MANUAL"` — safest mode for live market use.

Auto-trading requires explicit configuration (no accidental activation):
1. `EXECUTION_MODE: "AUTO"`
2. `BROKER_DRIVER: "KITE"` (or `"ANGEL"` / `"CUSTOM"`)
3. Valid credentials in `BROKER_CONFIG`

The system validates this at startup and will refuse to start if the config is inconsistent.

---

*Last updated: April 2026*
*Scripts: Stock Trader v1.4 + Index Trader v2.42*
*Signal Engine v1.0 + Dashboard v1.0*
