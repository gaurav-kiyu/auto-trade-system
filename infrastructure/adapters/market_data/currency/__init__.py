"""CDS Currency Market Data Adapter - Fetches NSE CDS currency data.

Provides real-time and historical market data for NSE Currency Derivatives
Segment (USD/INR, EUR/INR, GBP/INR, JPY/INR) through the MarketDataPort interface.

Usage:
    from infrastructure.adapters.market_data.currency import CdsCurrencyAdapter
"""
from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
    CdsCurrencyAdapter,
)

__all__ = [
    "CdsCurrencyAdapter",
]
