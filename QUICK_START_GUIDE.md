# QUICK START GUIDE — OPB Index Options Bot v2.53.0

**Current Version:** v2.53.0 (June 2026)  
**Status:** ✅ CONDITIONAL PRODUCTION READY (9.0/10 institutional evidence-based score)  
**Classification:** Institutional Indian Capital Market Super Platform

---

## 🚀 QUICK START

### Option 1: Paper Trading (Recommended First)
```bash
python -m index_app.index_trader --paper
```
- Simulated fills with realistic slippage
- Full signal generation, risk checks, and analysis
- **No real broker connection needed**
- Safe — never reaches a real broker API

### Option 2: GUI Launcher
```
Double-click: OPBuying_INDEX_Launcher.exe
```
- Real-time dashboard with monitoring
- Select PAPER or MANUAL mode

### Option 3: Low Capital Mode
```
Double-click: run_low_capital.bat
```
- Pre-configured for Rs.5,000 capital
- Strict risk limits enforced

### Option 4: Docker
```bash
docker compose up -d
docker compose logs -f opb
```
- Paper mode by default in Docker

### Generate PDF Report
```bash
python -m core.report_generator --days 30 --mode PAPER
```

---

## 📋 CONFIGURATION

### Config Files (3-Layer Merge)
1. `index_config.defaults.json` — Single source of truth (~860 keys)
2. `config.json` — User overrides
3. `config.local.json` — Local-only overrides (gitignored)
4. `OPBUYING_*` env vars — Secrets (BOT_TOKEN, CHAT_ID, API keys)

### Quick Config for Paper Trading
```json
{
  "EXECUTION_MODE": "PAPER",
  "BROKER_API_ENABLED": false,
  "BASE_CAPITAL": 5000,
  "MAX_DAILY_LOSS": -300,
  "MAX_DRAWDOWN": 0.3,
  "MAX_OPEN": 1,
  "MAX_TRADES_DAY": 2
}
```

### To Enable Live Trading Later
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

| Mode | Description | Risk Level |
|------|-------------|------------|
| **MANUAL** | Signals generated + displayed; YOU place orders | ✅ Lowest |
| **PAPER** | Simulated fills with slippage, tracks P&L | ✅ Safe |
| **SHADOW** | Monitors live market without executing | ✅ Safe |
| **AUTO (Live)** | Automatic order placement via broker | ⚠️ Capital at risk |

---

## ✅ CERTIFICATION STATUS

| Gate | Score | Status |
|------|-------|--------|
| Architecture | 9.0/10 | ✅ PASS |
| Risk Controls | 9.4/10 | ✅ PASS |
| Execution Safety | 9.5/10 | ✅ PASS |
| Replay Determinism | 9.5/10 | ✅ PASS |
| Chaos Engineering | 9.0/10 | ✅ PASS |
| Black Swan | 9.0/10 | ✅ PASS |
| Security | 8.8/10 | ✅ PASS |
| **Overall** | **9.0/10** | ✅ **CONDITIONAL PRODUCTION READY** |

---

## 🔧 TROUBLESHOOTING

### Check Python Version
```bash
python --version
```
Requires: Python 3.10–3.19

### Check Dependencies
```bash
python -c "import yfinance, pandas, numpy; print('OK')"
```

### Run Tests
```bash
python -m pytest tests/ -q
```
Expected: ~2670 tests, ~99.8% pass rate (~4.5 min runtime)

### Check Logs
- Console output
- `trades.db` — Trade history
- `logs/` — Rotated log files (50MB, gzip)

---

## 📁 KEY FILES

| File | Purpose |
|------|---------|
| `index_app/index_trader.py` | Main trading brain | 
| `core/services/risk_service.py` | Final risk authority |
| `core/execution/deterministic_state_machine.py` | Order lifecycle |
| `core/execution/idempotency/certifier.py` | Exactly-once execution |
| `core/wal/journal.py` | Write-ahead intent journal |
| `index_config.defaults.json` | All configuration (~860 keys) |
| `config.json` | Your overrides |

---

## 📚 ADDITIONAL RESOURCES

| Resource | Location |
|----------|----------|
| Setup Guide | `SETUP_AND_TRADING_GUIDE.md` |
| System Guide | `SYSTEM_SETUP_GUIDE.md` |
| Architecture | `ARCHITECTURE_REVIEW.md` |
| Audit Report | `INSTITUTIONAL_AUDIT_REPORT.md` |
| Scorecard | `FINAL_EVIDENCE_BASED_SCORECARD.md` |
| Security | `SECURITY_AUDIT_REPORT.md` |
| CI/CD | `bitbucket-pipelines.yml` + `.github/workflows/` |

---

## ⚠️ IMPORTANT NOTES

- **Always start with PAPER mode**
- **Never commit real credentials to git** — use `OPBUYING_*` env vars
- **Read the Master Constitution** — `MASTER_CONSTITUTION_PROMPT_v1.0.md`
- **Run `python -m core.live_readiness_checker`** before enabling LIVE mode

---

**Last Updated:** June 22, 2026  
**System Classification:** Institutional Grade — Conditional Production Ready
