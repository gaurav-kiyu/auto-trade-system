"""
Execution Domain Models

This module contains the data models used in the execution domain,
including orders, fills, and positions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OrderType(Enum):
    """Types of orders."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(Enum):
    """Order status values."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PositionSide(Enum):
    """Position side values."""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class Order:
    """
    Represents a trading order.

    Attributes:
        symbol: Trading symbol
        direction: Trade direction ("BUY" or "SELL")
        quantity: Order quantity
        order_type: Type of order (market, limit, etc.)
        price: Limit price (for limit orders) or None (for market)
        strategy_id: ID of the strategy that generated this order
        risk_decision_id: ID/reason from risk decision
        timestamp: When the order was created
        order_id: Unique order ID (assigned by broker/exchange)
        client_order_id: Client-generated order ID
    """
    symbol: str
    direction: str
    quantity: int
    order_type: OrderType
    price: float | None
    strategy_id: str
    risk_decision_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    order_id: str | None = None
    client_order_id: str | None = None

    def __post_init__(self):
        """Validate order after initialization."""
        if self.direction not in ["BUY", "SELL"]:
            raise ValueError(f"Direction must be 'BUY' or 'SELL', got {self.direction}")

        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {self.quantity}")

        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("Limit orders must have a price")

        if self.order_type == OrderType.STOP_LIMIT and self.price is None:
            raise ValueError("Stop-limit orders must have a price")


@dataclass
class OrderResult:
    """
    Represents the result of order execution.

    Attributes:
        order_id: ID of the order
        status: Final status of the order
        filled_quantity: Quantity that was filled
        average_price: Average fill price
        commission: Commission paid
        timestamp: Timestamp of the result
        error_message: Error message if order failed
    """
    order_id: str
    status: OrderStatus
    filled_quantity: int
    average_price: float | None
    commission: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    error_message: str | None = None

    def __post_init__(self):
        """Validate order result after initialization."""
        if self.filled_quantity < 0:
            raise ValueError(f"Filled quantity cannot be negative, got {self.filled_quantity}")

        if self.status == OrderStatus.FILLED and self.filled_quantity == 0:
            raise ValueError("Filled order must have positive filled quantity")

        if self.average_price is not None and self.average_price <= 0:
            raise ValueError(f"Average price must be positive, got {self.average_price}")


@dataclass
class Fill:
    """
    Represents a fill (execution) of part or all of an order.

    Attributes:
        order_id: ID of the order that was filled
        fill_id: Unique fill ID
        symbol: Trading symbol
        quantity: Filled quantity
        price: Fill price
        timestamp: When the fill occurred
        commission: Commission paid on this fill
        liquidity_flag: Whether the fill added or removed liquidity
    """
    order_id: str
    fill_id: str
    symbol: str
    quantity: int
    price: float
    timestamp: datetime = field(default_factory=datetime.now)
    commission: float = 0.0
    liquidity_flag: str = "unknown"  # "added", "removed", "unknown"

    def __post_init__(self):
        """Validate fill after initialization."""
        if self.quantity <= 0:
            raise ValueError(f"Fill quantity must be positive, got {self.quantity}")

        if self.price <= 0:
            raise ValueError(f"Fill price must be positive, got {self.price}")

        if self.commission < 0:
            raise ValueError(f"Commission cannot be negative, got {self.commission}")


@dataclass
class Position:
    """
    Represents a trading position.

    Attributes:
        symbol: Trading symbol
        side: Position side (LONG, SHORT, FLAT)
        quantity: Position quantity (positive for LONG, negative for SHORT)
        average_price: Average entry price
        current_price: Current market price
        unrealized_pnl: Unrealized profit/loss
        realized_pnl: Realized profit/loss
        timestamp: Last update timestamp
    """
    symbol: str
    side: PositionSide
    quantity: int
    average_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Validate position after initialization."""
        if self.average_price <= 0:
            raise ValueError(f"Average price must be positive, got {self.average_price}")

        if self.current_price <= 0:
            raise ValueError(f"Current price must be positive, got {self.current_price}")

        # Validate quantity matches side
        if self.side == PositionSide.LONG and self.quantity <= 0:
            raise ValueError(f"LONG position must have positive quantity, got {self.quantity}")

        if self.side == PositionSide.SHORT and self.quantity >= 0:
            raise ValueError(f"SHORT position must have negative quantity, got {self.quantity}")

        if self.side == PositionSide.FLAT and self.quantity != 0:
            raise ValueError(f"FLAT position must have zero quantity, got {self.quantity}")


@dataclass
class ExecutionContext:
    """
    Context information for execution decisions.

    Attributes:
        symbol: Trading symbol
        timestamp: Execution timestamp
        market_conditions: Current market conditions
        liquidity_info: Liquidity information
        volatility: Current volatility measure
        spread: Current bid-ask spread
    """
    symbol: str
    timestamp: datetime = field(default_factory=datetime.now)
    market_conditions: dict[str, Any] = field(default_factory=dict)
    liquidity_info: dict[str, Any] = field(default_factory=dict)
    volatility: float = 0.0
    spread: float = 0.0


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

