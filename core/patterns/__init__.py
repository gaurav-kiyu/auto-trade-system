"""Patterns — Enterprise Architecture Design Patterns (Constitution v4.0).

Provides reusable design pattern implementations for the platform:

Architecture Standards covered:
- AST-04: CQRS (Command Query Responsibility Segregation)
- AST-06: Mediator Pattern
- AST-09: Event-Driven Architecture (Event Bus)

Modules:
    patterns.mediator:
        Mediator, Command, Query, Event, CommandHandler, QueryHandler,
        EventHandler, Middleware pipeline, Result wrapper, singleton accessor.

    cqrs:
        CommandBus, QueryBus — dedicated buses with middleware, validation,
        deduplication, and optional caching.

Integration:
    integrations.event_bus_mediator:  Wires EventBus → Mediator for pub/sub
    integrations.tracing_mediator:    Wires OpenTelemetry → Mediator tracing
    integrations.cqrs_event_sourcing: Wires CQRS → Event Sourcing persistence
    di_container.wire_core:           Registers Mediator in DI container

Usage:
    # Via Mediator (recommended for new code)
    from core.patterns.mediator import (
        Mediator, Command, Query, CommandHandler, QueryHandler,
        MediatorConfig, get_mediator,
    )

    class PlaceOrder(Command[str]):
        symbol: str = ""
        quantity: int = 0

    class PlaceOrderHandler(CommandHandler[PlaceOrder, str]):
        async def handle(self, command: PlaceOrder) -> str:
            return f"Order placed: {command.symbol}"

    mediator = get_mediator()
    mediator.register_handler(PlaceOrder, PlaceOrderHandler())
    result = await mediator.send(PlaceOrder(symbol="NIFTY", quantity=50))
    print(result.value)  # "Order placed: NIFTY"

    # Via CQRS buses (for explicit command/query separation)
    from core.cqrs import CommandBus, QueryBus

    cmd_bus = CommandBus()
    qry_bus = QueryBus()

@cmd_bus.handler(PlaceOrder)
def handle_place_order(cmd):
    return {"status": "executed"}
"""

from core.cqrs import Command, CommandBus, Query, QueryBus
from core.patterns.mediator import (
    AuthMiddleware,
    CommandHandler,
    Event,
    EventHandler,
    LoggingMiddleware,
    Mediator,
    MediatorConfig,
    Middleware,
    QueryHandler,
    Result,
    RetryMiddleware,
    TimingMiddleware,
    ValidationMiddleware,
    get_mediator,
    reset_mediator,
)
from core.patterns.mediator import (
    Command as MediatorCommand,
)
from core.patterns.mediator import (
    Query as MediatorQuery,
)

__all__ = [
    # Mediator Pattern
    "AuthMiddleware",
    "CommandHandler",
    "Event",
    "EventHandler",
    "LoggingMiddleware",
    "Mediator",
    "MediatorCommand",
    "MediatorConfig",
    "MediatorQuery",
    "Middleware",
    "QueryHandler",
    "Result",
    "RetryMiddleware",
    "TimingMiddleware",
    "ValidationMiddleware",
    "get_mediator",
    "reset_mediator",
    # CQRS
    "Command",
    "CommandBus",
    "Query",
    "QueryBus",
]
