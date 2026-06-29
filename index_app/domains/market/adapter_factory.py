"""
Application-Layer Market Data Adapter Factory.

Creates concrete infrastructure adapter instances for all supported
asset classes. Lives in the application layer (index_app/) to maintain
ADR-0010 compliance (core/ must not import from infrastructure/).

This is the single place where infrastructure adapter types are resolved.
"""

from __future__ import annotations

import logging
from typing import Any

from core.ports.market_data import MarketDataPort

__all__ = [
    "create_market_data_adapter",
    "register_multi_asset_adapters",
]

_log = logging.getLogger(__name__)


def create_market_data_adapter(provider_type: str, config: dict[str, Any]) -> MarketDataPort:
    """Create a market data adapter instance based on provider type.

    Args:
        provider_type: One of YFINANCE, NSE_EQUITY, MCX_COMMODITY, CDS_CURRENCY, WEBSOCKET.
        config: Configuration dictionary for the provider.

    Returns:
        MarketDataPort implementation.

    Raises:
        NotImplementedError: If provider_type is unsupported or creation fails.
        ValueError: If provider_type is not recognized.
    """
    pt = provider_type.upper()

    if pt == "YFINANCE":
        return _create_yfinance_adapter(config)
    elif pt == "NSE_EQUITY":
        return _create_nse_equity_adapter(config)
    elif pt == "MCX_COMMODITY":
        return _create_mcx_commodity_adapter(config)
    elif pt == "CDS_CURRENCY":
        return _create_cds_currency_adapter(config)
    elif pt == "WEBSOCKET":
        return _create_nse_ws_adapter(config)
    else:
        raise ValueError(f"Unsupported market data provider type: {provider_type}")


def register_multi_asset_adapters(container_instance: Any) -> None:
    """Register multi-asset market data adapters in the DI container.

    Called from index_app/domains/trading/container.py during startup.
    """
    try:
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import NseEquityAdapter
        if not container_instance.is_registered(NseEquityAdapter):
            container_instance.register_singleton(NseEquityAdapter, NseEquityAdapter)
    except ImportError:
        _log.debug("[ADAPTER] NseEquityAdapter not available")

    try:
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import McxCommodityAdapter
        if not container_instance.is_registered(McxCommodityAdapter):
            container_instance.register_singleton(McxCommodityAdapter, McxCommodityAdapter)
    except ImportError:
        _log.debug("[ADAPTER] McxCommodityAdapter not available")

    try:
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import CdsCurrencyAdapter
        if not container_instance.is_registered(CdsCurrencyAdapter):
            container_instance.register_singleton(CdsCurrencyAdapter, CdsCurrencyAdapter)
    except ImportError:
        _log.debug("[ADAPTER] CdsCurrencyAdapter not available")


# ---------------------------------------------------------------------------
# Internal factory implementations
# ---------------------------------------------------------------------------


def _create_yfinance_adapter(config: dict[str, Any]) -> MarketDataPort:
    """Create a Yahoo Finance market data adapter (index focus)."""
    try:
        from core.data_engine import DataEngine
        return DataEngine(config)  # type: ignore[return-value]
    except (ImportError, TypeError) as e:
        raise NotImplementedError(f"YFinance adapter creation failed: {e}")


def _create_nse_equity_adapter(config: dict[str, Any]) -> MarketDataPort:
    """Create an NSE equity market data adapter."""
    try:
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import NseEquityAdapter
        adapter = NseEquityAdapter(config)
        adapter.connect()
        return adapter
    except (ImportError, TypeError) as e:
        raise NotImplementedError(f"NSE equity adapter creation failed: {e}")


def _create_mcx_commodity_adapter(config: dict[str, Any]) -> MarketDataPort:
    """Create an MCX commodity market data adapter."""
    try:
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import McxCommodityAdapter
        adapter = McxCommodityAdapter(config)
        adapter.connect()
        return adapter
    except (ImportError, TypeError) as e:
        raise NotImplementedError(f"MCX commodity adapter creation failed: {e}")


def _create_cds_currency_adapter(config: dict[str, Any]) -> MarketDataPort:
    """Create a CDS currency market data adapter."""
    try:
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import CdsCurrencyAdapter
        adapter = CdsCurrencyAdapter(config)
        adapter.connect()
        return adapter
    except (ImportError, TypeError) as e:
        raise NotImplementedError(f"CDS currency adapter creation failed: {e}")


def _create_nse_ws_adapter(config: dict[str, Any]) -> MarketDataPort:
    """Create an NSE index WebSocket market data adapter."""
    try:
        from infrastructure.adapters.market_data.websocket.nse_index_ws_adapter import NseIndexWebSocketAdapter
        adapter = NseIndexWebSocketAdapter(config)
        adapter.connect()
        return adapter
    except (ImportError, TypeError) as e:
        raise NotImplementedError(f"NSE WebSocket adapter creation failed: {e}")
