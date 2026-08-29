"""CQRS — Command Query Responsibility Segregation (Constitution v4.0 Architecture Standard).

Provides Command/Query separation with dedicated buses, decorators, and
middleware support. Integrates with the Mediator pattern and Event Bus
for a complete CQRS+ES architecture.

Architecture Standard: CQRS
Constitution Layer: Layer 3 — Enterprise Architecture

Usage:
    from core.cqrs import CommandBus, QueryBus, Command, Query

    # Define a command
    class PlaceTradeCommand(Command):
        schema = {"symbol": str, "qty": int, "side": str}

    # Define a handler
    @command_bus.handler(PlaceTradeCommand)
    def handle_place_trade(cmd):
        return {"status": "executed", "order_id": "123"}

    # Execute
    result = command_bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
"""

from core.cqrs.command_bus import Command, CommandBus
from core.cqrs.query_bus import Query, QueryBus

__all__ = [
    "Command",
    "CommandBus",
    "Query",
    "QueryBus",
]
