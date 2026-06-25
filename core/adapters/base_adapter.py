from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


__all__ = [
    "BrokerAdapter",
    "OrderRequest",
    "OrderResponse",
    "OrderStatus",
]

class OrderStatus(Enum):
    """Explicit execution states - never collapse ambiguity.

    UNKNOWN: "do not retry automatically" - requires manual intervention.
    PENDING: Order not yet submitted to broker.
    """
    NEW = auto()
    PENDING = auto()
    VALIDATED = auto()
    SUBMITTED = auto()
    ACKNOWLEDGED = auto()
    PARTIAL_FILL = auto()
    FILLED = auto()
    CANCEL_PENDING = auto()
    CANCELLED = auto()
    REJECTED = auto()
    FAILED = auto()
    UNKNOWN = auto()
    RECONCILING = auto()

@dataclass
class OrderRequest:
    symbol: str
    qty: int
    price: float
    order_type: str  # MARKET, LIMIT, SL, SLM
    direction: str  # BUY, SELL
    product: str    # MIS, CNC, NRML
    variety: str    # REGULAR, AMO, etc.
    tag: str = "OPB_BOT"
    idempotency_key: str = ""  # Broker-side idempotency key for duplicate prevention

@dataclass
class OrderResponse:
    order_id: str
    status: OrderStatus
    filled_qty: int = 0
    avg_price: float = 0.0
    error: str | None = None
    raw_response: Any = None

class BrokerAdapter(ABC):
    """
    Strict Abstract Base Class for all Broker Adapters.
    Any new broker must implement these methods to be compatible with the system.
    """

    @abstractmethod
    def authenticate(self, credentials: dict[str, Any]) -> bool:
        """Establish session with the broker."""
        pass

    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResponse:
        """Submit an order to the exchange."""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> OrderResponse:
        """Cancel an existing order."""
        pass

    @abstractmethod
    def get_ltp(self, symbol: str) -> float:
        """Fetch Last Traded Price for a symbol."""
        pass

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]:
        """Fetch all current open positions."""
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderResponse:
        """Fetch the current status of a specific order."""
        pass

    @abstractmethod
    def get_instrument_token(self, symbol: str) -> str:
        """Resolve a trading symbol to a broker-specific token."""
        pass

    @abstractmethod
    def is_healthy(self) -> bool:
        """Perform a health check on the broker connection."""
        pass
