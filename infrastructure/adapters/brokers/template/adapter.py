"""
Template Broker Adapter

This is a template/pattern implementation showing how to create a broker adapter
that conforms to the BrokerPort interface. This template is NOT tied to any
specific broker's API (like Kite or Angel) - it shows the pattern that should
be followed when implementing an adapter for ANY broker.

To use this template:
1. Copy this directory to a new broker-specific directory (e.g., "mybroker")
2. Rename the file to match your broker (e.g., mybroker_adapter.py)
3. Replace all TODO comments with your broker's specific API implementation
4. Update the broker factory to recognize your new broker type
5. Configure your broker type in the configuration

The adapter implements the BrokerPort interface defined in core/ports/broker.py
"""

from __future__ import annotations

import time
import logging
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

# Import the broker port interface this adapter implements
# WARNING: Do NOT modify this import - it's the contract we must follow
from core.ports.broker import BrokerPort, Order, OrderResult, Position, Quote, Fill

# Import shared exceptions for consistent error handling
from core.common.exceptions import BrokerError, ConfigurationError

logger = logging.getLogger(__name__)


class TemplateBrokerAdapter(BrokerPort):
    """
    Template broker adapter showing the pattern for implementing BrokerPort.

    This class demonstrates HOW to implement a broker adapter, but contains
    no actual broker-specific code. All methods contain TODO comments indicating
    where broker-specific implementation should be added.

    To create a real broker adapter:
    1. Copy this file to your broker's directory
    2. Replace all TODO sections with your broker's API implementation
    3. Add any broker-specific imports at the top
    4. Implement proper authentication and error handling
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the broker adapter with configuration.

        Args:
            config: Configuration dictionary containing broker-specific settings
                   such as API keys, endpoints, timeouts, etc.

        The config should contain all necessary information to connect to
        and authenticate with your broker's API.
        """
        # Store configuration for later use
        self.config = config

        # Initialize connection state
        self._is_connected = False
        self._last_request_time = 0
        self._request_count = 0

        # TODO: Initialize broker-specific client/session objects here
        # Example for a REST API broker:
        # self._api_client = None  # Will be initialized in connect()
        #
        # TODO: Extract configuration values
        # self._api_key = config.get('api_key')
        # self._api_secret = config.get('api_secret')
        # self._base_url = config.get('base_url', 'https://api.example.com')
        # self._timeout = config.get('timeout', 30)
        #
        # TODO: Set up rate limiting if needed
        # self._rate_limit_per_second = config.get('rate_limit', 5)
        # self._min_request_interval = 1.0 / self._rate_limit_per_second if self._rate_limit_per_second > 0 else 0

        logger.info(f"TemplateBrokerAdapter initialized with config keys: {list(config.keys())}")

    def _enforce_rate_limit(self) -> None:
        """
        Enforce rate limiting to avoid overwhelming the broker's API.

        This is a template implementation - customize based on your broker's
        specific rate limiting policies.
        """
        # TODO: Implement rate limiting based on your broker's specifications
        # Example implementation:
        # if self._min_request_interval > 0:
        #     elapsed = time.time() - self._last_request_time
        #     if elapsed < self._min_request_interval:
        #         time.sleep(self._min_request_interval - elapsed)
        #     self._last_request_time = time.time()
        pass

    def _make_api_call(self, method: Callable, *args, **kwargs) -> Any:
        """
        Make an API call with proper error handling and logging.

        This is a template for wrapping broker API calls with consistent
        error handling, logging, and retry logic.

        Args:
            method: The API method to call
            *args, **kwargs: Arguments to pass to the API method

        Returns:
            The API response

        Raises:
            BrokerError: If the API call fails after retries
        """
        # TODO: Implement API call wrapping with:
        # - Rate limiting (call _enforce_rate_limit())
        # - Error handling and logging
        # - Retry logic with exponential backoff
        # - Request/response logging for debugging
        #
        # Example structure:
        # self._enforce_rate_limit()
        # try:
        #     logger.debug(f"Making API call: {method.__name__}")
        #     result = method(*args, **kwargs)
        #     logger.debug(f"API call successful: {method.__name__}")
        #     return result
        # except Exception as e:
        #     logger.error(f"API call failed: {method.__name__} - {str(e)}")
        #     raise BrokerError(f"Broker API error: {str(e)}") from e
        return method(*args, **kwargs)

    def connect(self) -> bool:
        """
        Establish connection to the broker.

        This method should:
        1. Authenticate with the broker's API
        2. Test the connection (e.g., get account info)
        3. Set up any necessary subscriptions or listeners
        4. Update internal state to reflect connection status

        Returns:
            True if connection successful

        Raises:
            BrokerError: If connection fails
        """
        # TODO: Implement broker-specific connection logic
        # Example steps:
        # 1. Initialize API client with credentials
        # 2. Authenticate (if required)
        # 3. Test connection by calling a simple API endpoint
        # 4. Set up websocket connections for real-time data if needed
        # 5. Update self._is_connected = True on success
        #
        # Example structure:
        # try:
        #     logger.info("Connecting to broker...")
        #     # Initialize client
        #     self._api_client = SomeBrokerAPI(
        #         api_key=self.config.get('api_key'),
        #         api_secret=self.config.get('api_secret'),
        #         # ... other params
        #     )
        #
        #     # Authenticate if needed
        #     # self._api_client.authenticate()
        #
        #     # Test connection
        #     # account_info = self._make_api_call(self._api_client.get_account_info)
        #     # logger.info(f"Connected to broker. Account: {account_info.get('id')}")
        #
        #     self._is_connected = True
        #     return True
        # except Exception as e:
        #     logger.error(f"Failed to connect to broker: {str(e)}")
        #     self._is_connected = False
        #     raise BrokerError(f"Connection failed: {str(e)}") from e

        # For now, return False to indicate this is a template
        logger.warning("connect() called on TemplateBrokerAdapter - this is a template implementation")
        return False

    def disconnect(self) -> None:
        """Close connection to the broker and clean up resources."""
        # TODO: Implement disconnection logic
        # Example:
        # 1. Close websocket connections
        # 2. Invalidate API tokens/sessions
        # 3. Clean up resources
        # 4. Update self._is_connected = False
        #
        # Example structure:
        # try:
        #     logger.info("Disconnecting from broker...")
        #     # Close websocket connections
        #     # if hasattr(self, '_ws_client'):
        #     #     self._ws_client.close()
        #
        #     # Invalidate sessions
        #     # self._api_client = None
        #
        #     self._is_connected = False
        #     logger.info("Disconnected from broker")
        # except Exception as e:
        #     logger.error(f"Error during disconnection: {str(e)}")
        # finally:
        #     self._is_connected = False

        self._is_connected = False
        logger.info("disconnect() called on TemplateBrokerAdapter")

    def place_order(self, order: Order) -> str:
        """
        Place an order with the broker.

        Args:
            order: Order object containing order details

        Returns:
            Order ID from the broker

        Raises:
            BrokerError: If order placement fails
        """
        # TODO: Implement order placement logic
        # Example steps:
        # 1. Validate the order object
        # 2. Map internal order format to broker's API format
        # 3. Call broker's place_order API
        # 4. Extract and return the order ID from the response
        #
        # Example structure:
        # try:
        #     logger.info(f"Placing order: {order.symbol} {order.direction} {order.quantity}")
        #
        #     # Validate order
        #     if not order.symbol or order.quantity <= 0:
        #         raise ValueError("Invalid order parameters")
        #
        #     # Convert to broker-specific format
        #     broker_order = {
        #         'symbol': self._convert_symbol(order.symbol),
        #         'side': 'BUY' if order.direction == 'BUY' else 'SELL',
        #         'quantity': order.quantity,
        #         'order_type': self._map_order_type(order.order_type),
        #         # ... other fields
        #     }
        #
        #     # Add price if limit order
        #     if order.order_type in ['LIMIT', 'SL'] and order.price is not None:
        #         broker_order['price'] = order.price
        #
        #     # Make API call
        #     response = self._make_api_call(
        #         self._api_client.place_order,
        #         **broker_order
        #     )
        #
        #     # Extract order ID
        #     order_id = response.get('order_id')  # Adjust based on broker's response format
        #     if not order_id:
        #         raise BrokerError("No order ID returned from broker")
        #
        #     logger.info(f"Order placed successfully: {order_id}")
        #     return order_id
        # except Exception as e:
        #     logger.error(f"Failed to place order: {str(e)}")
        #     raise BrokerError(f"Order placement failed: {str(e)}") from e

        # For now, raise an error to indicate this is not implemented
        raise BrokerError("place_order() not implemented in TemplateBrokerAdapter - this is a template")

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an existing order.

        Args:
            order_id: ID of the order to cancel

        Returns:
            True if cancellation successful, False otherwise
        """
        # TODO: Implement order cancellation logic
        # Example:
        # 1. Call broker's cancel_order API with order_id
        # 2. Return True if successful, False otherwise
        #
        # Example structure:
        # try:
        #     logger.info(f"Cancelling order: {order_id}")
        #     self._make_api_call(self._api_client.cancel_order, order_id=order_id)
        #     logger.info(f"Order cancelled: {order_id}")
        #     return True
        # except Exception as e:
        #     logger.error(f"Failed to cancel order {order_id}: {str(e)}")
        #     return False

        logger.warning(f"cancel_order() called on TemplateBrokerAdapter for order {order_id} - not implemented")
        return False

    def modify_order(
        self,
        order_id: str,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None
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
        # TODO: Implement order modification logic
        # Example:
        # 1. Build modification request with provided parameters
        # 2. Call broker's modify_order API
        # 3. Return True if successful
        #
        # Example structure:
        # try:
        #     logger.info(f"Modifying order {order_id}: quantity={quantity}, price={price}")
        #     # Build modification dict
        #     modification = {}
        #     if quantity is not None:
        #         modification['quantity'] = quantity
        #     if price is not None:
        #         modification['price'] = price
        #     if trigger_price is not None:
        #         modification['trigger_price'] = trigger_price
        #
        #     if modification:
        #         self._make_api_call(
        #             self._api_client.modify_order,
        #             order_id=order_id,
        #             **modification
        #         )
        #         logger.info(f"Order modified: {order_id}")
        #         return True
        #     else:
        #         logger.warning(f"No modifications provided for order {order_id}")
        #         return False
        # except Exception as e:
        #     logger.error(f"Failed to modify order {order_id}: {str(e)}")
        #     return False

        logger.warning(f"modify_order() called on TemplateBrokerAdapter for order {order_id} - not implemented")
        return False

    def get_order_status(self, order_id: str) -> str:
        """
        Get the status of an order.

        Args:
            order_id: ID of the order to check

        Returns:
            Order status string (should match common values: OPEN, FILLED, CANCELLED, REJECTED, etc.)
        """
        # TODO: Implement order status retrieval logic
        # Example:
        # 1. Call broker's get_order_status API
        # 2. Map broker-specific status to common status values
        # 3. Return the status string
        #
        # Example structure:
        # try:
        #     logger.debug(f"Getting status for order: {order_id}")
        #     response = self._make_api_call(
        #         self._api_client.get_order_status,
        #         order_id=order_id
        #     )
        #
        #     # Map broker status to common status
        #     broker_status = response.get('status', '').upper()
        #     status_map = {
        #         # Add your broker's status mappings here
        #         'OPEN': 'OPEN',
        #         'FILLED': 'FILLED',
        #         'CANCELLED': 'CANCELLED',
        #         'REJECTED': 'REJECTED',
        #         # ... add more as needed
        #     }
        #     status = status_map.get(broker_status, 'UNKNOWN')
        #
        #     logger.debug(f"Order {order_id} status: {status}")
        #     return status
        # except Exception as e:
        #     logger.error(f"Failed to get order status {order_id}: {str(e)}")
        #     return 'ERROR'

        logger.warning(f"get_order_status() called on TemplateBrokerAdapter for order {order_id} - not implemented")
        return 'UNKNOWN'

    def get_positions(self) -> List[Position]:
        """
        Get current positions from the broker.

        Returns:
            List of Position objects representing current holdings
        """
        # TODO: Implement position retrieval logic
        # Example:
        # 1. Call broker's get_positions API
        # 2. Convert each position to Position object
        # 3. Return list of Position objects
        #
        # Example structure:
        # try:
        #     logger.debug("Getting current positions")
        #     positions_data = self._make_api_call(self._api_client.get_positions)
        #
        #     positions = []
        #     for pos_data in positions_data:
        #         # Skip zero positions
        #         if pos_data.get('quantity', 0) == 0:
        #             continue
        #
        #         # Convert to Position object
        #         position = Position(
        #             symbol=self._convert_symbol_from_broker(pos_data.get('symbol')),
        #             quantity=int(pos_data.get('quantity', 0)),
        #             average_price=float(pos_data.get('average_price', 0.0)),
        #             market_value=float(pos_data.get('market_value', 0.0)),
        #             unrealized_pnl=float(pos_data.get('unrealized_pnl', 0.0)),
        #             realized_pnl=float(pos_data.get('realized_pnl', 0.0)),
        #             timestamp=datetime.fromtimestamp(
        #                 pos_data.get('timestamp', time.time())
        #             ) if pos_data.get('timestamp') else datetime.now()
        #         )
        #         positions.append(position)
        #
        #     logger.debug(f"Retrieved {len(positions)} positions")
        #     return positions
        # except Exception as e:
        #     logger.error(f"Failed to get positions: {str(e)}")
        #     return []

        logger.warning("get_positions() called on TemplateBrokerAdapter - not implemented")
        return []

    def get_quote(self, symbol: str) -> Quote:
        """
        Get current quote for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Quote object with bid, ask, last price, etc.
        """
        # TODO: Implement quote retrieval logic
        # Example:
        # 1. Call broker's get_quote API for the symbol
        # 2. Extract bid, ask, last price, volume
        # 3. Return Quote object
        #
        # Example structure:
        # try:
        #     logger.debug(f"Getting quote for: {symbol}")
        #     quote_data = self._make_api_call(
        #         self._api_client.get_quote,
        #         symbol=self._convert_symbol(symbol)
        #     )
        #
        #     quote = Quote(
        #         symbol=symbol,
        #         bid=float(quote_data.get('bid', 0.0)),
        #         ask=float(quote_data.get('ask', 0.0)),
        #         last=float(quote_data.get('last', 0.0)),
        #         volume=int(quote_data.get('volume', 0)),
        #         timestamp=datetime.now()
        #     )
        #
        #     logger.debug(f"Quote for {symbol}: {quote.last}")
        #     return quote
        # except Exception as e:
        #     logger.error(f"Failed to get quote for {symbol}: {str(e)}")
        #     # Return empty quote on failure
        #     return Quote(symbol=symbol, bid=0.0, ask=0.0, last=0.0, volume=0)

        logger.warning(f"get_quote() called on TemplateBrokerAdapter for symbol {symbol} - not implemented")
        return Quote(symbol=symbol, bid=0.0, ask=0.0, last=0.0, volume=0)

    def subscribe_to_market_data(
        self,
        symbols: List[str],
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
        # TODO: Implement market data subscription logic
        # Example:
        # 1. Convert symbols to broker-specific format if needed
        # 2. Subscribe to real-time data feed
        # 3. Set up callback to convert broker's data format to Quote objects
        # 4. Start the data feed
        #
        # Example structure:
        # try:
        #     logger.info(f"Subscribing to market data for: {symbols}")
        #     # Convert symbols
        #     broker_symbols = [self._convert_symbol(s) for s in symbols]
        #
        #     # Define internal callback that converts broker data to Quote
        #     def internal_callback(broker_data):
        #         try:
        #             quote = Quote(
        #                 symbol=self._convert_symbol_from_broker(broker_data.get('symbol')),
        #                 bid=float(broker_data.get('bid', 0.0)),
        #                 ask=float(broker_data.get('ask', 0.0)),
        #                 last=float(broker_data.get('last', 0.0)),
        #                 volume=int(broker_data.get('volume', 0)),
        #                 timestamp=datetime.fromtimestamp(
        #                     broker_data.get('timestamp', time.time())
        #                 ) if broker_data.get('timestamp') else datetime.now()
        #             )
        #             callback(quote)
        #         except Exception as e:
        #             logger.error(f"Error in market data callback: {str(e)}")
        #
        #     # Subscribe to data feed
        #     self._make_api_call(
        #         self._api_client.subscribe_to_market_data,
        #         symbols=broker_symbols,
        #         callback=internal_callback
        #     )
        #
        #     logger.info(f"Subscribed to market data for {len(symbols)} symbols")
        #     return True
        # except Exception as e:
        #     logger.error(f"Failed to subscribe to market data: {str(e)}")
        #     return False

        logger.warning(f"subscribe_to_market_data() called on TemplateBrokerAdapter for {len(symbols)} symbols - not implemented")
        return False

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        """
        Unsubscribe from market data for a symbol.

        Args:
            symbol: Symbol to unsubscribe from

        Returns:
            True if unsubscription successful, False otherwise
        """
        # TODO: Implement unsubscription logic
        # Example:
        # 1. Call broker's unsubscribe API
        # 2. Return True if successful
        #
        # Example structure:
        # try:
        #     logger.info(f"Unsubscribing from market data for: {symbol}")
        #     self._make_api_call(
        #         self._api_client.unsubscribe_from_market_data,
        #         symbol=self._convert_symbol(symbol)
        #     )
        #     logger.info(f"Unsubscribed from market data for: {symbol}")
        #     return True
        # except Exception as e:
        #     logger.error(f"Failed to unsubscribe from market data for {symbol}: {str(e)}")
        #     return False

        logger.warning(f"unsubscribe_from_market_data() called on TemplateBrokerAdapter for {symbol} - not implemented")
        return False

    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day"
    ) -> List[Dict[str, Any]]:
        """
        Get historical market data for backtesting and analysis.

        Args:
            symbol: Trading symbol
            from_date: Start date for historical data
            to_date: End date for historical data
            interval: Data interval (minute, 3minute, 5minute, 15minute, 30minute, 60minute, day)

        Returns:
            List of historical data candles (each as a dict with OHLCV fields)
        """
        # TODO: Implement historical data retrieval logic
        # Example:
        # 1. Convert interval to broker-specific format if needed
        # 2. Call broker's historical data API
        # 3. Convert response to list of dicts with standard OHLCV fields
        # 4. Return the list
        #
        # Example structure:
        # try:
        #     logger.debug(f"Getting historical data for {symbol} from {from_date} to {to_date}")
        #     # Convert interval
        #     broker_interval = self._map_interval(interval)
        #
        #     # Get historical data
        #     data = self._make_api_call(
        #         self._api_client.get_historical_data,
        #         symbol=self._convert_symbol(symbol),
        #         from_date=from_date,
        #         to_date=to_date,
        #         interval=broker_interval
        #     )
        #
        #     # Convert to standard format
        #     result = []
        #     for candle in data:
        #         result.append({
        #             'date': candle.get('date'),  # Adjust based on broker's format
        #             'open': float(candle.get('open', 0.0)),
        #             'high': float(candle.get('high', 0.0)),
        #             'low': float(candle.get('low', 0.0)),
        #             'close': float(candle.get('close', 0.0)),
        #             'volume': int(candle.get('volume', 0))
        #         })
        #
        #     logger.debug(f"Retrieved {len(result)} historical candles for {symbol}")
        #     return result
        # except Exception as e:
        #     logger.error(f"Failed to get historical data for {symbol}: {str(e)}")
        #     return []

        logger.warning(f"get_historical_data() called on TemplateBrokerAdapter for {symbol} - not implemented")
        return []

    # ================================================================
    # HELPER METHODS (TO BE IMPLEMENTED BASED ON YOUR BROKER'S API)
    # ================================================================

    def _convert_symbol(self, symbol: str) -> str:
        """
        Convert internal symbol format to broker-specific format.

        Args:
            symbol: Internal symbol format (e.g., "NIFTY23JANFUT")

        Returns:
            Broker-specific symbol format
        """
        # TODO: Implement symbol conversion based on your broker's requirements
        # Example:
        # if your broker expects "NIFTY23JAN" but we use "NIFTY23JANFUT":
        # return symbol.replace('FUT', '')
        #
        # For most cases, you might not need conversion:
        return symbol

    def _convert_symbol_from_broker(self, broker_symbol: str) -> str:
        """
        Convert broker-specific symbol format to internal symbol format.

        Args:
            broker_symbol: Symbol format from broker's API

        Returns:
            Internal symbol format
        """
        # TODO: Implement reverse symbol conversion
        # Example:
        # if your broker returns "NIFTY23JAN" but we want "NIFTY23JANFUT":
        # return broker_symbol + 'FUT'
        #
        # For most cases, you might not need conversion:
        return broker_symbol

    def _map_order_type(self, order_type: str) -> str:
        """
        Map internal order type to broker-specific order type.

        Args:
            order_type: Internal order type (MARKET, LIMIT, SL, SL-M)

        Returns:
            Broker-specific order type
        """
        # TODO: Implement order type mapping based on your broker's API
        # Example mapping:
        # order_type_map = {
        #     'MARKET': 'MARKET',
        #     'LIMIT': 'LIMIT',
        #     'SL': 'STOP_LOSS',
        #     'SL-M': 'STOP_LOSS_MARKET'
        # }
        # return order_type_map.get(order_type, order_type)
        return order_type

    def _map_interval(self, interval: str) -> str:
        """
        Map internal interval to broker-specific interval format.

        Args:
            interval: Internal interval (minute, 5minute, day, etc.)

        Returns:
            Broker-specific interval format
        """
        # TODO: Implement interval mapping based on your broker's API
        # Example mapping:
        # interval_map = {
        #     'minute': '1',
        #     '5minute': '5',
        #     '15minute': '15',
        #     'day': 'D'
        # }
        # return interval_map.get(interval, interval)
        return interval


# ================================================================
# BROKER FACTORY
# ================================================================

class BrokerFactory:
    """
    Factory for creating broker adapter instances.

    This factory allows dynamic creation of broker adapters based on
    configuration, making it easy to switch between different brokers
    without changing core trading logic.
    """

    # Registry of available broker adapters
    _adapters = {
        'template': TemplateBrokerAdapter,
        # Add your broker adapters here as you implement them:
        # 'kite': KiteBrokerAdapter,
        # 'angel': AngelBrokerAdapter,
        # 'mybroker': MyBrokerAdapter,
    }

    @classmethod
    def register_adapter(cls, broker_type: str, adapter_class: type) -> None:
        """
        Register a new broker adapter.

        Args:
            broker_type: String identifier for the broker (e.g., 'kite', 'mybroker')
            adapter_class: Class that implements BrokerPort
        """
        if not issubclass(adapter_class, BrokerPort):
            raise ValueError(f"Adapter class must inherit from BrokerPort")

        cls._adapters[broker_type.lower()] = adapter_class
        logger.info(f"Registered broker adapter: {broker_type}")

    @classmethod
    def create_broker(cls, broker_type: str, config: Dict[str, Any]) -> BrokerPort:
        """
        Create a broker adapter instance.

        Args:
            broker_type: Type of broker to create (e.g., 'kite', 'template')
            config: Configuration dictionary for the broker

        Returns:
            BrokerPort implementation

        Raises:
            ValueError: If broker_type is not registered
        """
        broker_type_lower = broker_type.lower()

        if broker_type_lower not in cls._adapters:
            available = ', '.join(cls._adapters.keys())
            raise ValueError(
                f"Unknown broker type: {broker_type}. "
                f"Available brokers: {available}"
            )

        adapter_class = cls._adapters[broker_type_lower]
        logger.info(f"Creating broker adapter: {broker_type}")

        try:
            return adapter_class(config)
        except Exception as e:
            logger.error(f"Failed to create broker adapter {broker_type}: {str(e)}")
            raise

    @classmethod
    def list_available_brokers(cls) -> List[str]:
        """
        Get list of registered broker types.

        Returns:
            List of available broker type strings
        """
        return list(cls._adapters.keys())


if __name__ == "__main__":
    # This file demonstrates the pattern - no actual execution needed
    print("=== Template Broker Adapter ===")
    print("This file shows the pattern for implementing a broker adapter.")
    print("")
    print("To create a real broker adapter:")
    print("1. Copy this directory to a new broker-specific directory (e.g., 'mybroker')")
    print("2. Rename this file to match your broker (e.g., mybroker_adapter.py)")
    print("3. Replace all TODO comments with your broker's specific API implementation")
    print("4. Update the broker factory to recognize your new broker type")
    print("")
    print("Key features of this pattern:")
    print("- Implements the BrokerPort interface from core/ports/broker.py")
    print("- Contains detailed TODO comments showing where to add broker-specific code")
    print("- Includes helper methods for symbol conversion, order type mapping, etc.")
    print("- Shows proper error handling and logging patterns")
    print("- Demonstrates how to work with the BrokerFactory for dynamic loading")
    print("")
    print("Available brokers in factory:", BrokerFactory.list_available_brokers())
    print("")
    print("To use a broker adapter in your code:")
    print("  from infrastructure.adapters.brokers.template.adapter import BrokerFactory")
    print("  broker = BrokerFactory.create_broker('template', config)")
    print("  # Now you can use 'broker' as a BrokerPort instance")
