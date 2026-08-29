# ADR 0004: Broker Abstraction with Contract Enforcement

## Status
Accepted

## Date
2026-05-16

## Context
Trading system was tightly coupled to a specific broker implementation, making it difficult to switch brokers or add new broker integrations.

## Decision
Implemented strict broker abstraction layer with:
- Abstract `BrokerAdapter` base class defining the contract
- Concrete implementations: `ZerodhaAdapter`, `AngelBrokingAdapter`, `PaperBrokerAdapter`
- Required methods: `place_order()`, `cancel_order()`, `get_order_status()`, `get_positions()`, `get_quote()`
- Conformance tests in `tests/test_broker_adapters.py`

## Consequences
- Easy broker portability (Zerodha → Fyers → Angel → Dhan → IB)
- Paper mode without real broker instantiation
- Clean separation of execution logic from broker specifics
- Easier testing with mock brokers
- Added `core/adapters/broker_adapters.py` module