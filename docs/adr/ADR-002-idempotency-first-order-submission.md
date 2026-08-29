# ADR-002: Idempotency-First Order Submission Design

## Status
ACCEPTED — July 2026

## Context
In a trading system managing real capital, duplicate order submission is unacceptable. The system must guarantee exactly-once execution even under:
- Crash during order submission
- Network timeout on broker response
- Retry logic with ambiguous outcomes
- Process restart while order is in-flight

## Decision
All order submission passes through a **multi-layered idempotency architecture**:
1. **Deterministic ID Generation** — `client_order_id` derived from intent parameters (SHA-256 of signal + timestamp slot), never random
2. **IdempotencyManager** (`core/execution/idempotency/manager.py`) — SQLite-backed dedup cache with in-flight tracking, 24h expiry
3. **IdempotencyCertifier** (`core/execution/idempotency/certifier.py`) — WAL-journal-backed certifier for crash-safe idempotency
4. **DeterministicStateMachine** (`core/execution/deterministic_state_machine.py`) — Strict state transitions prevent duplicate order placement

## Consequences
- **Positive:** Zero duplicate orders guarantee. Crash-safe recovery. Explicit retry safety classification (SAFE vs UNSAFE).
- **Negative:** In-memory cache limits scaling to single-process deployments. Distributed deployments would require Redis-backed idempotency.
- **Trade-off:** Slight latency overhead per order (SQLite write on every idempotency check) is acceptable for index-level trading (~5s intervals).

## Related
- Phase 6 (Execution Certification)
- `core/execution/idempotency/manager.py`
- `core/execution/idempotency/certifier.py`
- `core/execution/deterministic_state_machine.py`
