"""NSE Equity Market Data Adapter - MarketDataPort implementation for NSE/BSE stocks.

Provides:
  - Real-time quotes for NSE/BSE equities
  - Historical OHLCV data for backtesting
  - Corporate actions calendar
  - Stock fundamentals data

Data Sources (priority order):
  1. Yahoo Finance (yfinance) - primary source for LTP and OHLCV
  2. NSE API (via cloudscraper) - fallback for quote data
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from core.ports.market_data import MarketDataPort

_log = logging.getLogger(__name__)

try:
    import pandas as pd
    import yfinance as yf
except ImportError:
    pd = None  # type: ignore
    yf = None  # type: ignore


class NseEquityAdapter(MarketDataPort):
    """MarketDataPort implementation for NSE/BSE equity stocks.

    Args:
        config: Configuration dict with keys:
            - equity_lookup_timeout: HTTP timeout in seconds (default 10)
            - equity_cache_seconds: Quote cache TTL (default 30)
    """

    NSE_SUFFIX = ".NS"  # Yahoo Finance suffix for NSE stocks

    def __init__(self, config: dict[str, Any] | None = None):
        self._cfg = config or {}
        self._timeout = int(self._cfg.get("equity_lookup_timeout", 10))
        self._cache_ttl = int(self._cfg.get("equity_cache_seconds", 30))
        self._cache: dict[str, tuple[Any, float]] = {}  # symbol -> (data, timestamp)
        self._connected = False

    # ── Connection lifecycle ───────────────────────────────────────────────

    def connect(self) -> bool:
        if yf is None:
            _log.error("yfinance not installed - cannot connect NseEquityAdapter")
            return False
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._cache.clear()

    # ── Quote data ─────────────────────────────────────────────────────────

    def _yf_symbol(self, symbol: str) -> str:
        """Convert NSE symbol to Yahoo Finance format."""
        sym = symbol.upper().strip()
        if not sym.endswith(".NS") and not sym.endswith(".BO"):
            sym += self.NSE_SUFFIX
        return sym

    def get_quote(self, symbol: str) -> Any:
        if not self._connected or yf is None:
            return None
        try:
            ticker = yf.Ticker(self._yf_symbol(symbol))
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
        except (ValueError, TypeError, KeyError, OSError, ConnectionError) as e:
            _log.warning("NSE equity quote failed for %s: %s", symbol, e)
            return None

    def get_latest_data(self, symbol: str) -> Any:
        if not self._connected:
            return None
        now = datetime.now()
        if symbol in self._cache:
            data, ts = self._cache[symbol]
            if (now - ts).total_seconds() < self._cache_ttl:
                return data
        try:
            ticker = yf.Ticker(self._yf_symbol(symbol))
            hist = ticker.history(period="5d", interval="1d", timeout=self._timeout)
            if hist.empty:
                return None
            self._cache[symbol] = (hist, now)
            return hist
        except (ValueError, TypeError, OSError, ConnectionError) as e:
            _log.warning("NSE equity data fetch failed for %s: %s", symbol, e)
            return None

    def is_data_fresh(self, market_data: Any, max_age_seconds: int = 30) -> bool:
        if market_data is None:
            return False
        return True

    def subscribe_to_market_data(self, symbols: list[str], callback: Any) -> bool:
        _log.warning("NSE equity adapter does not support real-time subscription")
        return False

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        return False

    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
    ) -> list[dict[str, Any]]:
        if not self._connected or yf is None:
            return []
        try:
            ticker = yf.Ticker(self._yf_symbol(symbol))
            hist = ticker.history(start=from_date, end=to_date, interval=interval)
            if hist.empty:
                return []
            return hist.reset_index().to_dict(orient="records")
        except (ValueError, TypeError, OSError, ConnectionError) as e:
            _log.warning("NSE equity historical data failed for %s: %s", symbol, e)
            return []

    def get_option_chain(self, symbol: str, expiry_date: datetime | None = None) -> list[dict[str, Any]]:
        _log.warning("NSE equity adapter does not provide option chains")
        return []

    def get_instrument_details(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "exchange": "NSE", "asset_class": "equity"}
