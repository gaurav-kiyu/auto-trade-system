"""
Market Data Port Interface

This interface defines the contract that all market data adapters must implement.
It decouples the trading logic from specific market data providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any

# Import shared models
from .broker import Quote


class MarketDataPort(ABC):
    """
    Abstract base class defining the market data interface.

    All market data adapters (Yahoo Finance, NSE API, WebSocket feeds, etc.)
    must implement this interface. This enables the trading logic to remain
    market data provider-agnostic.
    """

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to the market data provider.

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to the market data provider."""
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
    def get_latest_data(self, symbol: str) -> Any:
        """
        Get latest market data for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Market data structure (implementation-specific)
        """
        pass

    @abstractmethod
    def is_data_fresh(self, market_data: Any, max_age_seconds: int = 30) -> bool:
        """
        Check if market data is fresh enough for trading decisions.

        Args:
            market_data: Market data structure from get_latest_data
            max_age_seconds: Maximum age in seconds for data to be considered fresh

        Returns:
            True if data is fresh, False otherwise
        """
        pass

    @abstractmethod
    def subscribe_to_market_data(
        self,
        symbols: list[str],
        callback: Callable[[Any], None]
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
    def get_option_chain(
        self,
        symbol: str,
        expiry_date: datetime | None = None
    ) -> list[dict[str, Any]]:
        """
        Get option chain for a symbol.

        Args:
            symbol: Underlying symbol (e.g., "NIFTY")
            expiry_date: Specific expiry date (optional, gets nearest if not provided)

        Returns:
            List of option contracts with strike prices, premiums, Greeks, etc.
        """
        pass

    @abstractmethod
    def get_instrument_details(self, symbol: str) -> dict[str, Any]:
        """
        Get instrument details for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Dictionary containing instrument details like lot size, tick size, etc.
        """
        pass


# Example implementation showing how existing code would be adapted
class MarketDataAdapterFactory:
    """Factory for creating market data adapter instances."""

    @staticmethod
    def create_market_data_adapter(
        provider_type: str,
        config: dict[str, Any]
    ) -> MarketDataPort:
        """
        Create a market data adapter instance based on type.

        Args:
            provider_type: Type of provider ("YFINANCE", "NSE", "WEBSOCKET")
            config: Configuration dictionary for the provider

        Returns:
            MarketDataPort implementation

        Raises:
            ValueError: If provider_type is not supported
        """
        if provider_type.upper() == "YFINANCE":
            # In practice, this would import and return YahooFinanceAdapter
            raise NotImplementedError("Yahoo Finance market data adapter implementation needed")
        elif provider_type.upper() == "NSE":
            # In practice, this would import and return NseAdapter
            raise NotImplementedError("NSE market data adapter implementation needed")
        elif provider_type.upper() == "WEBSOCKET":
            # In practice, this would import and return WebSocketAdapter
            raise NotImplementedError("WebSocket market data adapter implementation needed")
        else:
            raise ValueError(f"Unsupported market data provider type: {provider_type}")


if __name__ == "__main__":
    # This file defines the interface - no runtime execution needed
    print("MarketDataPort interface defined successfully")
    print("Implementations should be created in infrastructure/adapters/market_data/")
