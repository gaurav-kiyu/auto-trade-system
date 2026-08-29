# ADR-006: Circuit Breaker Pattern for Market Data and Broker Resilience

## Status
ACCEPTED — July 2026

## Context
Market data providers (NSE, Yahoo Finance) and broker APIs are external dependencies that can fail intermittently or become unavailable. The trading system must degrade gracefully rather than crash, and must automatically recover when dependencies return.

## Decision
Three levels of circuit breaker protection are implemented:

### Level 1: `CircuitBreakerMonitor` (core/circuit_breaker_monitor.py)
- Monitors NSE + Yahoo Finance failure rates
- Trips on configurable failure threshold
- Alerts via Telegram on state transitions
- Market halt detection for NSE exchange-wide halts

### Level 2: `CircuitBreakerDetector` (core/circuit_breaker_detector.py)
- Real-time market-level circuit breaker detection (NSE price bands: 10%/15%/20%)
- NONE → LEVEL_1 → LEVEL_2 → LEVEL_3 → MARKET_HALT
- Triggers callback on level changes

### Level 3: `CircuitBreakerService` (core/services/circuit_breaker_service.py)
- Per-key circuit breaker (separate breakers for NSE, YF, Kite, Angel)
- Three states: CLOSED (normal) → OPEN (failing) → HALF_OPEN (testing recovery)
- Configurable thresholds per service
- Self-healing orchestrator can auto-reset after recovery window

## Consequences
- **Positive:** Graceful degradation on provider failure. Automatic recovery. Per-service isolation prevents cascading failures. Market halt detection enables fail-closed behavior.
- **Negative:** No explicit bulkhead pattern (thread pool isolation) across services — all breakers share the global thread pool.
- **Trade-off:** Circuit breaker granularity (per-key) adds complexity vs. simple global breaker. Worthwhile for multi-provider resilience.

## Related
- `core/circuit_breaker_monitor.py`
- `core/circuit_breaker_detector.py`
- `core/services/circuit_breaker_service.py`
- `core/ports/circuit_breaker/circuit_breaker_port.py`
- `core/self_healing/orchestrator.py`
