"""NSE Equity Market Data Adapter - Fetches NSE/BSE equity stock data.

Provides real-time and historical market data for NSE/BSE stocks through
the MarketDataPort interface. Uses Yahoo Finance as primary data source
with NSE API fallback.

Usage:
    from infrastructure.adapters.market_data.equity import NseEquityAdapter
"""
from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
    NseEquityAdapter,
)

__all__ = [
    "NseEquityAdapter",
]
