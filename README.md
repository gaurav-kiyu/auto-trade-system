# OPB Index Options Buying Bot v2.48

## Overview

OPB (Options Buying Bot) is an automated NSE index options trading system supporting NIFTY, BANKNIFTY, and FINNIFTY. The system implements algorithmic signal generation, risk management, and execution with broker integration.

**Version:** 2.48 (Mandate Compliant)  
**Platform:** Windows (primary), Linux/Docker compatible  
**Python:** 3.10-3.19

## Primary Mandate

**Survive first. Compound second. Never reverse that order.**

- Risk per trade: 1.5% (not 2% or 3%)
- Daily hard stop: 2.5%
- Weekly circuit: 5%
- Max drawdown protection: 12%
- Loss streak cooldown: 2 hours after 3 losses

---

## Architecture

### Core Components

| Component | Path | Purpose |
|-----------|------|---------|
| Trading Brain | `index_app/index_trader.py` | Main entry point (~8200 lines) |
| Execution Service | `core/services/execution_service.py` | Order execution with reconciliation |
| Risk Service | `core/services/risk_service.py` | Position sizing and limits |
| Broker Adapters | `core/adapters/broker_adapters.py` | Kite, Angel, Paper adapters |
| Reconciliation | `core/execution/reconciliation/service.py` | Broker-internal state sync |
| Telegram | `core/telegram_commander.py` | Command interface |
| Adaptive Governance | `core/adaptive_behavior_governance.py` | Auto-tune safety controls |

### Data Storage

| Database | Purpose |
|----------|---------|
| `trades.db` | Trade log and execution history |
| `trade_journal.db` | Execution quality tracking |
| `ml_tracker.db` | ML prediction calibration |
| `oi_snapshots.db` | Point-in-time OI history |

### Configuration

- **Defaults:** `index_config.defaults.json` (490+ keys)
- **User Config:** `config.json` (merged with defaults)
- **Environment:** `OPBUYING_*` prefix overrides

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

### Security (v2.46 Hardening)
- **Execution Reconciliation:** True broker-vs-internal state sync
- **DI Enforcement:** Strict broker_port required (no fallbacks)
- **Telegram Hardening:** Command validation, admin confirmation, rate limits
- **Adaptive Governance:** Auto-tune requires explicit approval in live mode
- **Secret-free:** No .env or config backups in codebase

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
OPBUYING_INDEX_CONFIG=config.dev.json python index_app/index_trader.py --paper
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

Set `web_dashboard_enabled: true` in config.json - runs on port 8765.

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
| Entry Point | `index_app/index_trader.py`, `launcher.py` |
| Core Services | `core/services/{execution,risk,portfolio,notification}_service.py` |
| Adapters | `core/adapters/broker_adapters.py`, `infrastructure/adapters/` |
| Ports | `core/ports/{broker,execution,risk,persistence}/` |
| Tests | `tests/test_*.py` (~1500 tests) |

---

## Version History

- **v2.46:** Execution reconciliation, DI hardening, Telegram security, adaptive governance
- **v2.45:** FII/DII tracker, implied move, GEX analyzer, Kelly sizing, VaR, stress tests
- **v2.44:** Liquidity guard, re-entry evaluator, news sentinel, confidence bands

---

## Support

- **Configuration Guide:** `SETUP_AND_TRADING_GUIDE.md`
- **Live Operations:** `LIVE_OPERATIONS_GUIDE.md`
- **Deployment:** `docs/deployment/DEPLOYMENT_GUIDE.md`

---

*Generated: May 2026 | Status: Production Ready*