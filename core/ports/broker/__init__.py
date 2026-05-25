"""
Broker Ports Package
"""
from __future__ import annotations

"""
Broker Port Interface

This interface defines the contract that all broker adapters must implement.
It decouples the trading logic from specific broker implementations.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from core.common.kernels.models import Fill as SharedFill

# Import shared models from shared kernels
from core.common.kernels.models import Order as SharedOrder
from core.common.kernels.models import OrderResult as SharedOrderResult
from core.common.kernels.models import Position as SharedPosition
from core.common.kernels.models import Quote as SharedQuote
from core.datetime_ist import now_ist

# Use shared models from shared kernels
Order = SharedOrder
OrderRequest = SharedOrder
OrderResult = SharedOrderResult
Position = SharedPosition
Quote = SharedQuote
Fill = SharedFill

class OrderStatus(Enum):
    """Standardized order statuses."""
    SUBMITTED = "SUBMITTED"
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"
    EXPIRED = "EXPIRED"


class OrderResult:
    """Result of order execution."""

    def __init__(
        self,
        order_id: str,
        status: str,  # OPEN, FILLED, PARTIALLY_FILLED, CANCELLED, REJECTED, ERROR
        filled_quantity: int = 0,
        average_price: float = 0.0,
        commission: float = 0.0,
        timestamp: datetime | None = None,
        reject_reason: str | None = None
    ):
        self.order_id = order_id
        self.status = status
        self.filled_quantity = filled_quantity
        self.average_price = average_price
        self.commission = commission
        self.timestamp = timestamp or now_ist()
        self.reject_reason = reject_reason


class Position:
    """Trading position."""

    def __init__(
        self,
        symbol: str,
        quantity: int,  # Positive for long, negative for short
        average_price: float,
        market_value: float,
        unrealized_pnl: float,
        realized_pnl: float,
        timestamp: datetime | None = None
    ):
        self.symbol = symbol
        self.quantity = quantity
        self.average_price = average_price
        self.market_value = market_value
        self.unrealized_pnl = unrealized_pnl
        self.realized_pnl = realized_pnl
        self.timestamp = timestamp or now_ist()


_log_quote = logging.getLogger(__name__)


class Quote:
    """Market quote with bid ≤ ask enforcement.

    Raises ValueError if bid > ask or bid/ask is NaN/inf — corrupted ticks
    are rejected at the adapter boundary and cannot propagate through the system.
    """

    def __init__(
        self,
        symbol: str,
        bid: float,
        ask: float,
        last: float,
        volume: int,
        timestamp: datetime | None = None
    ):
        # Reject quotes with NaN or inf prices
        _bid_valid = isinstance(bid, (int, float)) and not (bid != bid or bid in (float('inf'), float('-inf')))
        _ask_valid = isinstance(ask, (int, float)) and not (ask != ask or ask in (float('inf'), float('-inf')))
        if not _bid_valid or not _ask_valid:
            raise ValueError(
                f"Invalid bid/ask for {symbol}: bid={bid!r}, ask={ask!r} "
                f"(NaN or Inf detected and rejected at adapter boundary)"
            )
        if bid > ask:
            raise ValueError(
                f"Inverted market detected for {symbol}: bid={bid} > ask={ask}. "
                f"Corrupted tick rejected at adapter boundary."
            )
        self.symbol = symbol
        self.bid = bid
        self.ask = ask
        self.last = last
        self.volume = volume
        self.timestamp = timestamp or now_ist()


class Fill:
    """Order fill/execution."""

    def __init__(
        self,
        order_id: str,
        symbol: str,
        quantity: int,
        price: float,
        timestamp: datetime | None = None,
        commission: float = 0.0
    ):
        self.order_id = order_id
        self.symbol = symbol
        self.quantity = quantity
        self.price = price
        self.timestamp = timestamp or now_ist()
        self.commission = commission


class BrokerPort(ABC):
    """
    Abstract base class defining the broker interface.

    All broker adapters (Kite, Angel, Paper, etc.) must implement this interface.
    This enables the trading logic to remain broker-agnostic.
    """

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to the broker.

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to the broker."""
        pass

    @abstractmethod
    def place_order(self, order: Order) -> str:
        """
        Place an order with the broker.

        Args:
            order: Order object containing order details

        Returns:
            Order ID from the broker

        Raises:
            Exception: If order placement fails
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an existing order.

        Args:
            order_id: ID of the order to cancel

        Returns:
            True if cancellation successful, False otherwise
        """
        pass

    @abstractmethod
    def modify_order(
        self,
        order_id: str,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None
    ) -> bool:
        """
        Modify an existing order.

        Args:
            order_id: ID of the order to modify
            quantity: New quantity (optional)
            price: New price (optional)
            trigger_price: New trigger price (optional)

        Returns:
            True if modification successful, False otherwise
        """
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> str:
        """
        Get the status of an order.

        Args:
            order_id: ID of the order to check

        Returns:
            Order status string
        """
        pass

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """
        Get current positions from the broker.

        Returns:
            List of Position objects
        """
        pass

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        """
        Get current quote for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Quote object with bid, ask, last price, etc.
        """
        pass

    @abstractmethod
    def subscribe_to_market_data(
        self,
        symbols: list[str],
        callback: Callable[[Quote], None]
    ) -> bool:
        """
        Subscribe to real-time market data for symbols.

        Args:
            symbols: List of symbols to subscribe to
            callback: Function to call when market data arrives

        Returns:
            True if subscription setup successful, False otherwise
        """
        pass

    @abstractmethod
    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        """
        Unsubscribe from market data for a symbol.

        Args:
            symbol: Symbol to unsubscribe from

        Returns:
            True if unsubscription successful, False otherwise
        """
        pass

    @abstractmethod
    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day"
    ) -> list[dict[str, Any]]:
        """
        Get historical market data for backtesting and analysis.

        Args:
            symbol: Trading symbol
            from_date: Start date for historical data
            to_date: End date for historical data
            interval: Data interval (minute, 3minute, 5minute, 15minute, 30minute, 60minute, day)

        Returns:
            List of historical data candles
        """
        pass

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check of the broker connection.

        Returns:
            A dictionary with health status information. Expected keys:
            - status: str (e.g., "healthy", "unhealthy")
            - Optional: error, latency, etc.
        """
        pass


# Example implementation showing how existing code would be adapted
class BrokerAdapterFactory:
    """Factory for creating broker adapter instances."""

    @staticmethod
    def create_broker_adapter(broker_type: str, config: dict[str, Any]) -> BrokerPort:
        """
        Create a broker adapter instance based on type.

        Args:
            broker_type: Type of broker ("KITE", "ANGEL", "PAPER")
            config: Configuration dictionary for the broker

        Returns:
            BrokerPort implementation

        Raises:
            ValueError: If broker_type is not supported
        """
        if broker_type.upper() == "KITE":
            # In practice, this would import and return KiteBrokerAdapter
            # For now, we'll return a placeholder
            raise NotImplementedError("Kite broker adapter implementation needed")
        elif broker_type.upper() == "ANGEL":
            # In practice, this would import and return AngelBrokerAdapter
            raise NotImplementedError("Angel broker adapter implementation needed")
        elif broker_type.upper() == "PAPER":
            # In practice, this would import and return PaperBrokerAdapter
            raise NotImplementedError("Paper broker adapter implementation needed")
        else:
            raise ValueError(f"Unsupported broker type: {broker_type}")


if __name__ == "__main__":
    # This file defines the interface - no runtime execution needed
    print("BrokerPort interface defined successfully")
    print("Implementations should be created in infrastructure/adapters/brokers/")


from .health_port import BrokerHealthPort

__all__ = ["BrokerPort", "BrokerHealthPort"]
