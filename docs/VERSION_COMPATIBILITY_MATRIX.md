# Version Compatibility Matrix — OPB Institutional Platform

**Generated:** 2026-06-20  
**Classification:** INTERNAL — Release Engineering

---

## 1. Python Version Compatibility

| OPB Version | Python 3.10 | Python 3.11 | Python 3.12 | Python 3.13 | Notes |
|-------------|-------------|-------------|-------------|-------------|-------|
| **v2.40** | ✅ | ✅ | ⚠️ | ❌ | Deprecated `utcfromtimestamp` in 3.12+ |
| **v2.45** | ✅ | ✅ | ✅ | ⚠️ | RCA-136 fixed for 3.12+ compatibility |
| **v2.50** | ✅ | ✅ | ✅ | ✅ | 3.13 gate expanded to `<3.14` (RCA-138) |
| **v2.53** | ✅ | ✅ | ✅ | ✅ | Full 3.10–3.13 support confirmed |
| **v3.0** | ❌ | ✅ | ✅ | ✅ | 3.10 EOL, minimum raised to 3.11 |

**Current requirement:** Python 3.10–3.13 (enforced in `check_python_version()`, gate: `(3,10) <= (major,minor) < (3,14)`)

---

## 2. Operating System Compatibility

| OS | v2.40 | v2.45 | v2.50 | v2.53 | Notes |
|----|-------|-------|-------|-------|-------|
| **Windows 10+** | ✅ | ✅ | ✅ | ✅ | Primary target |
| **Windows Server 2019+** | ✅ | ✅ | ✅ | ✅ | Docker host |
| **Ubuntu 20.04+** | ✅ | ✅ | ✅ | ✅ | Docker images |
| **Debian 11+** | ✅ | ✅ | ✅ | ✅ | Docker images |
| **macOS 12+** | ⚠️ | ⚠️ | ⚠️ | ⚠️ | Not production-tested |
| **ARM64 (Raspberry Pi)** | ❌ | ❌ | ❌ | ❌ | No support planned |

---

## 3. Broker API Compatibility

| Broker | v2.40 | v2.45 | v2.50 | v2.53 | Adapter |
|--------|-------|-------|-------|-------|---------|
| **Zerodha Kite** | ✅ | ✅ | ✅ | ✅ | `core/adapters/broker_adapters.py` |
| **Angel One** | ✅ | ✅ | ✅ | ✅ | `core/adapters/broker_adapters.py` |
| **Fyers** | ❌ | ❌ | ❌ | ✅ | `core/execution/broker_exceptions.py` codes |
| **Dhan** | ❌ | ❌ | ❌ | ✅ | `core/execution/broker_exceptions.py` codes |
| **Upstox** | ❌ | ❌ | ❌ | ❌ | No adapter yet |
| **IIFL** | ❌ | ❌ | ❌ | ❌ | No adapter yet |
| **mStock** | ❌ | ❌ | ❌ | ❌ | No adapter yet |

**Broker Exception Taxonomy:** v2.53+ includes support for Fyers and Dhan error codes in `core/execution/broker_exceptions.py`.

---

## 4. Database Compatibility

| Database | v2.40 | v2.45 | v2.50 | v2.53 | Notes |
|----------|-------|-------|-------|-------|-------|
| **SQLite 3.35+** | ✅ | ✅ | ✅ | ✅ | Primary (WAL mode) |
| **PostgreSQL 14+** | ❌ | ❌ | ❌ | ❌ | Planned for v3.0 (₹25L+ scale) |
| **MySQL 8+** | ❌ | ❌ | ❌ | ❌ | Not planned |
| **Redis** | ❌ | ❌ | ❌ | ⚠️ | `core/adapters/redis_adapter.py` exists, not wired |

---

## 5. External API Compatibility

| API | v2.40 | v2.45 | v2.50 | v2.53 | Notes |
|-----|-------|-------|-------|-------|-------|
| **Yahoo Finance (yfinance)** | ✅ | ✅ | ✅ | ✅ | Primary data source |
| **NSE India** | ⚠️ | ⚠️ | ⚠️ | ⚠️ | Akamai blocked (403). Graceful fallback to yfinance |
| **Telegram Bot API** | ✅ | ✅ | ✅ | ✅ | Notifications |
| **NSE Holidays API** | ✅ | ✅ | ✅ | ✅ | With hardcoded fallback |
| **Claude API** | ❌ | ❌ | ✅ | ✅ | NLP Journal (opt-in) |
| **Prometheus** | ❌ | ❌ | ❌ | ✅ | `METRICS_PORT` config |

---

## 6. Key Dependency Version Matrix

| Package | v2.40 | v2.45 | v2.50 | v2.53 | Min | Max |
|---------|-------|-------|-------|-------|-----|-----|
| **Python** | 3.10-3.12 | 3.10-3.13 | 3.10-3.13 | 3.10-3.13 | 3.10 | 3.13 |
| **yfinance** | ≥0.2.18 | ≥0.2.30 | ≥0.2.36 | ≥0.2.40 | 0.2.18 | — |
| **pandas** | ≥1.5 | ≥2.0 | ≥2.1 | ≥2.2 | 1.5 | — |
| **numpy** | ≥1.24 | ≥1.26 | ≥1.26 | ≥1.26 | 1.24 | — |
| **lightgbm** | — | ≥4.0 | ≥4.1 | ≥4.5 | 4.0 | — |
| **scikit-learn** | — | ≥1.3 | ≥1.4 | ≥1.5 | 1.3 | — |
| **fastapi** | — | — | ≥0.100 | ≥0.110 | 0.100 | — |
| **uvicorn** | — | — | ≥0.23 | ≥0.29 | 0.23 | — |
| **reportlab** | — | — | ≥4.0 | ≥4.2 | 4.0 | — |
| **kiteconnect** | ≥5.0 | ≥5.0 | ≥5.0 | ≥5.0 | 5.0 | — |
| **requests** | ≥2.28 | ≥2.31 | ≥2.31 | ≥2.31 | 2.28 | — |
| **cloudscraper** | — | — | ≥1.2 | ≥1.2 | 1.2 | — |
| **pydantic** | — | — | ≥2.5 | ≥2.7 | 2.5 | — |

---

## 7. Config Schema Versioning

| Config Key Type | v2.40 | v2.45 | v2.50 | v2.53 |
|----------------|-------|-------|-------|-------|
| **Total keys** | ~320 | ~520 | ~680 | ~860 |
| **Schema validation** | ❌ | ❌ | ⚠️ | ✅ |
| **Strict enforcement** | ❌ | ❌ | ❌ | ⚠️ (opt-in, v2.53) |
| **Default values file** | ✅ | ✅ | ✅ | ✅ |
| **Config audit trail** | ❌ | ❌ | ❌ | ✅ |

Config schema files:
- `index_config.defaults.json` — Single source of truth for defaults
- `schemas/index_config.schema.json` — Generated JSON Schema (v2.53+)
- `index_config.schema.json` — Root-level symlink/generated schema

---

## 8. Feature Version Matrix

| Feature | v2.40 | v2.45 | v2.50 | v2.53 |
|---------|-------|-------|-------|-------|
| **IV Rank / IV Percentile** | ❌ | ✅ | ✅ | ✅ |
| **Paper Fill Simulation** | ❌ | ✅ | ✅ | ✅ |
| **Session Classifier** | ❌ | ✅ | ✅ | ✅ |
| **Greeks-Aware Strike** | ❌ | ✅ | ✅ | ✅ |
| **ML Classifier (LightGBM)** | ❌ | ✅ | ✅ | ✅ |
| **PDF Report (ReportLab)** | ❌ | ✅ | ✅ | ✅ |
| **OHLCV-only mode** | ❌ | ✅ | ✅ | ✅ |
| **Multi-Instrument Correlation** | ❌ | ✅ | ✅ | ✅ |
| **OI Snapshot Store** | ❌ | ✅ | ✅ | ✅ |
| **Monte Carlo Simulation** | ❌ | ✅ | ✅ | ✅ |
| **SHAP Explainability** | ❌ | ✅ | ✅ | ✅ |
| **Concept Drift Detector** | ❌ | ✅ | ✅ | ✅ |
| **Spread Strategy** | ❌ | ✅ | ✅ | ✅ |
| **Walk-Forward Validation** | ❌ | ✅ | ✅ | ✅ |
| **Signal Autopsy** | ❌ | ✅ | ✅ | ✅ |
| **Web Dashboard (FastAPI)** | ❌ | ✅ | ✅ | ✅ |
| **Docker Support** | ❌ | ✅ | ✅ | ✅ |
| **Liquidity Guard** | ❌ | ❌ | ✅ | ✅ |
| **Re-entry Evaluator** | ❌ | ❌ | ✅ | ✅ |
| **FII/DII Tracking** | ❌ | ❌ | ❌ | ✅ |
| **GEX Analyzer** | ❌ | ❌ | ❌ | ✅ |
| **Kelly Sizer** | ❌ | ❌ | ❌ | ✅ |
| **VaR Calculator** | ❌ | ❌ | ❌ | ✅ |
| **Stress Test Engine** | ❌ | ❌ | ❌ | ✅ |
| **Scale-In Manager** | ❌ | ❌ | ❌ | ✅ |
| **Limit Order Engine** | ❌ | ❌ | ❌ | ✅ |
| **P&L Attribution** | ❌ | ❌ | ❌ | ✅ |
| **Slippage Auto-Calibration** | ❌ | ❌ | ❌ | ✅ |
| **Equity Trading (Cash)** | ❌ | ❌ | ❌ | ✅ |
| **Deterministic State Machine** | ❌ | ❌ | ❌ | ✅ |
| **Event Store (Hash-Chained)** | ❌ | ❌ | ❌ | ✅ |
| **WAL Journal** | ❌ | ❌ | ❌ | ✅ |
| **Broker Failover** | ❌ | ❌ | ❌ | ✅ |
| **Idempotency Certifier** | ❌ | ❌ | ❌ | ✅ |
| **Constitution Engine** | ❌ | ❌ | ❌ | ✅ |
| **AI Governance Gate** | ❌ | ❌ | ❌ | ✅ |
| **Enterprise Dashboard (RBAC)** | ❌ | ❌ | ❌ | ✅ |
| **Equity Platform (SME)** | ❌ | ❌ | ❌ | ✅ |

---

## 9. Test Suite Size by Version

| Metric | v2.40 | v2.45 | v2.50 | v2.53 |
|--------|-------|-------|-------|-------|
| **Test files** | ~120 | ~200 | ~280 | ~345 |
| **Total tests** | ~800 | ~1,500 | ~2,100 | ~2,670 |
| **Test run time** | ~90s | ~180s | ~240s | ~270s |
| **Collection errors** | 0 | 0 | 0 | 0 ✅ |

---

## 10. Backward Compatibility Policy

| Change Type | Policy | Example |
|-------------|--------|---------|
| **Config key addition** | Always backward-compatible | New key with safe default |
| **Config key removal** | 2-version deprecation notice | Warn in v2.53, remove in v2.55 |
| **API signature change** | Deprecated wrapper for 1 version | Old func() → new func() with wrapper |
| **Database schema** | `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` | Event store hash columns |
| **Broker adapter** | New adapter = new file, no changes to existing | Fyers/Dhan error codes only |
| **Test file change** | No backward compatibility guaranteed | Update tests for new features |

---

## 11. Deprecation Timeline

| Deprecated Item | Since | Target Removal | Replacement |
|----------------|-------|---------------|-------------|
| `core/orchestrator.py` | v2.53 | v3.1 | `core/services/use_cases/trading_orchestrator.py` |
| `core/execution/execution_state.py` | v2.53 | v3.0 | `core/execution/deterministic_state_machine.py` |
| `tests/test_execution_execution_state.py` | v2.53 | v3.0 | `tests/test_execution_deterministic_state_machine.py` |
| Python 3.10 support | v2.53 | v3.0 | Python 3.11+ |
| `NSE_HOLIDAYS` hardcoded set | v2.50 | v2.55 | Dynamic API fetch only |
| `config.json` secrets | v2.53 | v3.0 | `OPBUYING_*` environment variables |

---

*This compatibility matrix is generated from release notes, git history, and manual verification. Update this document with every release.*
