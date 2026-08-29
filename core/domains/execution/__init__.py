"""Execution Domain Models - Orders, fills, positions, execution context.

Models the execution domain:
  - Order: Trading order with type, direction, quantity
  - OrderResult: Execution result from broker
  - Fill: Individual fill/execution
  - Position: Active position tracking
  - ExecutionContext: Market context for execution decisions

Usage:
    from core.domains.execution import (
        Order, OrderResult, Fill, Position,
        OrderType, OrderStatus, PositionSide, ExecutionContext
    )
"""
from core.domains.execution.model import (
    ExecutionContext,
    Fill,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
)

__all__ = [
    "ExecutionContext",
    "Fill",
    "Order",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "Position",
    "PositionSide",
]
