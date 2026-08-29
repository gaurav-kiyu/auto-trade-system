# ADR-001: Event Store as the Single Source of Truth for Execution State

## Status
ACCEPTED — July 2026

## Context
The trading system requires an authoritative record of all execution-related events for:
- Deterministic replay after crash recovery
- Audit trail for compliance and debugging
- Exactly-once execution guarantee verification
- Broker reconciliation

## Decision
The **SQLite-backed EventStore** in `core/execution/event_system.py` is the single source of truth for execution state. All critical state transitions (signal generated → risk approved → order submitted → fill received → position updated) are persisted as immutable, hash-chained events.

## Consequences
- **Positive:** Tamper-evident audit trail via SHA-256 hash chain. Deterministic replay. Crash recovery via EventStore replay + broker reconciliation.
- **Negative:** The `core/event_sourcing.py` EventStore (JSON file-based, stream-oriented) is a secondary implementation with a different interface. Callers must choose the right one.
- **Trade-off:** Two EventStore implementations exist because the SQLite version (runtime) and JSON version (analytics/integration) serve different use cases. Long-term consolidation is desired but not blocking.

## Related
- Phase 5 (Event Store & Immutable Audit Platform)
- Constitution Rule #13 (All critical state transitions must be persisted)
- Constitution Rule #15 (Replay must be deterministic)
- **TD-02** (Certification Report): Dual EventStore implementations should be consolidated. Planned for Sprint 1.
