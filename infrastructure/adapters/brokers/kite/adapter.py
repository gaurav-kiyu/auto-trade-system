"""
Kite Broker Adapter

This adapter implements the BrokerPort interface for Zerodha Kite Connect API.
It translates between the clean domain interfaces and the specific Kite API implementation.
"""

from __future__ import annotations

import time
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

# Import the broker port interface this adapter implements
from core.ports.broker import BrokerPort, Order, OrderResult, Position, Quote, Fill

# Import broker exception taxonomy - CRITICAL FIX #5
from core.execution.broker_exceptions import (
    BrokerException,
    BrokerExceptionType,
    TransientBrokerError,
    PermanentBrokerError,
    AuthExpiredError,
    RateLimitError,
    OrderRejectedError,
    NetworkError,
    BrokerTimeoutError,
    classify_broker_exception,
)

# Import Kite Connect (would be imported conditionally in real implementation)
# For this example, we'll show the structure without actual Kite dependency
try:
    from kiteconnect import KiteConnect
    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False
    # Mock KiteConnect for structure demonstration
    class KiteConnect:
        def __init__(self, api_key: str):
            self.api_key = api_key

        def set_access_token(self, access_token: str):
            self.access_token = access_token

        # Mock methods would go here


class KiteBrokerAdapter(BrokerPort):
    """
    Kite Connect broker adapter implementation.

    This adapter wraps the Kite Connect API to provide a clean interface
    that conforms to the BrokerPort contract defined in the core domain.
    """

    def __init__(self, api_key: str, access_token: str,
                 enable_rate_limit: bool = True,
                 max_retries: int = 3):
        """
        Initialize the Kite broker adapter.

        Args:
            api_key: Kite Connect API key
            access_token: Kite Connect access token
            enable_rate_limit: Whether to enable rate limiting
            max_retries: Maximum number of retry attempts for failed requests
        """
        if not KITE_AVAILABLE:
            raise ImportError("KiteConnect library not available. Install kiteconnect package.")

        self._kite = KiteConnect(api_key=api_key)
        self._kite.set_access_token(access_token)
        self._enable_rate_limit = enable_rate_limit
        self._max_retries = max_retries
        self._last_request_time = 0
        self._min_request_interval = 0.1  # 100ms between requests

        # Cache for instruments to avoid repeated API calls
        self._instruments_cache: Optional[Dict[str, Any]] = None
        self._instruments_cache_time = 0
        self._cache_ttl = 300  # 5 minutes

    def _rate_limit(self):
        """Implement rate limiting to avoid API throttling."""
        if not self._enable_rate_limit:
            return

        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _make_request_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a Kite API request with retry logic.

        Args:
            func: Kite API method to call
            *args, **kwargs: Arguments to pass to the method

        Returns:
            API response

        Raises:
            Exception: If all retry attempts fail
        """
        last_exception = None
        for attempt in range(self._max_retries):
            try:
                self._rate_limit()
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self._max_retries - 1:
                    # Exponential backoff
                    wait_time = (2 ** attempt) * 0.5
                    time.sleep(wait_time)
                else:
                    raise
        raise last_exception

    def _get_instrument_token(self, symbol: str, exchange: str = "NSE") -> Optional[int]:
        """
        Get instrument token for a symbol from Kite.

        Args:
            symbol: Trading symbol (e.g., "NIFTY23JANFUT")
            exchange: Exchange (default: NSE)

        Returns:
            Instrument token if found, None otherwise
        """
        # Check cache first
        if (self._instruments_cache is not None and
            time.time() - self._instruments_cache_time < self._cache_ttl):
            instruments = self._instruments_cache
        else:
            # Fetch instruments from Kite
            instruments_data = self._make_request_with_retry(
                self._kite.instruments, exchange
            )
            # Convert to dict for easier lookup
            instruments = {
                f"{item['tradingsymbol']}|{item['exchange']}": item['instrument_token']
                for item in instruments_data
            }
            self._instruments_cache = instruments
            self._instruments_cache_time = time.time()

        key = f"{symbol}|{exchange}"
        return instruments.get(key)

    def connect(self) -> bool:
        """
        Establish connection to the broker.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Test connection by getting profile
            profile = self._make_request_with_retry(self._kite.profile)
            return profile is not None
        except Exception:
            return False

    def disconnect(self) -> None:
        """Close connection to the broker."""
        # Kite Connect doesn't require explicit disconnection
        # HTTP sessions are managed internally
        pass

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
        try:
            # Convert symbol to instrument token
            instrument_token = self._get_instrument_token(order.symbol)
            if instrument_token is None:
                raise ValueError(f"Could not find instrument token for {order.symbol}")

            # Determine transaction type
            transaction_type = (
                self._kite.TRANSACTION_TYPE_BUY
                if order.direction == "BUY"
                else self._kite.TRANSACTION_TYPE_SELL
            )

            # Determine order type
            kite_order_type = {
                "MARKET": self._kite.ORDER_TYPE_MARKET,
                "LIMIT": self._kite.ORDER_TYPE_LIMIT,
                "SL": self._kite.ORDER_TYPE_SL,
                "SL-M": self._kite.ORDER_TYPE_SL_M
            }.get(order.order_type, self._kite.ORDER_TYPE_MARKET)

            # Place the order
            order_id = self._make_request_with_retry(
                self._kite.place_order,
                variety=self._kite.VARIETY_REGULAR,
                exchange=self._kite.EXCHANGE_NSE,  # Would need to determine from symbol
                tradingsymbol=order.symbol,
                transaction_type=transaction_type,
                quantity=order.quantity,
                product=self._kite.PRODUCT_NRML,  # Would be configurable
                order_type=kite_order_type,
                price=order.price,
                trigger_price=getattr(order, 'trigger_price', None),
                validity=self._kite.VALIDITY_DAY
            )

            return order_id

        except Exception as e:
            # CRITICAL FIX #5: Use broker-specific exception taxonomy
            classified = classify_broker_exception(e)
            if classified:
                raise classified
            # Fallback: classify based on error message
            error_msg = str(e).lower()
            if 'auth' in error_msg or 'token' in error_msg:
                raise AuthExpiredError(f"Authentication failed: {e}", original=e)
            elif 'margin' in error_msg or 'insufficient' in error_msg:
                raise PermanentBrokerError(f"Insufficient margin: {e}", original=e)
            elif 'rejected' in error_msg:
                raise OrderRejectedError(f"Order rejected: {e}", original=e)
            else:
                raise BrokerException(str(e), BrokerExceptionType.PERMANENT, False, original=e)

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an existing order.

        Args:
            order_id: ID of the order to cancel

        Returns:
            True if cancellation successful, False otherwise
        """
        try:
            self._make_request_with_retry(
                self._kite.cancel_order,
                variety=self._kite.VARIETY_REGULAR,
                order_id=order_id
            )
            return True
        except Exception:
            return False

    def modify_order(self, order_id: str,
                    quantity: Optional[int] = None,
                    price: Optional[float] = None,
                    trigger_price: Optional[float] = None) -> bool:
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
        try:
            self._make_request_with_retry(
                self._kite.modify_order,
                variety=self._kite.VARIETY_REGULAR,
                order_id=order_id,
                quantity=quantity,
                price=price,
                trigger_price=trigger_price
            )
            return True
        except Exception:
            return False

    def get_order_status(self, order_id: str) -> str:
        """
        Get the status of an order.

        Args:
            order_id: ID of the order to check

        Returns:
            Order status string
        """
        try:
            orders = self._make_request_with_retry(
                self._kite.orders
            )
            for order in orders:
                if order['order_id'] == order_id:
                    return order['status']
            return "UNKNOWN"
        except Exception:
            return "ERROR"

    def get_positions(self) -> List[Position]:
        """
        Get current positions from the broker.

        Returns:
            List of Position objects
        """
        try:
            positions_data = self._make_request_with_retry(self._kite.positions)
            positions = []

            for net_position in positions_data.get('net', []):
                # Skip zero positions
                if net_position['quantity'] == 0:
                    continue

                position = Position(
                    symbol=net_position['tradingsymbol'],
                    quantity=net_position['quantity'],
                    average_price=net_position['average_price'],
                    market_value=net_position['quantity'] * net_position['last_price'],
                    unrealized_pnl=net_position['pnl'],
                    realized_pnl=0.0,  # Would need to calculate from trade history
                    timestamp=datetime.fromtimestamp(
                        net_position['exchange_update_time'] / 1000
                    ) if 'exchange_update_time' in net_position else datetime.now()
                )
                positions.append(position)

            return positions
        except Exception as e:
            classified = classify_broker_exception(e)
            if classified:
                raise classified
            raise NetworkError(f"Failed to get positions: {e}", original=e)

    def get_quote(self, symbol: str) -> Quote:
        """
        Get current quote for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Quote object with bid, ask, last price, etc.
        """
        try:
            instrument_token = self._get_instrument_token(symbol)
            if instrument_token is None:
                raise ValueError(f"Could not find instrument token for {symbol}")

            quote_data = self._make_request_with_retry(
                self._kite.quote,
                [instrument_token]
            )

            quote_info = quote_data[str(instrument_token)]

            return Quote(
                symbol=symbol,
                bid=quote_info.get('bid', 0.0),
                ask=quote_info.get('ask', 0.0),
                last=quote_info.get('last_price', 0.0),
                volume=quote_info.get('volume', 0),
                timestamp=datetime.now()
            )
        except Exception as e:
            classified = classify_broker_exception(e)
            if classified:
                raise classified
            raise BrokerTimeoutError(f"Failed to get quote for {symbol}: {e}", original=e)

    def subscribe_to_market_data(self, symbols: List[str],
                               callback: Callable[[Quote], None]) -> bool:
        """
        Subscribe to real-time market data for symbols.

        Note: Kite Connect does not provide direct WebSocket market data
        in the standard Python client. This would require using Kite Ticker
        (websocket client) separately.

        Args:
            symbols: List of symbols to subscribe to
            callback: Function to call when market data arrives

        Returns:
            True if subscription setup successful, False otherwise
        """
        # This would require implementing Kite Ticker separately
        # For now, return False to indicate not implemented in this adapter
        # A full implementation would:
        # 1. Initialize KiteTicker with API key and access token
        # 2. Set up tick callback to convert ticks to Quote objects
        # 3. Subscribe to the instrument tokens for the symbols
        # 4. Start the ticker connection
        return False

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        """
        Unsubscribe from market data for a symbol.

        Args:
            symbol: Symbol to unsubscribe from

        Returns:
            True if unsubscription successful, False otherwise
        """
        # Would need to implement with Kite Ticker
        return False

    def get_historical_data(self, symbol: str,
                          from_date: datetime,
                          to_date: datetime,
                          interval: str = "day") -> List[Dict[str, Any]]:
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
        try:
            instrument_token = self._get_instrument_token(symbol)
            if instrument_token is None:
                raise ValueError(f"Could not find instrument token for {symbol}")

            # Convert interval to Kite format
            kite_interval = {
                "minute": self._kite.INTERVAL_MINUTE,
                "3minute": self._kite.INTERVAL_3MINUTE,
                "5minute": self._kite.INTERVAL_5MINUTE,
                "15minute": self._kite.INTERVAL_15MINUTE,
                "30minute": self._kite.INTERVAL_30MINUTE,
                "60minute": self._kite.INTERVAL_60MINUTE,
                "day": self._kite.INTERVAL_DAY
            }.get(interval, self._kite.INTERVAL_DAY)

            historical_data = self._make_request_with_retry(
                self._kite.historical_data,
                instrument_token,
                from_date,
                to_date,
                kite_interval
            )

            return historical_data

        except Exception as e:
            classified = classify_broker_exception(e)
            if classified:
                raise classified
            raise BrokerTimeoutError(f"Failed to get historical data for {symbol}: {e}", original=e)


# Factory function for creating Kite broker adapter instances
def create_kite_broker_adapter(config: Dict[str, Any]) -> KiteBrokerAdapter:
    """
    Factory function to create a KiteBrokerAdapter from configuration.

    Args:
        config: Configuration dictionary containing:
                - api_key: Kite Connect API key
                - access_token: Kite Connect access token
                - enable_rate_limit: Whether to enable rate limiting (optional, default True)
                - max_retries: Maximum retry attempts (optional, default 3)

    Returns:
        Configured KiteBrokerAdapter instance
    """
    return KiteBrokerAdapter(
        api_key=config['api_key'],
        access_token=config['access_token'],
        enable_rate_limit=config.get('enable_rate_limit', True),
        max_retries=config.get('max_retries', 3)
    )