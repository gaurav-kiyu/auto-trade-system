# OPB Index Options Bot v2.53.0 - Complete Setup Guide

## Version: 2.45 (Production Ready - Limited Live Pilot)
## Date: May 15, 2026

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [System Requirements](#2-system-requirements)
3. [Installation](#3-installation)
4. [Configuration](#4-configuration)
5. [Running the System](#5-running-the-system)
6. [Trading Modes](#6-trading-modes)
7. [Performance Metrics](#7-performance-metrics)
8. [Risk Controls](#8-risk-controls)
9. [Troubleshooting](#9-troubleshooting)
10. [Upgrading](#10-upgrading)

---

## 1. Quick Start

### Option A: GUI Launcher (Recommended for Beginners)
```
1. Double-click: OPBuying_INDEX_Launcher.exe
2. Select PAPER or MANUAL mode
3. Click START
```

### Option B: Command Line
```
1. Open terminal/command prompt
2. Navigate to project folder
3. Run: python -m index_app.index_trader --paper
```

### Option C: Low Capital Mode
```
1. Double-click: run_low_capital.bat
2. Confirm with Y
3. Bot starts in PAPER mode with Rs.5,000
```

---

## 2. System Requirements

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| Python | 3.10 | 3.10-3.14 |
| OS | Windows 10+ | Windows 11 |
| RAM | 4 GB | 8 GB |
| Disk | 500 MB | 1 GB |
| Internet | 10 Mbps | 50 Mbps |

### Required Dependencies
```
pip install -r requirements.txt
```

---

## 3. Installation

### Step 1: Clone/Download
```
git clone <repository-url>
cd OPB_FINAL_MT
```

### Step 2: Install Dependencies
```
pip install -r requirements.txt
```

### Step 3: Verify Installation
```
python -c "import yfinance, pandas, numpy; print('OK')"
```

### Step 4: Run Tests (Optional)
```
python -m pytest tests/ -q
```

---

## 4. Configuration

### Main Config: config.json
```json
{
    "EXECUTION_MODE": "MANUAL",        // MANUAL, PAPER, AUTO
    "BROKER_API_ENABLED": false,        // true for live trading
    "BASE_CAPITAL": 5000,              // Trading capital
    "MAX_DAILY_LOSS": -300,            // Daily stop loss
    "MAX_OPEN": 1,                    // Max open positions
    "MAX_TRADES_DAY": 2               // Max trades per day
}
```

### Preset Configs
| File | Use Case |
|------|-----------|
| config.json | Default (Rs.5,000, MANUAL mode) |
| config.lowcap.json | Low capital (Rs.2,000) |
| config.paper.json | Paper trading only |
| config.template.json | Template for customization |

---

## 5. Running the System

### Run from Command Line
```bash
# Paper trading (simulation)
python -m index_app.index_trader --paper

# Manual mode (signals only)
python -m index_app.index_trader --manual

# With custom config
python -m index_app.index_trader --config config.lowcap.json

# Debug mode
python -m index_app.index_trader --debug

# Self-test
python -m index_app.index_trader --selftest
```

### Run from GUI
```
Double-click: OPBuying_INDEX_Launcher.exe
```

### Run with BAT File
```
Double-click: run_low_capital.bat
```

---

## 6. Trading Modes

| Mode | Description | Broker Connection |
|------|-------------|-------------------|
| **MANUAL** | Signals generated, displayed, manual order placement | Not required |
| **PAPER** | Simulated fills, tracks paper P&L | Not required |
| **AUTO** | Automatic order execution | Required |

### Current Configuration
- **EXECUTION_MODE**: MANUAL (safe default)
- **BROKER_API_ENABLED**: false (no live orders)
- **MANUAL_SIGNALS_ONLY**: true

---

## 7. Performance Metrics

### Live Results (55 Paper Trades)
| Metric | Value |
|--------|-------|
| Total Trades | 55 |
| Win Rate | 54.5% |
| Profit Factor | 2.54 |
| Total PnL | +₹3,252 |
| Avg PnL/Trade | ₹59.13 |
| Sharpe Ratio | 6.99 |
| Max Drawdown | 0% |

### By Index
| Index | Trades | PnL | Avg |
|-------|--------|-----|-----|
| NIFTY | 19 | ₹1,430 | ₹75.26 |
| BANKNIFTY | 18 | ₹1,062 | ₹59.00 |
| FINNIFTY | 18 | ₹760 | ₹42.22 |

---

## 8. Risk Controls

### Hard Stops (Non-Negotiable)
| Control | Value | Action |
|---------|-------|--------|
| Per-Trade Risk | 1.5% | Auto-exit at stop |
| Daily Stop | -300 INR (-6%) | No more trades |
| Weekly Circuit | -5% | 0.75× sizing |
| Max Drawdown | 12% | Paper mode |
| Loss Streak | 3 losses | 2-hour cooldown |
| VIX Block | >30 | Zero entries |
| Data Stale | >30s | No new entries |

### Position Sizing
| Regime | Risk Multiplier |
|--------|-----------------|
| TRENDING | 1.2× (1.8%) |
| SIDEWAYS | 0.85× (1.275%) |
| RANGE | 0.75× (1.125%) |
| UNCLEAR | 0.5× (0.75%) |

---

## 9. Troubleshooting

### Common Issues

**Python not found**
```
Solution: Install Python 3.10-3.19 from python.org
```

**Import errors**
```
Solution: pip install -r requirements.txt
```

**Telegram not working**
```
Solution: Set BOT_TOKEN and CHAT_ID in config.json
```

**No signals generated**
```
Check: VIX must be 12-28, time must be 9:20-14:45 IST
```

### Health Check
```
python -m core.health_checker
```

### Live Readiness Check
```
python -m core.live_readiness_checker
```

---

## 10. Upgrading

### From Previous Versions
1. Backup config.json
2. Pull latest code
3. Update requirements: `pip install -r requirements.txt --upgrade`
4. Run tests: `python -m pytest tests/ -q`
5. Start in PAPER mode first

### Version History
| Version | Date | Key Changes |
|---------|-----|-------------|
| v2.45 | May 2026 | TOCTOU fix, idempotency, failover alert |
| v2.44 | Apr 2026 | Liquidity guard, reentry evaluator |
| v2.43 | Mar 2026 | Session classifier, IV rank |

---

## Support

- Documentation: SETUP_AND_TRADING_GUIDE.md
- Performance: PERFORMANCE_REPORT_V2.45.md
- Quick Start: QUICK_START_GUIDE.md
- Presentation: presentation_v245.html

---

**System Status: PRODUCTION READY**
**Classification: Limited Live Pilot (7/10)**
**Mandate: Survive First. Compound Second.**