"""
Market Data Port Interface

This interface defines the contract that all market data adapters must implement.
It decouples the trading logic from specific market data providers.

ADR-0010: core/ must not import from infrastructure/. Factory functions that
create infrastructure adapters live in index_app/domains/market/adapter_factory.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any

import logging

from .broker import Quote

_log = logging.getLogger(__name__)


class MarketDataProvider:
    """Well-known market data provider identifiers.

    These string constants are used in ``DATA_PROVIDER_PRIORITY`` and
    ``DATA_PROVIDER_ENABLED`` config keys to select and order providers.
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
            cls.YFINANCE, cls.WEBSOCKET, cls.BROKER, cls.NSE,
            cls.NSE_EQUITY, cls.MCX_COMMODITY, cls.CDS_CURRENCY,
        ]

    @classmethod
    def is_valid(cls, name: str) -> bool:
        """Check if a provider name is known."""
        return name.lower().strip() in cls.all()

    @classmethod
    def adapters_from_config(cls, config: dict[str, Any]) -> list[tuple[str, MarketDataPort]]:
        """Create a list of (name, adapter) pairs from config.

        Delegates to the application-layer adapter factory in
        index_app.domains.market.adapter_factory.
        """
        raw_priority = config.get("DATA_PROVIDER_PRIORITY")
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
    """Abstract base class defining the market data interface.

    All market data adapters (Yahoo Finance, NSE API, WebSocket feeds, etc.)
    must implement this interface.
    """

    @abstractmethod
    def connect(self) -> bool:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        ...

    @abstractmethod
    def get_latest_data(self, symbol: str) -> Any:
        ...

    @abstractmethod
    def is_data_fresh(self, market_data: Any, max_age_seconds: int = 30) -> bool:
        ...

    @abstractmethod
    def subscribe_to_market_data(self, symbols: list[str], callback: Callable[[Any], None]) -> bool:
        ...

    @abstractmethod
    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        ...

    @abstractmethod
    def get_historical_data(self, symbol: str, from_date: datetime, to_date: datetime, interval: str = "day") -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def get_option_chain(self, symbol: str, expiry_date: datetime | None = None) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def get_instrument_details(self, symbol: str) -> dict[str, Any]:
        ...


class MarketDataAdapterFactory:
    """Factory for creating market data adapter instances.

    Delegates to the application-layer factory to maintain ADR-0010
    compliance (no core/ -> infrastructure/ imports). The actual
    implementations live in index_app.domains.market.adapter_factory.
    """

    @staticmethod
    def create_market_data_adapter(provider_type: str, config: dict[str, Any]) -> MarketDataPort:
        """Create a market data adapter instance by delegating to the app-layer factory."""
        try:
            from index_app.domains.market.adapter_factory import create_market_data_adapter as _create
            return _create(provider_type, config)
        except ImportError:
            raise NotImplementedError(
                f"Adapter factory not available for {provider_type}: "
                "install index_app package or check PYTHONPATH"
            )


__all__ = [
    "MarketDataAdapterFactory",
    "MarketDataPort",
    "MarketDataProvider",
]

