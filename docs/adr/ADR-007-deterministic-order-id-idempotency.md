# ADR-007: Deterministic client_order_id Generation for Idempotency

## Status
ACCEPTED — July 2026

## Context
Idempotency requires that the same logical order always produces the same `client_order_id`. Random or sequential IDs cannot provide this guarantee. The system must generate deterministic order IDs that:
- Survive process restarts
- Produce the same ID for the same signal + time window
- Prevent duplicate order submission under any failure scenario

## Decision
`client_order_id` is generated deterministically via:
```
client_order_id = SHA-256(signal_type + index + direction + quantity + time_slot)
```
Where `time_slot` divides the trading day into 5-minute windows. This ensures:
- Same signal in same 5-minute window → same `client_order_id` → idempotency dedup
- Different signals → different `client_order_id` → no collision
- Restart produces same ID → crash-safe dedup
- Time slot expiry (next window) → new order permitted

## Consequences
- **Positive:** Guaranteed exactly-once execution. Crash-safe dedup. No random components.
- **Negative:** 5-minute time window means same signal in same window is considered duplicate (acceptable for index-level trading). Broker-side idempotency keys complement but don't replace this mechanism.
- **Trade-off:** Determinism over flexibility. If a genuine re-entry is needed within the same time window, manual override is required.

## Related
- `core/execution/deterministic_state_machine.py`
- `core/execution/idempotency/certifier.py`
- `core/execution/idempotency/manager.py`
- Constitution Rule #5 (Exactly-once execution is mandatory)
