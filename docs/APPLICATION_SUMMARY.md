# Application Summary — OPB Index Options Trading Platform

> **Deliverable #2** — Comprehensive system overview
> **Version:** 2.53.0
> **Date:** 2026-06-20

---

## 1. Identity

| Attribute | Value |
|-----------|-------|
| **Name** | OPB Index Options Buying Bot |
| **Version** | 2.53.0 |
| **Category** | Automated NSE Index Options Trading Platform |
| **Target Markets** | NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX |
| **Asset Classes** | Index Options, Equities, Futures, Commodities, Currency, Mutual Funds |
| **Architecture** | Clean Architecture with Domain-Driven Design |
| **Language** | Python 3.10–3.14 |
| **Primary Broker** | Zerodha Kite (with Angel Broking backup) |
| **Primary Data** | Yahoo Finance, NSE API, WebSocket feeds |
| **Maturity** | 8.4/10 Institutional (CONDITIONAL APPROVED) |

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Presentation Layer                       │
│  Tkinter GUI  │  Enterprise Dashboard (FastAPI)  │  CLI     │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    Application Layer                         │
│  index_trader.py  │  TradingLoopService  │  DI Container     │
│  SignalEvaluator  │  PositionService     │  MandateService   │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      Domain Layer                            │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐  │
│  │   Risk Domain  │  │  Execution     │  │  Portfolio     │  │
│  │  RiskService   │  │  StateMachine  │  │  Optmizer      │  │
│  │  Kelly/VaR     │  │  Idempotency   │  │  Correlation   │  │
│  │  Stress Tests  │  │  Reconciliation│  │  Monte Carlo   │  │
│  └────────────────┘  └────────────────┘  └────────────────┘  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐  │
│  │  Signal Domain │  │  Strategy      │  │  Governance    │  │
│  │  AdaptiveSig   │  │  Spread/Strad  │  │  Constitution  │  │
│  │  ML Classifier │  │  Iron Condor   │  │  SLO/SLA       │  │
│  │  IV Rank/GEX   │  │  Scale-In      │  │  Certification │  │
│  └────────────────┘  └────────────────┘  └────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                  Infrastructure Layer                         │
│  Broker Adapters  │  Market Data  │  Persistence  │  Auth    │
│  (Kite/Angel/Paper)│  (YF/NSE/WS)  │  (SQLite/WAL)  │  (JWT)  │
└─────────────────────────────────────────────────────────────┘
```

**Key Architectural Properties:**
- **Port/Adapter**: All external dependencies behind interfaces
- **Dependency Injection**: `core/di_container.py` manages lifetimes
- **Domain Isolation**: Risk, Execution, Portfolio, Signal as bounded contexts
- **Exactly-Once Execution**: WAL journal + idempotency certifier
- **Hash-Chained Audit Trail**: Immutable SHA-256 event store

---

## 3. Core Capabilities

### Trading
- Automated signal generation (RSI, MACD, ADX, PCR, IV Rank, GEX, FII/DII)
- ML-enhanced win probability prediction (LightGBM, 14 features, SHAP)
- Multi-strategy: Directional, Spread, Straddle, Iron Condor
- Smart strike selection (ATM/OTM/DELTA-based)
- Scale-in/out position management
- Partial exit with theta decay optimization

### Risk Management
- Hard halt kill switch (never bypassable)
- Multi-layered position sizing (Kelly, VaR, VIX-scaling, drawdown)
- 4-scenario stress testing (Flash Crash, Slow Grind, Gap Up, Expiry Crush)
- Real-time intraday loss limits
- Circuit breaker per broker operation
- Cross-index correlation guard

### Execution Safety
- Deterministic state machine for order lifecycle
- WAL journal for crash recovery
- Continuous broker reconciliation
- Exactly-once idempotency enforcement
- Partial fill handling
- Retry policy with exponential backoff

### Institutional Governance
- Constitution validation (23 categories, evidence-based scoring)
- AI governance gate (pre-implementation checks)
- Release governance automation
- SLO/SLA tracking (15 objectives)
- Certification gates (strategy, replay, paper)
- Version compatibility matrix
- Independent auditor (10 audit categories)
- Capacity planning and forecasting
- FinOps cost governance
- Regulatory reporting (SEBI compliance)

### Observability
- Prometheus metrics (:9090/metrics)
- Health check dashboard
- Self-healing orchestration (7 failure patterns)
- Global risk dashboard
- PDF trade report generation
- Trade replay visualizer
- Parameter sensitivity analyzer

---

## 4. Module Inventory

| Area | Files | Description |
|------|-------|-------------|
| Core Risk | 12 | RiskService, VaR, Kelly, Stress, Greeks |
| Core Execution | 9 | StateMachine, WAL, Idempotency, Reconcilation |
| Core Portfolio | 6 | Optimizer, Monte Carlo, Correlation Guard |
| Core Signal | 8 | Adaptive, ML, IV Rank, Session, Approval |
| Core Strategy | 6 | Spread, Straddle, Iron Condor, Scale-In |
| Core Governance | 10 | Constitution, SLO, Audit, Capacity, FinOps |
| Core Certification | 4 | Gate, Strategy/Replay/Paper certifiers |
| Core Self-Healing | 1 | Orchestrator (7 failure patterns) |
| Infrastructure | 25+ | Brokers, Market Data, Persistence, Auth |
| Tests | 200+ | ~2,670 tests |

---

## 5. Data Flow

```
[Market Data] → [Signal Engine] → [Risk Service] → [Execution] → [Broker]
     │                │                  │                │            │
     │                ▼                  │                │            │
     │         [ML Classifier]           │                │            │
     │                │                  │                │            │
     │                ▼                  ▼                ▼            ▼
     └───────── [Event Store (hash-chained audit trail)] ────────────┘
                          │
                          ▼
                   [SQLite DBs]
                   trades.db, trade_journal.db, ml_tracker.db
                   oi_snapshots.db, event_store.db, execution_state.db
```

---

## 6. Deployment Options

| Mode | Command | Description |
|------|---------|-------------|
| **Paper** | `python index_app/index_trader.py --paper` | Safe simulation, no real orders |
| **Manual** | `python index_app/index_trader.py` | Signals only, human approval required |
| **Auto** | Requires `BROKER_API_ENABLED=true` | Fully automated with broker API |
| **Docker** | `docker compose up -d` | Containerized deployment |
| **Backtest** | `python run_backtest.py` | Offline historical testing |
| **Report** | `python -m core.report_generator` | PDF trade report generation |

---

## 7. Configuration System

3-layer merge: `index_config.defaults.json` ← `config.json` ← `config.local.json` ← `OPBUYING_*` env vars

~860 config keys across all domains. Schema-validated. Hot-reloadable.

---

## 8. Database Schema

| Database | Tables | Purpose |
|----------|--------|---------|
| `trades.db` | trades | Trade execution records |
| `trade_journal.db` | execution_log | Execution quality metrics |
| `ml_tracker.db` | predictions, calibration | ML prediction tracking |
| `oi_snapshots.db` | oi_snapshots | Point-in-time OI data |
| `event_store.db` | events | Hash-chained event log |
| `execution_state.db` | state | Deterministic state machine |
| `feature_store.db` | feature_vectors | ML feature history |
| `wal_journal.db` | entries | Write-ahead intent log |

---

## 9. Security Model

- **Authentication**: JWT-based admin dashboard auth
- **Authorization**: RBAC with ADMIN/OPERATOR/VIEWER roles
- **Secrets**: All via `OPBUYING_*` environment variables (never in repo)
- **Audit**: JSONL audit trail for all operator actions
- **Network**: Rate-limited API calls, circuit-breaker protected
- **CSRF**: Double-submit cookie pattern for web dashboard

---

## 10. Production Readiness Assessment

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Paper Trading | ✅ READY | PaperBrokerAdapter, certifier |
| Shadow Live | ✅ READY | Monitor mode without execution |
| Small Capital | ⚠️ CONDITIONAL | Requires 90-day paper track record |
| Medium Capital | ❌ NOT YET | 6-month live track record needed |
| Full Auto | ❌ NOT YET | 12-month + regulatory approvals |

**Score: 8.4/10 Institutional**
