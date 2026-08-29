# QUICK START GUIDE
## OPB Index Options Buying Bot v2.59.0

**Goal:** Get from zero to paper trading in under 2 minutes.

---

### 1. Prerequisites

| Requirement | Check |
|-------------|-------|
| Python 3.10+ | `python --version` |
| Git (optional) | `git --version` |

### 2. Install

```bash
cd C:\OPB   # or your project folder

# Create virtual environment (recommended)
python -m venv venv
venv\Scripts\activate

# Install dependencies
python -m pip install -r requirements.txt
```

### 3. Configure

Create `json/config.json` (minimal):

```json
{
  "EXECUTION_MODE": "PAPER",
  "BROKER_API_ENABLED": false,
  "BASE_CAPITAL": 5000,
  "MAX_DAILY_LOSS": -300,
  "AI_THRESHOLD": 60
}
```

### 4. Start Paper Trading

```bash
python -m index_app.index_trader --paper --debug
```

**What you'll see:**
```
[INFO] Starting OPB Index Options Bot v2.57.0
[INFO] Execution mode: PAPER
[INFO] Market status: WAITING (opens at 09:15 IST)
```

### 5. What's Different in v2.57.0 Paper Trading

The paper trader now simulates **real exchange behavior**:

| Feature | Effect |
|---------|--------|
| **Bid-Ask Spread** | BUY fills at ask price, SELL fills at bid price |
| **Random Walk Prices** | Prices evolve between scans (like real ticks) |
| **Market Impact** | Orders >₹5L move price against you |
| **Partial Fills** | Large orders get only partial fill (OI-based) |
| **Indian Broker Commission** | STT + Exchange + GST 18% + SEBI + Stamp duty |
| **Circuit Limits** | ±20% price filter (matches NSE) |
| **Fill Delays** | Randomized 25ms-100ms (network+exchange processing) |

### 6. Quick Commands Reference

| Task | Command |
|------|---------|
| **Paper trading** | `python -m index_app.index_trader --paper` |
| **Paper + debug** | `python -m index_app.index_trader --paper --debug` |
| **Manual mode** | `python -m index_app.index_trader` |
| **Custom config** | `OPBUYING_INDEX_CONFIG=config.my.json python index_app/index_trader.py --paper` |
| **Run all tests** | `python -m pytest tests/ -q` |
| **Smoke test** | `python -m pytest tests/test_smoke.py -v` |
| **Health check** | `python -m core.health_checker` |
| **Live readiness** | `python -m core.live_readiness_checker` |
| **Backtest** | `python run_backtest.py --yf-quarter` |
| **Trade replay** | `python -m core.trade_replayer --last 5` |

### 7. Certification Pipeline (v2.57.0)

```bash
# Full certification (13 tools)
make certify

# Quick health check (skip slow benchmarks)
make certify-fast

# CI mode
python scripts/run_certify.py --ci
```

### 8. Paper Trader Test Suite (82 tests)

```bash
# Run all paper trading tests
python -m pytest tests/test_paper_trader.py tests/test_paper_trader_enhanced.py -v

# Run validation script tests
python -m pytest tests/test_validation_scripts.py -v
```

### 9. Market Hours (IST)

| Window | Action |
|--------|--------|
| Before 09:15 | Bot waits |
| 09:15 – 09:20 | Market opens (no signals) |
| **09:20 – 15:20** | **✅ Active trading** |
| 15:20 – 15:30 | Positions closed |
| After 15:30 | EOD report, bot sleeps |

### 10. Common Issues

| Problem | Fix |
|---------|-----|
| `yf.RateLimitError` | Wait 2-5 min (auto-recovers) |
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| Telegram not working | Verify `BOT_TOKEN` + `CHAT_ID` in `json/config.local.json` |
| `HARD_HALT` | Check `json/trader_state.json`, reconcile positions |
| No signals | Normal in low-volatility markets |

---

*Full guide: `docs/HOW_TO_USE_SYSTEM.md`*
*Setup & config: `SYSTEM_SETUP_GUIDE.md`*
