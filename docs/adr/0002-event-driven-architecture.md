# ADR 0002: Event-Driven Architecture

## Status
Accepted

## Date
2026-05-16

## Context
Trading system was mostly synchronous service calls, which would become fragile as complexity grows.

## Decision
Implemented event-driven architecture with:
- Event types: SIGNAL_GENERATED, RISK_APPROVED, ORDER_SUBMITTED, BROKER_ACK_RECEIVED, FILL_RECEIVED, POSITION_UPDATED, RISK_LIMIT_BREACHED, CIRCUIT_BREAKER_TRIGGERED
- Event bus with pub/sub pattern
- Event store for persistence (event sourcing)

## Consequences
- Loose coupling between components
- Extensibility for new event types
- Replay capability via event store
- Auditability through event history
- Easier multi-strategy scaling
- Added `core/execution/event_system.py` module