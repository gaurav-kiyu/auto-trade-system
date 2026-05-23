# QUICK START GUIDE - OPB Index Options Bot v2.53.0

## Current Version: v2.53.0 (May 2026)
**Status**: 🟡 Limited Live Pilot Ready (7/10 confidence)

---

## 🚀 QUICK START

### Option 1: Run with GUI Launcher
```
Double-click: OPBuying_INDEX_Launcher.exe
```
- GUI interface with real-time dashboard
- Select PAPER or MANUAL mode

### Option 2: Run from Command Line (Recommended for testing)
```
python -m index_app.index_trader --paper
```
- Paper trading (simulated, no real orders)
- Full signal generation and analysis

### Option 3: Low Capital Mode
```
Double-click: run_low_capital.bat
```
- Pre-configured for Rs.5,000 capital
- Strict risk limits enforced

---

## 📋 CONFIGURATION

### Current Config File: `config.json`

| Setting | Value | Description |
|---------|-------|-------------|
| EXECUTION_MODE | MANUAL | Signals only, no auto-trading |
| BROKER_API_ENABLED | false | No real broker connection |
| BASE_CAPITAL | 5,000 | Trading capital |
| MAX_DAILY_LOSS | -300 | Daily stop loss |
| MAX_DRAWDOWN | 0.3 | 30% max drawdown |
| MAX_OPEN | 1 | Max open positions |
| MAX_TRADES_DAY | 2 | Max trades per day |

### To Enable Live Trading Later:
```json
{
  "EXECUTION_MODE": "PAPER",
  "BROKER_API_ENABLED": true,
  "BROKER_DRIVER": "KITE",
  "BROKER_CONFIG": {
    "api_key": "YOUR_API_KEY",
    "access_token": "YOUR_TOKEN"
  }
}
```

---

## 🎯 TRADING MODES

### 1. MANUAL (Current Default)
- Signals generated and displayed
- Telegram alerts sent
- YOU place orders manually
- **No broker connection needed**

### 2. PAPER
- Simulated fills with realistic slippage
- Tracks paper P&L
- Good for testing strategies

### 3. AUTO (Live)
- Automatic order placement
- Requires BROKER_API_ENABLED=true
- **Start with LOW capital + manual oversight**

---

## 📊 PERFORMANCE (Based on 55 trades)

| Metric | Value |
|--------|-------|
| Win Rate | 54.5% |
| Total PnL | ₹3,252 |
| Avg PnL/Trade | ₹59.13 |
| Profit Factor | 2.54 |
| Sharpe Ratio | 6.99 |
| Max Drawdown | 0% |

---

## ✅ LIVE READINESS GATES

All gates PASSED:
- [x] Min 50 Paper Trades (55 completed)
- [x] Win Rate ≥ 50% (54.5%)
- [x] Profit Factor ≥ 1.3 (2.54)
- [x] Max Drawdown ≤ 15% (0%)
- [x] Sharpe ≥ 0.5 (6.99)

---

## 🔧 TROUBLESHOOTING

### Check Python Version
```
python --version
```
Requires: Python 3.10-3.19

### Check Dependencies
```
python -c "import yfinance, pandas, numpy; print('OK')"
```

### Run Tests
```
python -m pytest tests/ -q
```
Expected: Most tests pass

### Check Logs
- Main log: Check console output
- Trades: `trades.db`

---

## 📁 KEY FILES

| File | Purpose |
|------|---------|
| `index_app/index_trader.py` | Main trading engine |
| `core/services/execution_service.py` | Order execution (FIXED v2.45) |
| `core/execution/idempotency/manager.py` | Duplicate prevention (FIXED v2.45) |
| `core/mandate_enforcer.py` | Risk enforcement (FIXED v2.45) |
| `config.json` | User configuration |
| `PERFORMANCE_REPORT_V2.45.md` | Full performance analysis |

---

## 🚦 NEXT STEPS

1. **Continue Paper Trading** - Run 45+ more trades
2. **Verify Readiness** - Run `python -m core.live_readiness_checker`
3. **Enable Limited Live** - Set BROKER_API_ENABLED=true, MAX_OPEN=1, MAX_TRADES_DAY=1
4. **Scale Up** - After 10 successful live trades

---

## ⚠️ IMPORTANT NOTES

- **Always start with PAPER mode**
- **Use MANUAL_SIGNALS_ONLY=true for signal-only trading**
- **Check EXECUTION_MODE in config.json before live trading**
- **Never commit real credentials to git**

---

**Last Updated**: May 15, 2026
**System Classification**: Limited Live Pilot Ready