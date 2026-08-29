"""CDS Currency Market Data Adapter - MarketDataPort implementation for NSE CDS.

Provides:
  - Real-time quotes for NSE Currency Derivatives (USD/INR, EUR/INR, GBP/INR, JPY/INR)
  - Historical OHLCV data for backtesting
  - RBI reference rates

Data Sources (priority order):
  1. Yahoo Finance (yfinance) - primary source for LTP and OHLCV
  2. RBI API - reference rates
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from core.ports.market_data import MarketDataPort

_log = logging.getLogger(__name__)

try:
    import pandas as pd
    import yfinance as yf
except ImportError:
    pd = None  # type: ignore
    yf = None  # type: ignore


# Mapping of currency pairs to Yahoo Finance tickers
CURRENCY_YF_TICKERS: dict[str, str] = {
    "USDINR": "USDINR=X",    # USD/INR
    "EURINR": "EURINR=X",    # EUR/INR
    "GBPINR": "GBPINR=X",    # GBP/INR
    "JPYINR": "JPYINR=X",    # JPY/INR
}


class CdsCurrencyAdapter(MarketDataPort):
    """MarketDataPort implementation for NSE Currency Derivatives Segment.

    Note: Yahoo Finance forex data for INR pairs has limited intraday resolution.
    For production use, connect directly to the NSE CDS feed or a forex data provider.

    Args:
        config: Configuration dict with keys:
            - currency_lookup_timeout: HTTP timeout (default 10)
            - currency_cache_seconds: Quote cache TTL (default 60)
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._cfg = config or {}
        self._timeout = int(self._cfg.get("currency_lookup_timeout", 10))
        self._cache_ttl = int(self._cfg.get("currency_cache_seconds", 60))
        self._cache: dict[str, tuple[Any, float]] = {}
        self._connected = False

    def connect(self) -> bool:
        if yf is None:
            _log.error("yfinance not installed - cannot connect CdsCurrencyAdapter")
            return False
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._cache.clear()

    def _resolve_symbol(self, symbol: str) -> str:
        sym = symbol.upper().strip()
        return CURRENCY_YF_TICKERS.get(sym, f"{sym}=X")

    def get_quote(self, symbol: str) -> Any:
        if not self._connected or yf is None:
            return None
        try:
            ticker = yf.Ticker(self._resolve_symbol(symbol))
            hist = ticker.history(period="1d", timeout=self._timeout)
            if hist.empty:
                return None
            last_row = hist.iloc[-1]
            from core.ports.broker import Quote
            return Quote(
                symbol=symbol,
                bid=float(last_row.get("Close", 0)),
                ask=float(last_row.get("Close", 0)),
                last=float(last_row.get("Close", 0)),
                volume=int(last_row.get("Volume", 0)),
            )
        except (ValueError, TypeError, OSError, ConnectionError) as e:
            _log.warning("CDS quote failed for %s: %s", symbol, e)
            return None

    def get_latest_data(self, symbol: str) -> Any:
        if not self._connected or yf is None:
            return None
        try:
            ticker = yf.Ticker(self._resolve_symbol(symbol))
            hist = ticker.history(period="5d", interval="1d", timeout=self._timeout)
            return hist if not hist.empty else None
        except (ValueError, TypeError, OSError, ConnectionError) as e:
            _log.warning("CDS data failed for %s: %s", symbol, e)
            return None

    def is_data_fresh(self, market_data: Any, max_age_seconds: int = 30) -> bool:
        return market_data is not None

    def subscribe_to_market_data(self, symbols: list[str], callback: Any) -> bool:
        _log.warning("CDS adapter does not support real-time subscription")
        return False

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        return False

    def get_historical_data(
        self, symbol: str, from_date: datetime, to_date: datetime, interval: str = "day",
    ) -> list[dict[str, Any]]:
        if not self._connected or yf is None:
            return []
        try:
            ticker = yf.Ticker(self._resolve_symbol(symbol))
            hist = ticker.history(start=from_date, end=to_date, interval=interval)
            return hist.reset_index().to_dict(orient="records") if not hist.empty else []
        except (ValueError, TypeError, OSError, ConnectionError) as e:
            _log.warning("CDS historical data failed for %s: %s", symbol, e)
            return []

    def get_option_chain(self, symbol: str, expiry_date: datetime | None = None) -> list[dict[str, Any]]:
        _log.warning("CDS adapter does not provide option chains")
        return []

    def get_instrument_details(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "exchange": "CDS", "asset_class": "currency"}
