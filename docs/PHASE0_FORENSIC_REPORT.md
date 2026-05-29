# Phase 0 — Complete Forensic Architecture Report

**Platform:** OPB Index Options Buying Bot v2.53.0  
**Date:** 29 May 2026  
**Analyst:** AI Governance Protocol v1.0  

---

## 1. Architecture Map

### 1.1 Hexagonal Architecture (Ports/Adapters)

```
┌─────────────────────────────────────────────────────────┐
│                    ENTRY POINTS                          │
│  launcher.py → index_app/index_trader.py                 │
│  run_backtest.py → core/backtest_engine.py                │
│  core/enterprise_dashboard.py (FastAPI)                   │
│  signal_engine.py / telegram_engine.py (standalone)       │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│               COMPOSITION ROOT (DI Container)             │
│          index_trader.py:setup_di_container()             │
│   Wires 15+ ports → adapters in a single location         │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                    CORE DOMAINS                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │  Signal   │ │   Risk   │ │Portfolio │ │Execution │   │
│  │  Engine   │ │  Domain  │ │  Domain  │ │  Domain  │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │Strategy  │ │  State   │ │  Session │ │    ML    │   │
│  │  Domain  │ │  Domain  │ │  Domain  │ │  Domain  │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                    PORTS (14+)                            │
│  BrokerPort  ConfigPort  RiskPort  ExecutionPort          │
│  MarketDataPort  NotificationPort  PersistencePort        │
│  MlModelPort  StrategyPort  RateLimitPort                 │
│  CircuitBreakerPort  LoggingPort  MetricsPort             │
│  CorrelationIdPort                                        │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                 INFRASTRUCTURE ADAPTERS                   │
│  KitAdapter  AngelAdapter  PaperAdapter  SQLiteAdapter    │
│  NSEAdapter  YFAdapter  TelegramAdapter  EmailAdapter     │
│  MLModelAdapter  MetricsAdapter  ConfigAdapter            │
└─────────────────────────────────────────────────────────┘
```

### 1.2 Safety Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   SAFETY LAYER                            │
│                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │  Hard Halt  │  │   Circuit   │  │  Watchdog   │      │
│  │   Event     │  │  Breaker    │  │   Thread    │      │
│  └─────────────┘  └─────────────┘  └─────────────┘      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │ Kill File   │  │  Capital    │  │  LTP Sanity │      │
│  │ (STOP_*)    │  │  Reserve    │  │    Check    │      │
│  └─────────────┘  └─────────────┘  └─────────────┘      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │   Invariant │  │   Startup   │  │   Morning   │      │
│  │   Checks    │  │  Validation │  │  Checklist  │      │
│  └─────────────┘  └─────────────┘  └─────────────┘      │
│  ┌─────────────┐  ┌─────────────┐                        │
│  │  Readiness  │  │  Operating  │                        │
│  │   Checker   │  │  Mode Gate  │                        │
│  └─────────────┘  └─────────────┘                        │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Implementation Model

| Layer | Maturity | Files | Notes |
|-------|----------|-------|-------|
| **Ports** | 95% Complete | 14 ports | Well-defined ABC interfaces |
| **Domains** | 60% Complete | 8 domains | Core domains signal/risk/portfolio/execution done |
| **Services** | 85% Complete | ~20 services | ExecutionService (58KB) is largest |
| **Infrastructure** | 90% Complete | ~15 adapters | Kite/Angel/Paper/Telegram/Yahoo/NSE all done |
| **Legacy (non-ported)** | 40% of core | ~180 files | adaptive_signal.py, pure_index_signal.py still bypass ports |
| **Config System** | 95% Complete | 3-layer merge + schema | ~860 keys, JSONL audit trail |

---

## 3. Historical Differential Analysis

### Version Timeline
```
v2.44 → v2.45 → v2.51 → v2.53 → v2.53.0 (current)
 19 items   22 items   6 phases    final remediation
```

### Regressions Identified
| Regression | Location | Severity | Status |
|-----------|----------|----------|--------|
| expiry_entry_allowed() → always True | index_trader.py:1277 | HIGH | Unfixed |
| Broker snapshot stubs → {} | index_trader.py:1139-1142 | HIGH | Unfixed |
| _execute_with_retries → NO retries | execution_service.py:903 | MEDIUM | Willful (safety) |
| FormalOrderState deprecated but still used | execution_state.py:93 | MEDIUM | Partial migration |
| 5 invariants are no-ops | invariants/checks.py | MEDIUM | Needs rewrite |

---

## 4. Dead Code Report

| File | Dead Code | Lines | Severity |
|------|-----------|-------|----------|
| `index_trader.py` | expiry_entry_allowed stub | 1277-1280 | HIGH |
| `index_trader.py` | can_reenter stub | 1282-1285 | LOW |
| `index_trader.py` | sniper_ok stub | 1287-1289 | LOW |
| `index_trader.py` | get_atm_ltp stub | 1291-1293 | LOW |
| `index_trader.py` | _ltp_sane stub | 1295-1296 | LOW |
| `index_trader.py` | latency_check stub | 1298-1299 | LOW |
| `index_trader.py` | _broker_positions_snapshot | 1139 | HIGH |
| `index_trader.py` | _local_positions_snapshot | 1142 | HIGH |
| `execution_state.py` | FormalOrderState (deprecated) | 93-197 | MEDIUM |
| `invariants/checks.py` | broker_positions_match (no-op) | 43-69 | HIGH |
| `invariants/checks.py` | no_duplicate_submissions (no-op) | 154-173 | MEDIUM |

---

## 5. Duplicate Code Report

| Item | Location | Size | Impact |
|------|----------|------|--------|
| **Full project copy** | `auto-trade-system/` | 650 files, 548 .py | HIGH — maintenance drag, confusion |
| State machine implementations | `execution_state.py` + `deterministic_state_machine.py` | 2 implementations | MEDIUM — competing state machines |
| Config loader variants | `config_bootstrap.py`, `config_loader.py`, `config_v2.py` | 3 implementations | MEDIUM — which one is canonical? |
| Root scripts | `signal_engine.py`, `telegram_engine.py` | 2 files | LOW — standalone entry points |

---

## 6. Stale File Report

| File | Reason | Action |
|------|--------|--------|
| `auto-trade-system/` | Full stale duplicate (missing ~20 newer files) | DELETE |
| `test_recon_*.db` (28 files) | Orphaned test artifacts | DELETE |
| `nonexistent_*.db` (3 files) | Zero-byte test artifacts | DELETE |
| `.pytest_cache/` | Build cache | DELETE |
| `.ruff_cache/` | Build cache | DELETE |
| `.venv/` | Virtual environment | DELETE |
| `trades.db` (root) | Should be in data/ | MOVE |
| `execution_state.db` (root) | Should be in data/ | MOVE |
| `order_state.db` (root) | Should be in data/ | MOVE |
| `trader_state.json` | Should be in data/ | MOVE |
| `audit_trail.jsonl` | Should be in logs/ | MOVE |
| `config_audit.jsonl` | Should be in logs/ | MOVE |

---

## 7. Security Gap Report

| Gap | Location | Severity | Fix |
|-----|----------|----------|-----|
| `exec()` arbitrary code execution | `trader_desk.py:18` | CRITICAL | Replace with importlib |
| Silent except:pass (118 instances) | Production code | CRITICAL | Add logging to all |
| Placeholder secrets shipped | `notification_service.py:373-374` | CRITICAL | Use None defaults |
| pickle.load() no integrity check | `ml_classifier.py:326` | HIGH | Add SHA-256 check |
| sqlite3.connect() no timeout (~80) | Production code | HIGH | Add timeout=10 |
| CI StrictHostKeyChecking=no | `.github/workflows/prod-release.yml` | HIGH | Pin host key |
| pip-audit warnings ignored | `.github/workflows/ci.yml` | HIGH | Fail on CRITICAL/HIGH |
| Bare except: in scripts | `scripts/restore.py` | HIGH | Change to except Exception |
| Rate limiting bypass for localhost | `auth/handler.py:693` | MEDIUM | Document/restrict |
| print() in production (702 instances) | Multiple files | MEDIUM | Replace with logging |

---

## 8. Reliability Gap Report

| Gap | Location | Severity | Fix |
|-----|----------|----------|-----|
| State machine errors swallowed | `execution_service.py:922-925` | CRITICAL | Propagate exceptions |
| expiry_entry_allowed() → True | `index_trader.py:1277` | HIGH | Implement real expiry gate |
| Broker pos snapshots → {} | `index_trader.py:1139` | HIGH | Implement reconciliation |
| Invariants are no-ops | `invariants/checks.py` | MEDIUM | Implement real checks |
| 30+ SQLite connections per login | `auth/handler.py` | MEDIUM | Add connection caching |
| No connection pooling anywhere | All DB modules | MEDIUM | Use Singleton pattern |
| Multiple state machines active | `execution_state.py` | MEDIUM | Consolidate to one |

---

## 9. Test Gap Report

| Gap | Details | Severity |
|-----|---------|----------|
| No test for real broker failover | broker_failover.py untested | HIGH |
| No test for expiry gate | index_trader.py expiry functions | HIGH |
| No test for invariant system | invariants/checks.py | MEDIUM |
| No test for orphan state machines | execution_state.py | MEDIUM |
| Auth handler has no concurrency test | auth/handler.py | MEDIUM |
| No performance/load tests | Entire system | MEDIUM |

---

## 10. Future-Readiness Gap Report

| Gap | Impact | Severity |
|-----|--------|----------|
| No multi-broker support ready | Only Kite/Angel adapters | HIGH |
| No multi-strategy dispatch ready | Only signal engine | MEDIUM |
| No feature flag system | Can't A/B test strategies | MEDIUM |
| No environment-aware deployment | partial via environment.py | LOW |
| No canary/blue-green support | all-or-nothing deployment | MEDIUM |
| No SBOM generation | Supply chain risk | LOW |

---

## 11. Target Final Architecture Blueprint

### Target State: v3.0 "Enterprise Production"

```
┌──────────────────────────────────────────────────────────────┐
│                     GATEWAY LAYER                             │
│  FastAPI + WebSocket + Webhook + CLI + Telegram Bot          │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    CONTROL PLANE                              │
│  Auth (RBAC) | Config Governance | Feature Flags | Audit     │
│  Rate Limiting | Circuit Breakers | Kill Switch | Health     │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  ORCHESTRATOR LAYER                           │
│  Strategy Orchestrator | Signal Pipeline | Risk Pipeline     │
│  Execution Pipeline | ML Pipeline | Market Data Pipeline     │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    DOMAIN LAYER                               │
│  Signal Domain | Risk Domain | Portfolio Domain              │
│  Execution Domain | Strategy Domain | ML Domain              │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    PORT LAYER (Abstractions)                  │
│  15+ ABC interfaces — all domain logic depends on these      │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  INFRASTRUCTURE LAYER                         │
│  Brokers (Kite/Angel/Dhan/Fyers/Upstox/IBKR)                 │
│  Market Data (NSE/Yahoo/WebSocket/Broker)                    │
│  Persistence (SQLite/PostgreSQL/Redis)                       │
│  Notifications (Telegram/Email/Slack)                        │
│  ML (LightGBM/ONNX/TensorFlow)                              │
└─────────────────────────────────────────────────────────────┘
```

---

## EXECUTIVE SUMMARY

| Category | Score (0-10) | Evidence |
|----------|-------------|----------|
| Architecture | 8.5 | Hexagonal well-defined but 60% adoption |
| Reliability | 6.5 | State machine error swallowing, no-op invariants |
| Execution Safety | 7.0 | 3-phase submit, WAL, but expiry gate broken |
| Risk Controls | 8.0 | Hard halt, circuit breakers, kill file present |
| Security | 6.0 | CRITICAL: exec(), pickle, except:pass, placeholders |
| Authentication | 8.5 | PBKDF2-600K, session mgmt, CSRF, brute-force |
| Authorization | 8.0 | RBAC with admin/operator/viewer |
| UI Quality | 7.0 | Dashboard has premium feel, 98KB template |
| UX Quality | 6.5 | GUI has except:pass everywhere |
| Admin Experience | 7.5 | Config diff, kill switch, user management |
| Observability | 7.0 | Health checks, metrics, audit trail |
| Test Maturity | 8.5 | 3,528 tests, contract/chaos/integration |
| Release Engineering | 7.0 | CI/CD exists but has security gaps |
| Scalability | 6.5 | Single-process, SQLite only |
| Maintainability | 6.0 | Duplicate tree, 108KB god module |
| Operational Resilience | 7.0 | Watchdogs, circuit breakers, recovery |
| Broker Robustness | 7.5 | Paper/Kite/Angel adapters, failover |
| Replay Determinism | 8.0 | Execution replay, backtest engine |
| ML Governance | 7.0 | Drift detection, performance tracker |
| Config Governance | 8.5 | 3-layer merge, schema, audit trail |
| Future Readiness | 6.0 | No multi-broker, multi-strategy ready |
| Production Readiness | 6.5 | Security gaps, invariant no-ops |
| Repository Hygiene | 4.0 | Duplicate tree, orphan DBs, stale files |
| Deployment Readiness | 7.0 | Docker, docker-compose, supervisord |

**OVERALL SCORE: 7.0 / 10**

**CRITICAL GAPS (< 6.9) requiring immediate remediation:**
- Maintainability (6.0) — duplicate tree, god module
- Security (6.0) — exec(), pickle, except:pass
- Repository Hygiene (4.0) — 28 orphan DBs, duplicate codebase
- Future Readiness (6.0) — missing multi-broker, multi-strategy
- Production Readiness (6.5) — no-op invariants, broken expiry gate
