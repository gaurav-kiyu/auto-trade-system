# Broker Architecture Review

**Generated:** June 21, 2026  
**Status:** Complete

---

## Architecture Overview

The OPB platform uses a broker-independent architecture where all broker interactions go through `core/adapters/broker_adapters.py`. This provides a unified interface regardless of the underlying broker.

## Broker Abstraction Layer

```
Trading Logic (index_trader.py)
        ↓
Broker Adapter Interface (core/ports/broker.py)
        ↓
┌─────────────────────── Broker Adapters ───────────────────────┐
│  PaperBrokerAdapter   │   ZerodhaAdapter   │   AngelAdapter   │
│  (test/simulation)    │   (live)           │   (live)          │
└───────────────────────────────────────────────────────────────┘
        ↓
┌─────────────────────── Broker SDKs ───────────────────────────┐
│  kiteconnect  │  smartapi  │  (not in repo — runtime only)    │
└───────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Paper Mode Invariant
When `EXECUTION_MODE=PAPER` or `--paper` CLI flag is set:
- `PaperBrokerAdapter` handles all fills
- Real broker SDK is never instantiated
- This is safety-critical and enforced at startup

### 2. Broker Adapter Factory
- Located in `index_app/domains/market/adapter_factory.py` (app layer)
- Avoids core/ → infrastructure/ import violations (ADR-0010)
- Registered via DI container at startup

### 3. Broker Failover
- `core/broker_failover.py` manages multi-broker switching
- Threshold-based failover with recovery window
- Circuit breaker pattern for broker health monitoring

## Supported Brokers

| Broker | Type | Adapter | Status |
|--------|------|---------|--------|
| Paper | Simulation | `PaperBrokerAdapter` | ✅ Active |
| Zerodha (Kite) | Live | `ZerodhaAdapter` | ✅ Active |
| Angel One | Live | `AngelAdapter` | ✅ Active |

## Broker-Free Startup Flow

```
1. Paper Mode (default)
2. No Broker Enabled (config check)
3. Config Validation (credentials present)
4. Broker Credentials Loaded (from config + env)
5. Single Broker Activation
6. Application Startup
```

## Recommendations

1. Add broker health SLA tracking (latency percentiles per broker)
2. Implement multi-broker concurrent order routing (Phase 21 future)
3. Add broker reconciliation at configurable intervals
