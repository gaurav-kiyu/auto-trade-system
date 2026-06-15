"""
Broker Port Interface

This interface defines the contract that all broker adapter implementations
must implement. It provides a unified way to place, modify, cancel, and query
orders across any broker (Zerodha, Angel, Dhan, Groww, Fyers, Upstox, IBKR, etc.).

Architecture invariant: ALL broker API calls must go through implementations
of this interface. Never call broker SDK methods directly from core modules.

NOTE: BrokerPort dataclasses are prefixed with "Broker" to avoid naming
collisions with sibling ports (e.g. ``core.ports.execution.execution_port``
has its own ``OrderRequest`` / ``OrderResult`` which serve a different
abstraction layer).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BrokerAuthStatus(Enum):
    """Broker authentication status."""
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    ERROR = "ERROR"


class OrderType(Enum):
    """Supported order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL_M"


class OrderVariety(Enum):
    """Order variety (broker-specific)."""
    REGULAR = "REGULAR"
    CO = "CO"  # Cover order
    BO = "BO"  # Bracket order
    AMO = "AMO"  # After market order
    ICEBERG = "ICEBERG"


class ProductType(Enum):
    """Product type for order placement."""
    MIS = "MIS"  # Margin Intraday Squareoff
    NRML = "NRML"  # Normal / Delivery
    CNC = "CNC"  # Cash & Carry


class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    TRIGGER_PENDING = "TRIGGER_PENDING"
    OPEN = "OPEN"
    UNKNOWN = "UNKNOWN"


class PositionDirection(Enum):
    """Position direction."""
    LONG = "LONG"
    SHORT = "SHORT"


class Exchange(Enum):
    """Supported exchanges."""
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"  # NSE Futures & Options
    BFO = "BFO"  # BSE Futures & Options
    MCX = "MCX"
    CDS = "CDS"


@dataclass
class BrokerCredentials:
    """Broker authentication credentials."""
    broker_name: str
    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""
    user_id: str = ""
    totp_key: str = ""
    additional_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerOrderRequest:
    """Order placement request (broker-level).

    Carries broker-specific fields such as exchange, product type, and
    variety.  This is distinct from the execution-layer ``OrderRequest``
    defined in ``core.ports.execution.execution_port`` which operates at
    a higher abstraction level (signal → order mapping).
    """
    symbol: str
    exchange: Exchange
    transaction_type: str  # BUY or SELL
    quantity: int
    order_type: OrderType
    product: ProductType = ProductType.MIS
    variety: OrderVariety = OrderVariety.REGULAR
    price: float | None = None
    trigger_price: float | None = None  # For SL / SL-M orders
    validity: str = "DAY"
    tag: str = ""
    idempotency_key: str = ""
    strategy_id: str = ""
    user_order_id: str = ""
    additional_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderResult:
    """Result of an order operation."""
    broker_order_id: str
    status: OrderStatus
    filled_quantity: int = 0
    pending_quantity: int = 0
    cancelled_quantity: int = 0
    average_price: float = 0.0
    total_amount: float = 0.0
    placed_at: datetime | None = None
    filled_at: datetime | None = None
    exchange_order_id: str = ""
    reject_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    """Current position information."""
    symbol: str
    exchange: Exchange
    direction: PositionDirection
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0
    buy_quantity: int = 0
    sell_quantity: int = 0
    buy_average: float = 0.0
    sell_average: float = 0.0
    product: ProductType = ProductType.MIS
    multiplier: float = 1.0
    trade_value: float = 0.0
    lot_size: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Holding:
    """Holdings information."""
    symbol: str
    exchange: Exchange
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    realised_quantity: int = 0
    collateral_quantity: int = 0
    product: ProductType = ProductType.NRML
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trade:
    """Executed trade information."""
    trade_id: str
    order_id: str
    symbol: str
    exchange: Exchange
    transaction_type: str  # BUY or SELL
    quantity: int
    price: float
    amount: float
    trade_time: datetime
    brokerage: float = 0.0
    product: ProductType = ProductType.MIS
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Margin:
    """Account margin information."""
    total_margin: float = 0.0
    used_margin: float = 0.0
    available_margin: float = 0.0
    payin: float = 0.0
    payout: float = 0.0
    collateral: float = 0.0
    cash: float = 0.0
    exposure: float = 0.0
    additional: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerCapability:
    """Capability that a broker supports."""
    name: str
    description: str
    version: str = "1.0"


class BrokerPort(ABC):
    """
    Abstract base class for broker adapters.

    All broker implementations (Zerodha, Angel, Dhan, etc.) must inherit
    from this class and implement the required methods. This enables
    broker-independent trading with zero code changes when switching brokers.
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Return the human-readable broker name (e.g. 'zerodha', 'angel')."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> list[BrokerCapability]:
        """Return list of capabilities supported by this broker adapter."""
        ...

    # ── Authentication ──────────────────────────────────────────────────────

    @abstractmethod
    def authenticate(self, credentials: BrokerCredentials) -> BrokerAuthStatus:
        """
        Authenticate with broker and establish session.

        Args:
            credentials: Broker credentials (API key, secret, token, etc.)

        Returns:
            BrokerAuthStatus indicating connection result
        """
        ...

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Return True if the session is still valid and authenticated."""
        ...

    @abstractmethod
    def refresh_token(self, force: bool = False) -> bool:
        """
        Refresh the access token if expired.

        Args:
            force: Force refresh even if token appears valid

        Returns:
            True if refresh was successful
        """
        ...

    @abstractmethod
    def logout(self) -> bool:
        """Logout from broker session and invalidate token."""
        ...

    # ── Orders ───────────────────────────────────────────────────────────────

    @abstractmethod
    def place_order(self, order: BrokerOrderRequest) -> OrderResult:
        """
        Place an order with the broker.

        Args:
            order: Order details

        Returns:
            OrderResult with broker order ID and status
        """
        ...

    @abstractmethod
    def modify_order(
        self,
        broker_order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
        order_type: OrderType | None = None,
        validity: str | None = None,
    ) -> OrderResult:
        """
        Modify an existing order.

        Args:
            broker_order_id: Broker's order ID to modify
            quantity: New quantity
            price: New limit price
            trigger_price: New trigger price for SL orders
            order_type: New order type
            validity: New validity

        Returns:
            OrderResult with modified order details
        """
        ...

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> OrderResult:
        """
        Cancel an open or pending order.

        Args:
            broker_order_id: Broker's order ID to cancel

        Returns:
            OrderResult with cancellation status
        """
        ...

    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> OrderResult:
        """
        Get the current status of an order.

        Args:
            broker_order_id: Broker's order ID

        Returns:
            OrderResult with current status
        """
        ...

    @abstractmethod
    def get_order_history(
        self,
        *,
        symbol: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        max_results: int = 50,
    ) -> list[OrderResult]:
        """
        Get order history with optional filters.

        Args:
            symbol: Filter by symbol
            from_date: Filter from date
            to_date: Filter to date
            max_results: Maximum number of results

        Returns:
            List of OrderResult
        """
        ...

    # ── Positions ────────────────────────────────────────────────────────────

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """
        Get all current open positions.

        Returns:
            List of current positions
        """
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> Position | None:
        """
        Get position for a specific symbol.

        Args:
            symbol: Symbol to query

        Returns:
            Position if exists, None otherwise
        """
        ...

    # ── Holdings ─────────────────────────────────────────────────────────────

    @abstractmethod
    def get_holdings(self) -> list[Holding]:
        """
        Get all current holdings.

        Returns:
            List of holdings
        """
        ...

    # ── Trades ───────────────────────────────────────────────────────────────

    @abstractmethod
    def get_trades(
        self,
        *,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        max_results: int = 50,
    ) -> list[Trade]:
        """
        Get executed trades with optional date filter.

        Args:
            from_date: Filter from date
            to_date: Filter to date
            max_results: Maximum results to return

        Returns:
            List of executed trades
        """
        ...

    # ── Account ──────────────────────────────────────────────────────────────

    @abstractmethod
    def get_margin(self) -> Margin:
        """
        Get account margin details.

        Returns:
            Margin with total, used, available amounts
        """
        ...

    @abstractmethod
    def get_balance(self) -> dict[str, float]:
        """
        Get account balance summary.

        Returns:
            Dict with 'cash', 'available', 'used' keys
        """
        ...

    # ── Market Data ──────────────────────────────────────────────────────────

    @abstractmethod
    def get_ltp(self, symbol: str, exchange: Exchange) -> float:
        """
        Get last traded price for a symbol.

        Args:
            symbol: Trading symbol
            exchange: Exchange

        Returns:
            Last traded price
        """
        ...

    @abstractmethod
    def get_quote(self, symbol: str, exchange: Exchange) -> dict[str, Any]:
        """
        Get full market quote for a symbol.

        Args:
            symbol: Trading symbol
            exchange: Exchange

        Returns:
            Dict with ohlc, volume, oi, bid, ask, etc.
        """
        ...

    @abstractmethod
    def get_option_chain(
        self,
        symbol: str,
        expiry: str | None = None,
        strike: float | None = None,
        option_type: str | None = None,  # CE, PE, or None for both
    ) -> list[dict[str, Any]]:
        """
        Get option chain data for a symbol.

        Args:
            symbol: Underlying symbol (e.g. 'NIFTY', 'BANKNIFTY')
            expiry: Expiry date filter (optional)
            strike: Strike price filter (optional)
            option_type: 'CE', 'PE', or None for both

        Returns:
            List of option contracts with greeks, OI, volume, etc.
        """
        ...

    # ── Historical Data ──────────────────────────────────────────────────────

    @abstractmethod
    def get_historical_data(
        self,
        symbol: str,
        exchange: Exchange,
        interval: str,  # "1m", "5m", "15m", "1d", etc.
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict[str, Any]]:
        """
        Get historical OHLCV data.

        Args:
            symbol: Trading symbol
            exchange: Exchange
            interval: Bar interval
            from_date: Start date
            to_date: End date

        Returns:
            List of OHLCV bars with timestamp
        """
        ...

    # ── WebSocket ────────────────────────────────────────────────────────────

    @abstractmethod
    def subscribe_market_data(
        self,
        symbols: list[str],
        exchange: Exchange,
        callback: Callable[[dict[str, Any]], None],
    ) -> bool:
        """
        Subscribe to real-time market data feed.

        Args:
            symbols: List of symbols to subscribe
            exchange: Exchange for the symbols
            callback: Callback function for tick data

        Returns:
            True if subscription was successful
        """
        ...

    @abstractmethod
    def unsubscribe_market_data(
        self,
        symbols: list[str],
        exchange: Exchange,
    ) -> bool:
        """
        Unsubscribe from real-time market data feed.

        Args:
            symbols: List of symbols to unsubscribe
            exchange: Exchange for the symbols

        Returns:
            True if unsubscription was successful
        """
        ...

    # ── Health & Diagnostics ─────────────────────────────────────────────────

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the broker connection.

        Returns:
            Dict with 'status', 'latency_ms', 'auth_status', etc.
        """
        ...

    @abstractmethod
    def ping(self) -> bool:
        """
        Quick connectivity check to broker API.

        Returns:
            True if broker API is reachable and responsive
        """
        ...

    # ── Error Handling ───────────────────────────────────────────────────────

    @abstractmethod
    def handle_error(self, error: Exception, context: dict[str, Any] | None = None) -> None:
        """
        Handle broker-specific errors with retry/fallback logic.

        Args:
            error: The exception that occurred
            context: Additional context about the operation that failed
        """
        ...

    @abstractmethod
    def is_rate_limited(self) -> bool:
        """
        Check if the broker API is currently rate-limiting requests.

        Returns:
            True if requests are being rate-limited
        """
        ...
