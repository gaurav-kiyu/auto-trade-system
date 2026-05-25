"""
Yahoo Finance Market Data Adapter

This adapter implements the MarketDataPort interface for Yahoo Finance data.
It provides market data retrieval using the yfinance library.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pandas as pd
from core.datetime_ist import now_ist

# Import the market data port interface this adapter implements
try:
    from core.ports.market_data import MarketDataPort, Quote
except ImportError:
    # Fallback for type hints
    MarketDataPort = Any
    Quote = Any

# Try to import yfinance
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    # Mock yfinance for structure demonstration
    class yf:
        class Ticker:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, period="1d", interval="1d", start=None, end=None):
                # Return empty DataFrame with expected structure
                return pd.DataFrame()

            def info(self):
                return {}

            def option_chain(self, date=None):
                return None


# Import LoggingService
from core.logging import LoggingService


class YahooFinanceAdapter(MarketDataPort):
    """
    Yahoo Finance market data adapter implementation.

    This adapter provides market data from Yahoo Finance using the yfinance library
    and implements the MarketDataPort interface for clean architecture.
    """

    def __init__(self,
                 enable_rate_limit: bool = True,
                 max_retries: int = 3,
                 requests_per_second: float = 2.0):
        """
        Initialize the Yahoo Finance market data adapter.

        Args:
            enable_rate_limit: Whether to enable rate limiting
            max_retries: Maximum number of retry attempts for failed requests
            requests_per_second: Rate limit for requests per second
        """
        if not YFINANCE_AVAILABLE:
            raise ImportError("yfinance library not available. Install yfinance package.")

        self._enable_rate_limit = enable_rate_limit
        self._max_retries = max_retries
        self._min_request_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0
        self._last_request_time = 0

        # Cache for ticker objects to avoid repeated creation
        self._ticker_cache: dict[str, Any] = {}
        self._ticker_cache_time: dict[str, float] = {}
        self._cache_ttl = 300  # 5 minutes

        # Track last fetch time per symbol for freshness checks
        self._last_fetch_time: dict[str, float] = {}

        logger = self._get_logger()
        self._logger = LoggingService(
            log_dir="logs",
            log_filename_prefix="yahoo_finance_adapter_",
            retain_days=30,
            json_log_file="",
            version="UNKNOWN",
            enable_correlation_ids=False,
            enable_contextual_logging=False
        )
        self._logger.info("Yahoo Finance market data adapter initialized")

    def _get_logger(self):
        """Get logger instance."""
        import logging
        return logging.getLogger(__name__)

    def _rate_limit(self):
        """Implement rate limiting to avoid API throttling."""
        if not self._enable_rate_limit:
            return

        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _make_request_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a request with retry logic.

        Args:
            func: Function to call
            *args, **kwargs: Arguments to pass to the function

        Returns:
            Function result

        Raises:
            Exception: If all retry attempts fail
        """
        last_exception = None
        for attempt in range(self._max_retries):
            try:
                self._rate_limit()
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self._max_retries - 1:
                    # Exponential backoff
                    wait_time = (2 ** attempt) * 0.5
                    time.sleep(wait_time)
                else:
                    raise
        raise last_exception

    def _get_ticker(self, symbol: str) -> Any:
        """
        Get or create a yfinance Ticker object for the symbol.

        Args:
            symbol: Trading symbol

        Returns:
            yfinance Ticker object
        """
        # Check cache first
        if (symbol in self._ticker_cache and
            symbol in self._ticker_cache_time and
            time.time() - self._ticker_cache_time[symbol] < self._cache_ttl):
            return self._ticker_cache[symbol]

        # Create new ticker
        ticker = yf.Ticker(symbol)
        self._ticker_cache[symbol] = ticker
        self._ticker_cache_time[symbol] = time.time()
        return ticker

    def _convert_to_quote(self, symbol: str, data: pd.Series) -> Quote:
        """
        Convert pandas Series data to Quote object.

        Args:
            symbol: Trading symbol
            data: pandas Series containing quote data

        Returns:
            Quote object
        """
        return Quote(
            symbol=symbol,
            bid=float(data.get('bid', 0.0)) if pd.notna(data.get('bid')) else 0.0,
            ask=float(data.get('ask', 0.0)) if pd.notna(data.get('ask')) else 0.0,
            last=float(data.get('lastPrice', data.get('regularMarketPrice', 0.0))) if pd.notna(data.get('lastPrice', data.get('regularMarketPrice'))) else 0.0,
            volume=int(data.get('volume', data.get('regularMarketVolume', 0))) if pd.notna(data.get('volume', data.get('regularMarketVolume'))) else 0,
            timestamp=now_ist()
        )

    def connect(self) -> bool:
        """
        Establish connection to the market data provider.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Test connection by getting info for a well-known symbol
            ticker = self._get_ticker("AAPL")  # Using US symbol for reliability test
            info = self._make_request_with_retry(lambda: ticker.info)
            return info is not None and len(info) > 0
        except Exception as e:
            logger = self._get_logger()
            logger.warning(f"Failed to connect to Yahoo Finance: {e}")
            return False

    def disconnect(self) -> None:
        """Close connection to the market data provider."""
        # yfinance doesn't require explicit disconnection
        # Clear ticker cache
        self._ticker_cache.clear()
        self._ticker_cache_time.clear()

    def get_quote(self, symbol: str) -> Quote:
        """
        Get current quote for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Quote object with bid, ask, last price, etc.
        """
        try:
            ticker = self._get_ticker(symbol)

            # Try to get quote data
            quote_data = self._make_request_with_retry(lambda: ticker.info)

            if not quote_data:
                # Fallback to recent history data
                hist_data = self._make_request_with_retry(
                    lambda: ticker.history(period="1d", interval="1m")
                )
                if not hist_data.empty:
                    latest = hist_data.iloc[-1]
                    quote_data = {
                        'bid': latest.get('Open', 0.0),
                        'ask': latest.get('Close', 0.0),
                        'lastPrice': latest.get('Close', 0.0),
                        'volume': latest.get('Volume', 0)
                    }

            self._last_fetch_time[symbol] = time.time()
            return self._convert_to_quote(symbol, quote_data)

        except Exception as e:
            logger = self._get_logger()
            self._logger.error(f"Failed to get quote for {symbol}: {e}")
            return None  # Caller must handle None vs zero-price

    def get_latest_data(self, symbol: str) -> Any:
        """
        Get latest market data for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Market data structure (implementation-specific)
            For Yahoo Finance, returns the ticker info dict
        """
        try:
            ticker = self._get_ticker(symbol)
            data = self._make_request_with_retry(lambda: ticker.info)
            self._last_fetch_time[symbol] = time.time()
            return data
        except Exception as e:
            logger = self._get_logger()
            self._logger.error(f"Failed to get latest data for {symbol}: {e}")
            return {}

    def is_data_fresh(self, market_data: Any, symbol: str = "") -> bool:
        """
        Check if market data is fresh enough for trading decisions.

        Args:
            market_data: Market data structure from get_latest_data (unused, kept for compatibility)
            symbol: Symbol to check freshness for

        Returns:
            True if data was fetched within the last 30 seconds, False otherwise
        """
        if symbol and symbol in self._last_fetch_time:
            age = time.time() - self._last_fetch_time[symbol]
            return age < 30  # 30 seconds max staleness
        return False

    def subscribe_to_market_data(
        self,
        symbols: list[str],
        callback: Callable[[Any], None]
    ) -> bool:
        """
        Subscribe to real-time market data for symbols.

        Note: Yahoo Finance does not provide true real-time WebSocket data
        in the standard library. This would require implementing polling
        or using a different approach.

        Args:
            symbols: List of symbols to subscribe to
            callback: Function to call when market data arrives

        Returns:
            True if subscription setup successful, False otherwise
        """
        # For Yahoo Finance, we can't provide true real-time subscriptions
        # without implementing our own polling mechanism
        # A full implementation would:
        # 1. Start a background thread for each symbol
        # 2. Periodically fetch quote data
        # 3. Call the callback with new data
        # 4. Handle unsubscription cleanup
        #
        # For this implementation, we'll return False to indicate
        # that real-time subscriptions are not supported via this method
        logger = self._get_logger()
        logger.info("Yahoo Finance adapter does not support real-time subscriptions")
        return False

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        """
        Unsubscribe from market data for a symbol.

        Args:
            symbol: Symbol to unsubscribe from

        Returns:
            True if unsubscription successful, False otherwise
        """
        # Would clean up subscription resources if we had them
        return True

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
        try:
            ticker = self._get_ticker(symbol)

            # Map interval to yfinance format
            yf_interval = {
                "minute": "1m",
                "3minute": "30m",  # yfinance doesn't have 3m, using closest
                "5minute": "5m",
                "15minute": "15m",
                "30minute": "30m",
                "60minute": "60m",
                "day": "1d",
                "week": "1wk",
                "month": "1mo"
            }.get(interval, "1d")

            # Calculate period
            delta = to_date - from_date
            days = delta.days

            # Determine period string for yfinance
            if days <= 7:
                period = "7d"
            elif days <= 30:
                period = "1mo"
            elif days <= 90:
                period = "3mo"
            elif days <= 365:
                period = "1y"
            else:
                period = "2y"

            # Get historical data
            hist_data = self._make_request_with_retry(
                lambda: ticker.history(
                    period=period,
                    interval=yf_interval,
                    start=from_date,
                    end=to_date
                )
            )

            if hist_data.empty:
                return []

            # Convert to list of dictionaries
            result = []
            for timestamp, row in hist_data.iterrows():
                result.append({
                    'timestamp': timestamp.to_pydatetime() if hasattr(timestamp, 'to_pydatetime') else timestamp,
                    'open': float(row['Open']) if pd.notna(row['Open']) else 0.0,
                    'high': float(row['High']) if pd.notna(row['High']) else 0.0,
                    'low': float(row['Low']) if pd.notna(row['Low']) else 0.0,
                    'close': float(row['Close']) if pd.notna(row['Close']) else 0.0,
                    'volume': int(row['Volume']) if pd.notna(row['Volume']) else 0
                })

            return result

        except Exception as e:
            logger = self._get_logger()
            self._logger.error(f"Failed to get historical data for {symbol}: {e}")
            return []

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
        try:
            # For Indian indices, we need to use the correct symbol format
            # Yahoo Finance uses ^NIFTY for NIFTY index, etc.
            yahoo_symbol = symbol
            if symbol.upper() in ['NIFTY', 'BANKNIFTY', 'FINNIFTY']:
                yahoo_symbol = f"^{symbol.upper()}"

            ticker = self._get_ticker(yahoo_symbol)

            # Get option chain
            if expiry_date:
                # Format date for yfinance
                date_str = expiry_date.strftime("%Y-%m-%d")
                options_data = self._make_request_with_retry(
                    lambda: ticker.option_chain(date_str)
                )
            else:
                options_data = self._make_request_with_retry(
                    lambda: ticker.option_chain
                )

            if not options_data:
                return []

            result = []

            # Process calls and puts
            if hasattr(options_data, 'calls') and not options_data.calls.empty:
                for _, row in options_data.calls.iterrows():
                    result.append({
                        'symbol': row.get('contractSymbol', ''),
                        'strike': float(row.get('strike', 0.0)),
                        'lastPrice': float(row.get('lastPrice', 0.0)),
                        'bid': float(row.get('bid', 0.0)),
                        'ask': float(row.get('ask', 0.0)),
                        'volume': int(row.get('volume', 0)),
                        'openInterest': int(row.get('openInterest', 0)),
                        'impliedVolatility': float(row.get('impliedVolatility', 0.0)) if pd.notna(row.get('impliedVolatility')) else 0.0,
                        'inTheMoney': bool(row.get('inTheMoney', False)),
                        'optionType': 'CALL'
                    })

            if hasattr(options_data, 'puts') and not options_data.puts.empty:
                for _, row in options_data.puts.iterrows():
                    result.append({
                        'symbol': row.get('contractSymbol', ''),
                        'strike': float(row.get('strike', 0.0)),
                        'lastPrice': float(row.get('lastPrice', 0.0)),
                        'bid': float(row.get('bid', 0.0)),
                        'ask': float(row.get('ask', 0.0)),
                        'volume': int(row.get('volume', 0)),
                        'openInterest': int(row.get('openInterest', 0)),
                        'impliedVolatility': float(row.get('impliedVolatility', 0.0)) if pd.notna(row.get('impliedVolatility')) else 0.0,
                        'inTheMoney': bool(row.get('inTheMoney', False)),
                        'optionType': 'PUT'
                    })

            return result

        except Exception as e:
            logger = self._get_logger()
            self._logger.error(f"Failed to get option chain for {symbol}: {e}")
            return []

    def get_instrument_details(self, symbol: str) -> dict[str, Any]:
        """
        Get instrument details for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Dictionary containing instrument details like lot size, tick size, etc.
        """
        try:
            ticker = self._get_ticker(symbol)
            info = self._make_request_with_retry(lambda: ticker.info)

            if not info:
                return {}

            # Extract relevant instrument details
            details = {
                'symbol': symbol,
                'name': info.get('longName', info.get('shortName', '')),
                'exchange': info.get('exchange', ''),
                'currency': info.get('currency', 'USD'),
                'market': info.get('market', ''),
                'sector': info.get('sector', ''),
                'industry': info.get('industry', ''),
                'lotSize': info.get('lotSize', 1),  # Default to 1 if not specified
                'tickSize': info.get('tickSize', 0.01),  # Default tick size
                'isin': info.get('isin', ''),
                'marketCap': info.get('marketCap', 0),
                'enterpriseValue': info.get('enterpriseValue', 0),
                'outstandingShares': info.get('sharesOutstanding', 0),
                'floatShares': info.get('floatShares', 0)
            }

            return details

        except Exception as e:
            logger = self._get_logger()
            self._logger.error(f"Failed to get instrument details for {symbol}: {e}")
            return {}


# Factory function for creating Yahoo Finance market data adapter instances
def create_yahoo_finance_adapter(config: dict[str, Any]) -> YahooFinanceAdapter:
    """
    Factory function to create a YahooFinanceAdapter from configuration.

    Args:
        config: Configuration dictionary containing:
                - enable_rate_limit: Whether to enable rate limiting (optional, default True)
                - max_retries: Maximum retry attempts (optional, default 3)
                - requests_per_second: Rate limit for requests per second (optional, default 2.0)

    Returns:
        Configured YahooFinanceAdapter instance
    """
    return YahooFinanceAdapter(
        enable_rate_limit=config.get('enable_rate_limit', True),
        max_retries=config.get('max_retries', 3),
        requests_per_second=config.get('requests_per_second', 2.0)
    )


if __name__ == "__main__":
    # This file defines the adapter - no runtime execution needed
    print("Yahoo Finance Market Data Adapter defined successfully")
    print("Implementation should be tested with actual yfinance data")
