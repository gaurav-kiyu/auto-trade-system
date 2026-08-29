# OPB Multi-Asset Quant Trading System v2.59.0

[![CI](https://github.com/gaurav-kiyu/auto-trade-system/actions/workflows/ci.yml/badge.svg)](https://github.com/gaurav-kiyu/auto-trade-system/actions/workflows/ci.yml)

## Overview

OPB (Options Buying & Multi-Asset Quant System) is an enterprise algorithmic trading and portfolio diagnostic platform supporting **NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX** index options and the **complete 2,553+ active listed NSE stock universe**. The system implements 16 quantitative strategy engines, ML feature SLA quality tracking, multi-broker OAuth ingestion, and automated dual-channel alerting (Telegram & Gmail).

**Version:** 2.59.0 (Full NSE Universe & 16-Strategy Quant Engine Release)  
**Platform:** Windows (primary), Linux/Docker compatible  
**Python:** 3.10-3.19

> ### New to this project? Start here, not below.
> **[docs/GETTING_STARTED_NO_CODE.md](docs/GETTING_STARTED_NO_CODE.md)** — a
> click-only walkthrough (no terminal, no code) covering: installing Python
> correctly, double-clicking `setup.bat` then `open_app.bat`, your first
> admin login, a tour of the dashboard, and getting alerts on your phone.
> Everything below this point is the technical architecture reference for
> developers — if you just want to *run* the app, the guide above is faster.

## Primary Mandate

**Survive first. Compound second. Never reverse that order.**

All mandate rules are ACTUALLY ENFORCED:
- Risk per trade: 1.5% (not 2% or 3%)
- Daily hard stop: 2.5% of capital
- Weekly circuit: 5% → 0.75× sizing
- Max drawdown protection: 12%
- Loss streak cooldown: 2 hours after 3 losses

---

## Architecture

### Core Components

| Component | Path | Purpose |
|---|---|---|
| Trading Brain | `index_app/index_trader.py` | Main index options & equity trader |
| Full NSE Universe Scanner | `core/all_nse_scanner.py` | Scans 2,553+ listed stocks daily with 20 parallel threads |
| Portfolio Diagnostic Engine | `core/admin_portfolio_analyzer.py` | 16-strategy diagnostic engine & 11-broker OAuth ingestion |
| Execution Service | `core/services/execution_service.py` | Order execution with reconciliation |
| Risk Service | `core/services/risk_service.py` | Position sizing and risk limits |
| Multi-Broker Adapters | `core/adapters/broker_adapters.py` | Zerodha, Angel, Upstox, Groww, Kotak, Dhan, Paper |
| Notification Service | `core/services/notification_service.py` | Dual real-time alerts via Telegram Bot & Gmail SMTP |
| Reconciliation | `core/execution/reconciliation/service.py` | Broker-internal state sync |
| Telegram Commander | `core/telegram_commander.py` | Two-way command & alert interface |
| Adaptive Governance | `core/adaptive_behavior_governance.py` | Auto-tune safety controls |
| Multi-Asset Dispatcher | `core/strategy/multi_asset_dispatcher.py` | Cross-asset signal routing |
| Commodity Trader | `core/commodity_trader.py` | MCX commodity futures engine |
| Currency Trader | `core/currency_trader.py` | CDS currency futures engine |
| Equity Trader | `core/equity_trader.py` | NSE/BSE cash equity engine |
| Futures Trader | `core/strategy/futures_trader.py` | NSE index futures engine |

### Data Storage

| Database | Purpose |
|----------|---------|
| `db/trades.db` | Trade log and execution history |
| `db/trade_journal.db` | Execution quality tracking |
| `db/ml_tracker.db` | ML prediction calibration |
| `db/oi_snapshots.db` | Point-in-time OI history |

### Configuration

- **Defaults:** `json/index_config.defaults.json` (1,058 keys)
- **User Config:** `json/config.json` (merged with defaults)
- **Environment:** `OPBUYING_*` prefix overrides

**`OPBUYING_*` env bridge** (same contract in `core/config_loader.py` and
`index_app/domains/config/loader.py` — keep both in sync):

- `OPBUYING_<KEY>` overrides `<KEY>` case-insensitively, coerced to the
  existing key's type (`true/1/yes/on` → `True`; int/float/string as-is).
- Unknown keys are **ignored** — env vars never add new config keys.
- `BROKER_CONFIG.<field>_env` resolves broker secrets from the named env var
  (e.g. `api_key_env: "OPBUYING_BROKER_API_KEY"`); explicit config values win.
- Overrides are applied at first load and cached.

---

## Data Sources & Known Limitations

### NSE Option Chain API — Blocked by Akamai (Known External Limitation)

NSE India protects its website with **Akamai App & API Protector**, which blocks
all automated access to the NSE option-chain endpoints (HTTP `403`). This is an
external limitation of the free tier — it affects every common scraping approach
(`requests`, `cloudscraper`, `curl_cffi`, `nselib`) and is **not a bug in this
project**. The option chain would supply Open Interest (OI) and Put-Call Ratio
(PCR) data; without it, the bot runs on price + volume data only.

**Impact is limited by design:**

- **OI/PCR-based scoring is optional, not required.** Signal generation works
  fully from index price/volume data (RSI, MACD, ADX, trend, regime, VIX).
- **Backtests use synthetic/flat OI/PCR values** (documented in the backtest
  reports) so results are conservative rather than misleading.
- The bot logs a warning when the chain is unavailable and continues scanning.

### Automatic Fallback Chain (Verified in Live Paper Runs)

The system **gracefully degrades** to free-tier sources when a layer is down:

| Data | Primary | Fallback 1 | Fallback 2 | Notes |
|------|---------|-----------|-----------|-------|
| LTP (index prices) | Kite WebSocket feed | Broker REST `get_ltp()` | **yfinance** last close | `core/ltp_resolver.py` — WS → broker → yfinance, with staleness warning on yfinance fallback |
| Intraday OHLCV (1m/5m/15m) | **yfinance** | cached snapshot | — | `core/yf_data_provider.py` — exponential backoff (5s → max 5min) + cross-cycle TTL cache |
| India VIX | **yfinance** `^INDIAVIX` | — | — | Same backoff/cache; returns `0.0` on failure |
| Option chain (OI/PCR) | NSE direct | — | — | ⚠️ Akamai-blocked (`403`); gracefully skipped — enhancement, not a dependency |

### Data Source Priority (Free Tier)

1. **yfinance** (✅ working) — LTP, intraday 1m/5m/15m, daily OHLCV, Volume, VIX
2. **Broker API** (optional, requires account) — Kite Connect can provide live
   WebSocket feeds for real-time LTP
3. **NSE direct** (⚠️ blocked by Akamai) — option-chain data not available
   without a licensed/paid feed

### What This Means for Trading

- **Paper mode works end-to-end** on the free tier (verified during live-market
  paper runs: NIFTY/BANKNIFTY/FINNIFTY LTP + signals generated successfully).
- If you need real OI/PCR data, connect a **broker WebSocket feed** (Kite Connect)
  or a licensed NSE data feed; the option-chain consumers (`core/oi_snapshot_store.py`,
  `core/strike_selector.py`, `core/iv_rank.py`) activate automatically once a
  chain source is available.

---

## Features

### Signal Generation
- IV Rank / IV Percentile (Phase 1)
- Time-of-Day Session Classifier (Phase 3)
- Greeks-Aware Strike Selection (Phase 4)
- ML Signal Classifier - LightGBM (Phase 5)
- FII/DII Institutional Flow Tracker (v2.45)
- Implied Move Calculator (v2.45)
- GEX Analyzer with gamma flip detection (v2.45)

### Risk Management
- Daily loss / drawdown circuit breakers
- VIX-based position sizing
- Kelly Criterion Half-Kelly sizing (v2.45)
- Parametric VaR calculator (v2.45)
- Stress test engine (v2.45)

### Execution
- Broker abstraction via ports (Zerodha Kite, Angel Broking)
- Paper mode with realistic fills + OI filter
- Idempotency for duplicate prevention
- Retry with exponential backoff

### Multi-Asset Trading (v2.56.0)

| Module | Asset Class | Market | Default Status |
|--------|-------------|--------|----------------|
| `core/commodity_trader.py` | MCX Commodity Futures | GOLD, SILVER, CRUDEOIL, NATURALGAS, COPPER | Disabled (`COMMODITY_ENABLED: false`) |
| `core/currency_trader.py` | CDS Currency Futures | USDINR, EURINR, GBPINR, JPYINR | Disabled (`CURRENCY_ENABLED: false`) |
| `core/equity_trader.py` | NSE/BSE Cash Equities | RELIANCE, TCS, HDFCBANK, ICICIBANK, INFY | Enabled (`EQUITY_ENABLED: true`) |
| `core/strategy/futures_trader.py` | NSE Index Futures | NIFTY, BANKNIFTY, FINNIFTY | Disabled (`FUTURES_ENABLED: false`) |

All multi-asset modules integrate via `core/strategy/multi_asset_dispatcher.py`, which routes signals to the appropriate engine. Positions are bridged to the enterprise dashboard for unified risk monitoring via `core/positions/bridge.py`.

### Security (v2.46 Hardening)
- **Execution Reconciliation:** True broker-vs-internal state sync
- **DI Enforcement:** Strict broker_port required (no fallbacks)
- **Telegram Hardening:** Command validation, admin confirmation, rate limits
- **Adaptive Governance:** Auto-tune requires explicit approval in live mode
- **Secret-free:** No .env or config backups in codebase

---

## System Review (2026-08-08)

Full end-to-end review, live-market validation and security-hardening deliverables:

- **Summary PDF:** [`docs/review/SYSTEM_REVIEW_SUMMARY.pdf`](docs/review/SYSTEM_REVIEW_SUMMARY.pdf)
- **Architecture deck:** [`docs/review/ARCHITECTURE_OVERVIEW.pptx`](docs/review/ARCHITECTURE_OVERVIEW.pptx)
- **Regenerate:** `python scripts/generate_review_artifacts.py`

Highlights: live-market session (PAPER mode) running against real NSE data with zero orders and
clean reconciliation; bandit 0 HIGH / 14 MEDIUM (annotated safe code); governance score 9.19/10
across 111 categories; hygiene PRISTINE; architecture compliance PASSED; full regression suite
(~14,700 tests) green. The live-readiness gate still blocks AUTO until the 50-paper-trade track
record is built — see the PDF for the full scorecard.

---

## Usage

### Quick Start

```bash
# Paper mode (safe, no real orders)
python index_app/index_trader.py --paper

# Live mode
python index_app/index_trader.py
```

### Configuration

```bash
# Custom config
OPBUYING_INDEX_CONFIG=json/config.dev.json python index_app/index_trader.py --paper
```

### CLI Tools

```bash
# Trade replay
python -m core.trade_replayer --id 42

# Parameter sensitivity
python -m core.sensitivity_analyzer --param SL_PCT --days 60

# Health check
python -m core.health_checker

# Readiness check (paper→live gate)
python -m core.live_readiness_checker
```

### Web Dashboard (optional)

Set `web_dashboard_enabled: true` in json/config.json - runs on port 8765.

---

## Testing

```bash
# Full test suite
python -m pytest tests/ -q

# Quick smoke test
python -m pytest tests/test_smoke.py -v
```

---

## Security Notes

1. **Never commit secrets** - Use `OPBUYING_*` environment variables
2. **Reconciliation freezes trading** on ambiguous state (orphan positions, stale orders)
3. **Telegram commands** require admin confirmation for dangerous operations
4. **Auto-tune** defaults to DISABLED - enable only after validation

---

## Files

| Type | Files |
|------|-------|
| Entry Point | `index_app/index_trader.py`, `launcher.py`, `core/enterprise_dashboard/__init__.py` |
| Core Services | `core/services/{execution,risk,portfolio,notification}_service.py` |
| Adapters | `core/adapters/broker_adapters.py`, `infrastructure/adapters/` |
| Ports | `core/ports/{broker,execution,risk,persistence}/` |
| Tests | `tests/test_*.py` (~14,700 tests) |
| Multi-Asset Dispatcher | `core/strategy/multi_asset_dispatcher.py` | Cross-asset engine routing |
| Data Quality Scorer | `core/data_quality_scorer.py` | Source-level data quality scoring |
| Strategy Approval | `core/strategy/approval_workflow.py` | Paper→Live promotion workflow |
| Capacity Planning | `core/capacity_planning.py` | Resource/scaling forecasting |

---

## Version History

- **v2.45:** FII/DII tracker, implied move, GEX analyzer, Kelly sizing, VaR, stress tests
- **v2.46:** Execution reconciliation, DI hardening, Telegram security, adaptive governance
- **v2.56.0:** Liquidity guard, re-entry evaluator, news sentinel, confidence bands
- **v2.57.x:** CI/CD enhancement, end-to-end review & cleanup, security/container validation
- **v2.58.0:** Live-market validation session, version sync across scripts/docs, governance 9.19/111, bandit hardening, refreshed review PDF/PPTX

---

## Support

- **Configuration Guide:** `SYSTEM_SETUP_GUIDE.md`
- **Enterprise Dashboard:** `core/enterprise_dashboard/__init__.py` (FastAPI + Jinja2 + RBAC)
- **Deployment:** `docs/deployment/DEPLOYMENT_GUIDE.md`

---

## Backtesting

```bash
# Run comprehensive backtest suite across all indices
python scripts/run_backtest_suite.py

# Single-index backtest (30-day Yahoo 1m)
python run_backtest.py --yf-quarter --yf-symbol ^NSEI --yf-days 30

# JSON output for machine processing
python run_backtest.py --yf-quarter --json

# Results saved to reports/backtest_results.json
```

## Deliverables

| Document | Format | Content |
|----------|--------|--------|
| `docs/ARCHITECTURE_SUMMARY.pdf` | PDF | Deep analysis: strengths, weaknesses, improvement suggestions, backtesting |
| `docs/ARCHITECTURE_PRESENTATION.pptx` | PPTX | Executive overview, comparative analysis, backtesting, recommendations |
| `docs/REMEDIATION_REPORT.md` | MD | Fixes applied, enhancements, weaknesses |
| ~~`docs/REGRESSION_TEST_SUMMARY.md`~~ | ARCHIVED → `docs/archive/REGRESSION_TEST_SUMMARY.md` |
| ~~`docs/BACKTESTING_REPORT.md`~~ | ARCHIVED → `docs/archive/BACKTESTING_REPORT.md` |
| `docs/DOCUMENTATION_SYNC_LOG.md` | MD | All sync activity tracked |
| `docs/RISK_MIGRATION_PLAN.md` | MD | Risk engine consolidation plan |

## Repository Hygiene

```bash
# Archive old artifacts (logs, reports, backups)
python scripts/archive_artifacts.py --dry-run  # preview first
python scripts/archive_artifacts.py            # archive files >14 days

# Clean Python cache
python -c "from pathlib import Path; import shutil; [shutil.rmtree(d) for d in Path('.').rglob('__pycache__') if d.is_dir()]"
```

*Generated: August 8, 2026 | Status: Production Ready v2.59.0*