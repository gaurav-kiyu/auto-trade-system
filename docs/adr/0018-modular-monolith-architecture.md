# ADR 0018: Modular Monolith Architecture

## Status
Accepted

## Date
2026-07-30

## Context
As the trading platform expands across indices (NIFTY, BANKNIFTY, FINNIFTY), asset classes (equities, options, futures, commodities), and domains (trading, real estate, portfolio management), a critical architectural decision is required: should we extract microservices, or maintain a monolith?

The Master Engineering Constitution v4.0 mandates **Modular Monolith first, Microservices when justified** (AST-07). This aligns with the current reality:

1. **Team size** — Small core team (<5 active developers) cannot sustain distributed system overhead
2. **Transaction consistency** — Trading requires ACID transactions across positions, risk, and execution — hard in distributed systems
3. **Latency sensitivity** — Signal generation → risk check → order placement must complete in <500ms — network hops add unacceptable latency
4. **Current architecture** — The system already has clean module boundaries via DI container, ports/adapters, and vertical slices

## Decision

We adopt **Modular Monolith** as the default deployment architecture. Modules will be extracted to microservices ONLY when all criteria below are met.

### Module Isolation Rules

Every module MUST:
1. **Own its data** — Each module has exclusive write access to its tables/prefixed collections
2. **Communicate via interfaces** — Modules interact through `core/ports/*` interfaces, never through direct imports
3. **Have explicit dependencies** — DI container wiring in `core/di_container/wire_core.py` defines all module dependencies
4. **Be independently testable** — Module tests run with mocked port implementations
5. **Have a single entry point** — Each module exposes a clean API via its `__init__.py`

### Current Module Map

| Module | Package | Dependencies | Extractable? |
|--------|---------|-------------|:------------:|
| Risk Engine | `core/services/risk_service.py` | Port interfaces only | ✅ Ready |
| Trade Execution | `core/execution/` | RiskPort, BrokerPort | ⚠️ Needs work |
| Signal Generation | `core/adaptive_signal.py` | MarketDataPort | ✅ Ready |
| Strategy Engine | `core/strategy/orchestrator.py` | SignalPort, RiskPort | ✅ Ready |
| Auth & Access | `core/auth/` | Database (shared) | ❌ Tied to monolith |
| Market Data | `core/ltp_resolver.py` | External APIs | ✅ Ready |
| Monitoring | `core/health_checker.py` | Port interfaces only | ✅ Ready |
| Reporting | `core/report_generator.py` | Database (read-only) | ⚠️ Needs work |

### Microservice Extraction Criteria

A module MAY be extracted to a standalone microservice ONLY when ALL of the following are true:

1. **Independent scaling need** — The module requires different scaling characteristics than the monolith (e.g., signal processing needs 10× the compute of risk checks)
2. **Independent deploy velocity** — The module changes at a different cadence (e.g., risk engine changes weekly, strategy engine changes daily)
3. **Polyglot persistence justified** — The module has different data storage requirements
4. **Team boundary aligned** — A dedicated team owns the module
5. **Latency budget allows network hop** — The module's response time budget is >10ms
6. **Distributed transaction pattern proven** — Saga or event-driven consistency is implemented and tested

### Migration Path (Monolith → Microservices)

```
Phase 1: Modular Monolith ← YOU ARE HERE
Phase 2: Extract stateless services (signal gen, monitoring)
Phase 3: Extract stateful services with event-driven consistency
Phase 4: Full microservices (only if criteria met)
```

## Consequences

### Positive
- ACID transaction support for critical trading operations
- Low latency (<500ms end-to-end) for signal-to-order pipeline
- Simplified development, testing, and debugging
- Single deployment unit reduces operational complexity
- All modules already designed for potential extraction when justified

### Negative
- Scaling requires vertical scaling of the entire monolith
- Single process can affect the whole system (mitigated by module isolation, circuit breakers, and health checks)
- Cannot use polyglot persistence within the monolith (mitigated by separate SQLite databases per domain)
- Technology stack is uniform (all Python) — cannot use specialized languages per module

## Compliance
Enforcement mechanisms:
1. **CI boundary test** — `tests/test_module_isolation.py` verifies no module bypasses port interfaces
2. **DI container test** — `tests/test_di_container.py` validates wiring and prevents circular dependencies
3. **Pre-commit check** — `scripts/pre_implementation_check.py` validates no direct cross-module imports
4. **Quarterly extraction review** — Every quarter, review extraction criteria and assess if any module now qualifies

## References
- Master Engineering Constitution v4.0 — AST-07 (Modular Monolith first)
- ADR 0010: Architecture Governance Framework
- ADR 0004: Broker Abstraction
- ADR 0017: Vertical Slice Architecture
- Simon Brown: "Modular Monoliths" (2021)
