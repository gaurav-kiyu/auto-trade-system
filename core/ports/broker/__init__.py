"""
Broker Ports Package

Canonical broker port interface and types.

The canonical ``BrokerPort`` ABC (rich 25‑method interface with dataclass
types) lives in ``broker_port.py`` and is re‑exported here.

Legacy backward‑compatible types (from the original streamlined 10‑method
interface) are available as ``LegacyBrokerPort``, ``LegacyOrderResult``,
``LegacyPosition``, ``LegacyQuote``, ``LegacyFill``, ``LegacyOrderStatus``,
and the shared kernel re‑exports ``Order`` / ``OrderRequest`` / ``Fill``
(from ``core.common.kernels.models``).

New code should use the canonical types (``BrokerPort``, ``OrderResult``,
``Position``, ``OrderStatus``, ``Exchange``, …) from ``broker_port.py``.
"""

from __future__ import annotations


from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any

# ── Canonical types from broker_port.py (the canonical interface) ────────────

from core.ports.broker.broker_port import BrokerPort as BrokerPort
from core.ports.broker.broker_port import (
    BrokerAuthStatus,
    BrokerCapability,
    BrokerCredentials,
    BrokerOrderRequest,
    Exchange,
    Holding,
    Margin,
    OrderResult,
    OrderStatus,
    OrderType,
    OrderVariety,
    Position,
    PositionDirection,
    ProductType,
    Trade,
)

# ── Shared kernel models (used by legacy broker adapters) ────────────────────

from core.common.kernels.models import Fill as SharedFill
from core.common.kernels.models import Order as SharedOrder

from core.common.kernels.models import Position as SharedPosition
from core.common.kernels.models import Quote as SharedQuote

from core.datetime_ist import now_ist

# ── Legacy backward‑compatible aliases ───────────────────────────────────────

# Shared kernel models (used by PaperBrokerAdapter, KiteBrokerAdapter, MarketDataPort)
Order = SharedOrder
OrderRequest = SharedOrder
Fill = SharedFill
Quote = SharedQuote

# Legacy model classes (redefined inline to match the original __init__.py)

LegacyOrderStatus = Enum(
    "LegacyOrderStatus",
    {
        "SUBMITTED": "SUBMITTED",
        "PENDING": "PENDING",
        "FILLED": "FILLED",
        "PARTIALLY_FILLED": "PARTIALLY_FILLED",
        "CANCELLED": "CANCELLED",
        "REJECTED": "REJECTED",
        "ERROR": "ERROR",
        "EXPIRED": "EXPIRED",
    },
    type=str,
)


class LegacyOrderResult:
    """Legacy order result (backward compat — simple attribute class)."""
    def __init__(
        self,
        order_id: str,
        status: str,
        filled_quantity: int = 0,
        average_price: float = 0.0,
        commission: float = 0.0,
        timestamp: datetime | None = None,
        reject_reason: str | None = None,
    ):
        self.order_id = order_id
        self.status = status
        self.filled_quantity = filled_quantity
        self.average_price = average_price
        self.commission = commission
        self.timestamp = timestamp or now_ist()
        self.reject_reason = reject_reason


class LegacyPosition:
    """Legacy trading position (backward compat)."""
    def __init__(
        self,
        symbol: str,
        quantity: int,
        average_price: float,
        market_value: float,
        unrealized_pnl: float,
        realized_pnl: float,
        timestamp: datetime | None = None,
    ):
        self.symbol = symbol
        self.quantity = quantity
        self.average_price = average_price
        self.market_value = market_value
        self.unrealized_pnl = unrealized_pnl
        self.realized_pnl = realized_pnl
        self.timestamp = timestamp or now_ist()


class LegacyQuote:
    """Legacy market quote with bid ≤ ask enforcement (backward compat)."""
    def __init__(
        self,
        symbol: str,
        bid: float,
        ask: float,
        last: float,
        volume: int,
        timestamp: datetime | None = None,
    ):
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


class LegacyFill:
    """Legacy order fill / execution (backward compat)."""
    def __init__(
        self,
        order_id: str,
        symbol: str,
        quantity: int,
        price: float,
        timestamp: datetime | None = None,
        commission: float = 0.0,
    ):
        self.order_id = order_id
        self.symbol = symbol
        self.quantity = quantity
        self.price = price
        self.timestamp = timestamp or now_ist()
        self.commission = commission


class LegacyBrokerPort(ABC):
    """
    Legacy broker port interface (backward compat — 10‑method streamlined ABC).

    .. deprecated::
       New broker adapters should implement ``BrokerPort`` from
       ``core.ports.broker.broker_port`` (the canonical 25‑method interface
       with rich dataclass types).
    """

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def place_order(self, order: SharedOrder) -> str: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    def modify_order(
        self,
        order_id: str,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> bool: ...

    @abstractmethod
    def get_order_status(self, order_id: str) -> str: ...

    @abstractmethod
    def get_positions(self) -> list[SharedPosition]: ...

    @abstractmethod
    def get_quote(self, symbol: str) -> SharedQuote: ...

    @abstractmethod
    def subscribe_to_market_data(
        self,
        symbols: list[str],
        callback: Callable[[SharedQuote], None],
    ) -> bool: ...

    @abstractmethod
    def unsubscribe_from_market_data(self, symbol: str) -> bool: ...

    @abstractmethod
    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def health_check(self) -> dict[str, Any]: ...


class BrokerAdapterFactory:
    """Factory for creating broker adapter instances (legacy)."""
    @staticmethod
    def create_broker_adapter(broker_type: str, config: dict[str, Any]) -> LegacyBrokerPort:
        """Create a legacy broker adapter (deprecated — use create_broker_adapter() in broker_adapters.py)."""
        raise NotImplementedError(f"Broker adapter for {broker_type} must be created via broker_adapters.py")


# ── Health port ───────────────────────────────────────────────────────────────

from core.ports.broker.health_port import BrokerHealthPort


__all__ = [
    # Canonical types (from broker_port.py)
    "BrokerAuthStatus", "BrokerCapability", "BrokerCredentials",
    "BrokerOrderRequest", "BrokerPort",
    "Exchange", "Holding", "Margin",
    "OrderResult", "OrderStatus", "OrderType", "OrderVariety",
    "Position", "PositionDirection", "ProductType", "Trade",
    # Health
    "BrokerHealthPort",
    # Legacy backward-compat types
    "BrokerAdapterFactory",
    "Fill", "LegacyBrokerPort", "LegacyFill", "LegacyOrderResult",
    "LegacyOrderStatus", "LegacyPosition", "LegacyQuote",
    "Order", "OrderRequest", "Quote",
]
