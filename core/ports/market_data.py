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
import logging

from .broker import Quote

_log = logging.getLogger(__name__)


class MarketDataProvider:
    """Well-known market data provider identifiers.

    These string constants are used in ``DATA_PROVIDER_PRIORITY`` and
    ``DATA_PROVIDER_ENABLED`` config keys to select and order providers.

    Usage::

        provider = MarketDataProvider.WEBSOCKET  # "websocket"
        factory.create_market_data_adapter(provider, config)
    """

    YFINANCE = "yfinance"
    WEBSOCKET = "websocket"
    BROKER = "broker"
    NSE = "nse"
    NSE_EQUITY = "nse_equity"
    MCX_COMMODITY = "mcx_commodity"
    CDS_CURRENCY = "cds_currency"

    @classmethod
    def all(cls) -> list[str]:
        """Return all known provider identifiers."""
        return [
            cls.YFINANCE,
            cls.WEBSOCKET,
            cls.BROKER,
            cls.NSE,
            cls.NSE_EQUITY,
            cls.MCX_COMMODITY,
            cls.CDS_CURRENCY,
        ]

    @classmethod
    def is_valid(cls, name: str) -> bool:
        """Check if a provider name is known."""
        return name.lower().strip() in cls.all()

    @classmethod
    def adapters_from_config(cls, config: dict[str, Any]) -> list[tuple[str, MarketDataPort]]:
        """Create a list of (name, adapter) pairs from config.

        Reads ``DATA_PROVIDER_PRIORITY`` and ``DATA_PROVIDER_ENABLED`` from
        config, then creates and connects only enabled adapters in priority
        order.  Adapters that fail to connect are skipped.

        Args:
            config: Application configuration dict.

        Returns:
            List of (name, adapter) tuples in provider priority order.
        """
        raw_priority = config.get("DATA_PROVIDER_PRIORITY")
        # Handle None/non-list gracefully - fall back to default
        if not isinstance(raw_priority, (list, tuple)):
            raw_priority = ["yfinance"]
        priority: list[str] = list(raw_priority)
        enabled: dict[str, bool] = dict(config.get("DATA_PROVIDER_ENABLED", {}))

        result: list[tuple[str, MarketDataPort]] = []

        for name in priority:
            is_enabled = enabled.get(name, True)
            if not is_enabled:
                continue
            try:
                adapter = MarketDataAdapterFactory.create_market_data_adapter(name, config)
                if adapter is not None:
                    result.append((name, adapter))
            except (NotImplementedError, ValueError, ImportError, TypeError) as exc:
                _log.warning("[MDP] provider %s skipped: %s", name, exc)
        return result


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
            return _create_yfinance_adapter(config)
        elif provider_type.upper() == "NSE_EQUITY":
            return _create_nse_equity_adapter(config)
        elif provider_type.upper() == "MCX_COMMODITY":
            return _create_mcx_commodity_adapter(config)
        elif provider_type.upper() == "CDS_CURRENCY":
            return _create_cds_currency_adapter(config)
        elif provider_type.upper() == "WEBSOCKET":
            return _create_nse_ws_adapter(config)
        else:
            raise ValueError(f"Unsupported market data provider type: {provider_type}")



def _create_yfinance_adapter(config: dict[str, Any]) -> MarketDataPort:
    """Create a generic Yahoo Finance market data adapter (index focus)."""
    try:
        from core.data_engine import DataEngine
        # DataEngine wraps yfinance for index data - use it directly
        return DataEngine(config)  # type: ignore[return-value]
    except (ImportError, TypeError) as e:
        raise NotImplementedError(f"YFinance adapter creation failed: {e}")


def _create_nse_equity_adapter(config: dict[str, Any]) -> MarketDataPort:
    """Create an NSE equity market data adapter."""
    try:
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter(config)
        adapter.connect()
        return adapter
    except (ImportError, TypeError) as e:
        raise NotImplementedError(f"NSE equity adapter creation failed: {e}")


def _create_mcx_commodity_adapter(config: dict[str, Any]) -> MarketDataPort:
    """Create an MCX commodity market data adapter."""
    try:
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter(config)
        adapter.connect()
        return adapter
    except (ImportError, TypeError) as e:
        raise NotImplementedError(f"MCX commodity adapter creation failed: {e}")


def _create_cds_currency_adapter(config: dict[str, Any]) -> MarketDataPort:
    """Create a CDS currency market data adapter."""
    try:
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter(config)
        adapter.connect()
        return adapter
    except (ImportError, TypeError) as e:
        raise NotImplementedError(f"CDS currency adapter creation failed: {e}")


def _create_nse_ws_adapter(config: dict[str, Any]) -> MarketDataPort:
    """Create an NSE index WebSocket market data adapter."""
    try:
        from infrastructure.adapters.market_data.websocket.nse_index_ws_adapter import (
            NseIndexWebSocketAdapter,
        )
        adapter = NseIndexWebSocketAdapter(config)
        adapter.connect()
        return adapter
    except (ImportError, TypeError) as exc:
        raise NotImplementedError(f"NSE WebSocket adapter creation failed: {exc}")


if __name__ == "__main__":
    # This file defines the interface - no runtime execution needed
    print("MarketDataPort interface defined successfully")
    print("Implementations should be created in infrastructure/adapters/market_data/")
