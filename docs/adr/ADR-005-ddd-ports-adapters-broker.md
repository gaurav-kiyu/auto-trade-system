# ADR-005: DDD with Ports/Adapters for Broker Independence

## Status
ACCEPTED — July 2026

## Context
The system must support multiple Indian brokers (Zerodha Kite, Angel One) with the ability to add new brokers without modifying core trading logic. Broker APIs differ significantly in authentication, order placement, and data formats.

## Decision
All broker interactions go through a **ports/adapters architecture**:
- **`core/ports/broker/`** — Abstract `BrokerPort` interface defining the broker contract (place_order, cancel_order, get_positions, get_orders, get_ltp)
- **`infrastructure/adapters/brokers/kite/`** — Kite adapter implementing `BrokerPort`
- **`core/adapters/broker_adapters.py`** — PaperBrokerAdapter and GenericBrokerAdapter
- **`core/ports/broker/health_port.py`** — Separate health monitoring port
- **`infrastructure/adapters/brokers/kite/adapter.py`** — Kite-specific implementation with retry, rate limiting, token management

## Consequences
- **Positive:** New brokers can be added by implementing `BrokerPort`. Core trading logic is broker-agnostic. Paper mode uses the same interface. Smart router enables multi-broker execution.
- **Negative:** Adapter abstraction adds complexity for simple operations. Some broker-specific features (e.g., Kite WebSocket tick-level data) require bypassing the abstraction.
- **Trade-off:** Abstraction overhead is worthwhile for institutional multi-broker support.

## Related
- `core/ports/broker/broker_port.py`
- `infrastructure/adapters/brokers/kite/adapter.py`
- `core/adapters/broker_adapters.py`
- `core/execution/smart_router.py`
