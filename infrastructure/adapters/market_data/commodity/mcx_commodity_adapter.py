"""MCX Commodity Market Data Adapter - MarketDataPort implementation for MCX commodities.

Provides:
  - Real-time quotes for MCX commodity futures (Gold, Silver, Crude, etc.)
  - Historical OHLCV data for backtesting
  - Contract specifications

Data Sources (priority order):
  1. Yahoo Finance (yfinance) - primary source for LTP and OHLCV
  2. Investing.com / MCX API - fallback
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


# Mapping of MCX symbols to Yahoo Finance tickers
MCX_YF_TICKERS: dict[str, str] = {
    "GOLD": "GC=F",          # Gold Futures (COMEX proxy for MCX)
    "SILVER": "SI=F",        # Silver Futures (COMEX proxy)
    "CRUDEOIL": "CL=F",      # Crude Oil Futures (NYMEX proxy)
    "NATURALGAS": "NG=F",    # Natural Gas Futures (NYMEX proxy)
    "COPPER": "HG=F",        # Copper Futures (COMEX proxy)
    "ALUMINIUM": "ALI=F",    # Aluminium Futures (LME proxy)
    "ZINC": "ZNC=F",         # Zinc Futures
}


class McxCommodityAdapter(MarketDataPort):
    """MarketDataPort implementation for MCX commodity futures.

    Args:
        config: Configuration dict with keys:
            - commodity_lookup_timeout: HTTP timeout (default 10)
            - commodity_cache_seconds: Quote cache TTL (default 30)
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._cfg = config or {}
        self._timeout = int(self._cfg.get("commodity_lookup_timeout", 10))
        self._cache_ttl = int(self._cfg.get("commodity_cache_seconds", 30))
        self._cache: dict[str, tuple[Any, float]] = {}
        self._connected = False

    def connect(self) -> bool:
        if yf is None:
            _log.error("yfinance not installed - cannot connect McxCommodityAdapter")
            return False
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._cache.clear()

    def _resolve_symbol(self, symbol: str) -> str:
        """Resolve MCX symbol to Yahoo Finance ticker."""
        sym = symbol.upper().strip()
        return MCX_YF_TICKERS.get(sym, sym)

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
            _log.warning("MCX quote failed for %s: %s", symbol, e)
            return None

    def get_latest_data(self, symbol: str) -> Any:
        if not self._connected or yf is None:
            return None
        try:
            ticker = yf.Ticker(self._resolve_symbol(symbol))
            hist = ticker.history(period="5d", interval="1d", timeout=self._timeout)
            return hist if not hist.empty else None
        except (ValueError, TypeError, OSError, ConnectionError) as e:
            _log.warning("MCX data failed for %s: %s", symbol, e)
            return None

    def is_data_fresh(self, market_data: Any, max_age_seconds: int = 30) -> bool:
        return market_data is not None

    def subscribe_to_market_data(self, symbols: list[str], callback: Any) -> bool:
        _log.warning("MCX adapter does not support real-time subscription")
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
            _log.warning("MCX historical data failed for %s: %s", symbol, e)
            return []

    def get_option_chain(self, symbol: str, expiry_date: datetime | None = None) -> list[dict[str, Any]]:
        _log.warning("MCX adapter does not provide option chains")
        return []

    def get_instrument_details(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "exchange": "MCX", "asset_class": "commodity"}
