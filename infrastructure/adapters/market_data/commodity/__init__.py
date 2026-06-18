"""MCX Commodity Market Data Adapter - Fetches MCX commodity futures data.

Provides real-time and historical market data for MCX commodities through
the MarketDataPort interface. Uses Yahoo Finance and investing.com as data sources.

Usage:
    from infrastructure.adapters.market_data.commodity import McxCommodityAdapter
"""
from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
    McxCommodityAdapter,
)

__all__ = [
    "McxCommodityAdapter",
]
