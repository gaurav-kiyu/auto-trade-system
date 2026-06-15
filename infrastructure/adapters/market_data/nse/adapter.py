"""
NSE Market Data Adapter

This adapter implements the MarketDataPort interface for National Stock Exchange (NSE) data.
It provides market data retrieval using NSE's public APIs or available Python libraries.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Any

from core.datetime_ist import now_ist
from core.logging import LoggingService

# Import the market data port interface this adapter implements
try:
    from core.ports.market_data import MarketDataPort, Quote
except ImportError:
    # Fallback for type hints
    MarketDataPort = Any
    Quote = Any

# Try to import requests for better HTTP handling
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    # Fallback to urllib
    requests = None

# Try to import cloudscraper for bypassing NSE's Akamai/WAF protection
try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False
    cloudscraper = None

# Try to import nsepython library if available
try:
    from nsepython import nse_get_index_quote, nse_get_quote, nse_get_option_chain
    NSEPYTHON_AVAILABLE = True
except ImportError:
    NSEPYTHON_AVAILABLE = False
    # We'll implement our own NSE API calls


class NSEAdapter(MarketDataPort):
    """
    NSE market data adapter implementation.

    This adapter provides market data from India's National Stock Exchange (NSE)
    using available APIs and implements the MarketDataPort interface for clean architecture.
    """

    def __init__(self,
                 enable_rate_limit: bool = True,
                 max_retries: int = 3,
                 requests_per_second: float = 1.0,
                 use_nsepython: bool = True):
        """
        Initialize the NSE market data adapter.

        Args:
            enable_rate_limit: Whether to enable rate limiting
            max_retries: Maximum number of retry attempts for failed requests
            requests_per_second: Rate limit for requests per second (NSE is strict about rate limits)
            use_nsepython: Whether to use nsepython library if available
        """
        self._enable_rate_limit = enable_rate_limit
        self._max_retries = max_retries
        self._min_request_interval = 1.0 / requests_per_second if requests_per_second > 0 else 1.0  # Conservative for NSE
        self._last_request_time = 0
        self._use_nsepython = use_nsepython and NSEPYTHON_AVAILABLE

        # Headers to mimic a browser request (NSE blocks default Python user agents)
        self._headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        # Session for connection pooling
        # Priority: cloudscraper > requests > urllib
        self._session = None
        self._session_type = "none"
        if CLOUDSCRAPER_AVAILABLE:
            try:
                self._session = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "desktop": True},
                    delay=2,
                )
                self._session.headers.update(self._headers)
                self._session_type = "cloudscraper"
            except (OSError, ConnectionError, TimeoutError, ValueError, TypeError) as _init_err:
                self._session = None
                self._logger.warning(f"[NSE] Cloudscraper init failed: {_init_err}")
        if self._session is None and REQUESTS_AVAILABLE:
            self._session = requests.Session()
            self._session.headers.update(self._headers)
            self._session_type = "requests"

        # NSE session initialization state
        self._nse_session_initialized = False
        self._nse_session_init_time = 0.0
        self._nse_session_ttl = 300  # Re-init session every 5 minutes

        # Cache for symbol mappings and instrument data
        self._symbol_cache: dict[str, dict[str, Any]] = {}
        self._symbol_cache_time: dict[str, float] = {}
        self._cache_ttl = 300  # 5 minutes for symbol data

        self._logger = LoggingService(
            log_dir="logs",
            log_filename_prefix="nse_adapter_",
            retain_days=30,
            json_log_file="",
            version="UNKNOWN",
            enable_correlation_ids=False,
            enable_contextual_logging=False
        )
        self._logger.info("NSE market data adapter initialized")
        self._logger.info(f"Using session type: {self._session_type}")
        self._logger.info(f"Using nsepython library: {self._use_nsepython}")
        self._logger.info(f"Requests library available: {REQUESTS_AVAILABLE}")
        self._logger.info(f"Cloudscraper library available: {CLOUDSCRAPER_AVAILABLE}")

    def _get_logger(self):
        """Get logger instance."""
        return logging.getLogger(__name__)

    def _rate_limit(self):
        """Implement rate limiting to avoid API throttling."""
        if not self._enable_rate_limit:
            return

        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _init_nse_session(self) -> bool:
        """
        Initialize NSE session by visiting the homepage to obtain required cookies.
        NSE's anti-scraping measures require a valid session cookie obtained by
        first visiting the homepage before API endpoints will respond.

        Returns:
            True if session initialized successfully, False otherwise.
        """
        now = time.time()
        if self._nse_session_initialized and (now - self._nse_session_init_time) < self._nse_session_ttl:
            return True

        if not REQUESTS_AVAILABLE or not self._session:
            self._logger.warning("Cannot init NSE session: requests library not available")
            return False

        try:
            # Step 1: Visit homepage to get initial cookies
            self._logger.info("[NSE] Initializing session — visiting homepage")
            homepage_url = "https://www.nseindia.com"
            resp = self._session.get(
                homepage_url,
                timeout=15,
                headers={
                    **self._headers,
                    "Referer": "https://www.google.com/",
                },
            )
            resp.raise_for_status()

            # Step 2: Visit the market status page to get additional cookies
            # This is needed for the option chain API specifically
            market_status_url = "https://www.nseindia.com/market-data/market-status"
            self._session.get(
                market_status_url,
                timeout=10,
                headers={
                    **self._headers,
                    "Referer": homepage_url,
                },
            )

            # Update session headers with NSE cookies
            self._session.headers.update({
                "Referer": homepage_url,
                "Origin": "https://www.nseindia.com",
            })

            self._nse_session_initialized = True
            self._nse_session_init_time = now
            self._logger.info("[NSE] Session initialized successfully")
            return True

        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            self._logger.warning(f"[NSE] Failed to initialize session: {e}")
            self._nse_session_initialized = False
            return False

    def _make_request_with_retry(self, url: str, params: dict[str, Any] = None) -> Any:
        """
        Make an HTTP request with retry logic.

        Args:
            url: URL to request
            params: Query parameters (optional)

        Returns:
            Parsed JSON response or raw response

        Raises:
            Exception: If all retry attempts fail
        """
        last_exception = None
        for attempt in range(self._max_retries):
            try:
                self._rate_limit()

                if REQUESTS_AVAILABLE and self._session:
                    # Auto-init NSE session on first request or if TTL expired
                    if "nseindia.com" in url:
                        self._init_nse_session()

                    response = self._session.get(url, params=params, timeout=15)

                    # If we get a 404 or 403, the session may have expired — try re-init
                    if response.status_code in (403, 404) and "nseindia.com" in url:
                        self._logger.info(f"[NSE] Got {response.status_code} — re-initializing session")
                        self._nse_session_initialized = False
                        self._init_nse_session()
                        response = self._session.get(url, params=params, timeout=15)

                    response.raise_for_status()
                    return response.json()
                else:
                    # Fallback to urllib
                    full_url = url
                    if params:
                        from urllib.parse import urlencode
                        full_url = f"{url}?{urlencode(params)}"

                    req = urllib.request.Request(full_url, headers=self._headers)
                    with urllib.request.urlopen(req, timeout=15) as response:
                        data = response.read().decode('utf-8')
                        return json.loads(data)

            except (OSError, ConnectionError, TimeoutError, ValueError, TypeError, json.JSONDecodeError) as e:
                last_exception = e
                self._logger.warning(
                    f"[NSE] Request failed (attempt {attempt + 1}/{self._max_retries}, "
                    f"session={self._session_type}): {type(e).__name__}: {e}"
                )
                if attempt < self._max_retries - 1:
                    # Exponential backoff with longer delays for NSE (they're strict)
                    wait_time = (2 ** attempt) * 2.0  # Start with 2 seconds
                    time.sleep(wait_time)
                else:
                    raise
        raise last_exception

    def _get_nse_symbol(self, symbol: str) -> str:
        """
        Convert a trading symbol to NSE format.

        Args:
            symbol: Trading symbol (e.g., "NIFTY", "RELIANCE")

        Returns:
            NSE-formatted symbol
        """
        # Handle indices
        if symbol.upper() == "NIFTY":
            return "NIFTY 50"
        elif symbol.upper() == "BANKNIFTY":
            return "NIFTY BANK"
        elif symbol.upper() == "FINNIFTY":
            return "NIFTY FIN SERVICE"

        # For stocks, return as-is (NSE expects the symbol)
        return symbol.upper()

    def _convert_to_quote(self, symbol: str, data: dict[str, Any]) -> Quote:
        """
        Convert NSE API data to Quote object.

        Args:
            symbol: Trading symbol
            data: Dictionary containing quote data from NSE API

        Returns:
            Quote object
        """
        # Extract data with fallbacks for different API response formats
        bid = float(data.get('bidPrice', data.get('bid', data.get('bp', 0.0))) or 0.0)
        ask = float(data.get('askPrice', data.get('ask', data.get('sp', 0.0))) or 0.0)
        last_price = float(data.get('lastPrice', data.get('ltp', data.get('last', 0.0))) or 0.0)
        volume = int(data.get('volume', data.get('tradedVolume', data.get('volume', 0))) or 0)

        # If we don't have bid/ask, estimate from last price
        if bid == 0.0 and ask == 0.0 and last_price > 0:
            spread = last_price * 0.0005  # 0.05% spread
            bid = last_price - spread / 2
            ask = last_price + spread / 2

        return Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=last_price,
            volume=volume,
            timestamp=now_ist()
        )

    def connect(self) -> bool:
        """
        Establish connection to the market data provider.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Test connection by getting data for a well-known symbol
            if self._use_nsepython:
                # Test nsepython
                try:
                    data = nse_get_index_quote("NIFTY 50")
                    return data is not None
                except (KeyError, TypeError, ValueError, IndexError):
                    pass

            # Test direct API
            url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
            data = self._make_request_with_retry(url)
            return data is not None and len(str(data)) > 0
        except (OSError, ConnectionError, TimeoutError, ValueError, json.JSONDecodeError) as e:
            self._logger.warning(f"Failed to connect to NSE: {e}")
            return False

    def disconnect(self) -> None:
        """Close connection to the market data provider."""
        # Close session if using requests
        if self._session:
            self._session.close()
            self._session = None

        # Clear caches
        self._symbol_cache.clear()
        self._symbol_cache_time.clear()

    def get_quote(self, symbol: str) -> Quote:
        """
        Get current quote for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Quote object with bid, ask, last price, etc.
        """
        try:
            nse_symbol = self._get_nse_symbol(symbol)

            # Try nsepython first if available and enabled
            if self._use_nsepython:
                try:
                    if nse_symbol in ["NIFTY 50", "NIFTY BANK", "NIFTY FIN SERVICE"]:
                        # Index quote
                        data = nse_get_index_quote(nse_symbol)
                        if data:
                            return self._convert_to_quote(symbol, data)
                    else:
                        # Stock quote
                        data = nse_get_quote(nse_symbol)
                        if data:
                            return self._convert_to_quote(symbol, data)
                except (KeyError, TypeError, ValueError, IndexError, OSError, ConnectionError) as e:
                    logger = self._get_logger()
                    self._logger.debug(f"nsepython failed for {symbol}: {e}")
                    # Fall back to direct API

            # Fallback to direct NSE API
            # For indices
            if nse_symbol in ["NIFTY 50", "NIFTY BANK", "NIFTY FIN SERVICE"]:
                url_map = {
                    "NIFTY 50": "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050",
                    "NIFTY BANK": "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20BANK",
                    "NIFTY FIN SERVICE": "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20FIN%20SERVICE"
                }
                url = url_map.get(nse_symbol)
                if url:
                    data = self._make_request_with_retry(url)
                    # NSE indices API returns data under 'data' array
                    if data and isinstance(data, dict) and 'data' in data and len(data['data']) > 0:
                        return self._convert_to_quote(symbol, data['data'][0])
            else:
                # For stocks/equities
                url = f"https://www.nseindia.com/api/quote-equity?symbol={nse_symbol}"
                data = self._make_request_with_retry(url)
                if data and isinstance(data, dict):
                    # NSE equity API has data under various keys
                    quote_data = (
                        data.get('priceInfo') or
                        data.get('metadata') or
                        data.get('info') or
                        data
                    )
                    if quote_data:
                        return self._convert_to_quote(symbol, quote_data)

            # If we got here, we didn't get valid data
            logger = self._get_logger()
            self._logger.warning(f"No valid quote data received for {symbol}")

        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError) as e:
            logger = self._get_logger()
            self._logger.error(f"Failed to get quote for {symbol}: {e}")

        # Return empty quote on failure
        return Quote(
            symbol=symbol,
            bid=0.0,
            ask=0.0,
            last=0.0,
            volume=0,
            timestamp=now_ist()
        )

    def get_latest_data(self, symbol: str) -> Any:
        """
        Get latest market data for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Market data structure (implementation-specific)
            For NSE, returns the raw API response dict
        """
        try:
            # For simplicity, we'll reuse get_quote logic but return raw data
            quote = self.get_quote(symbol)
            # Return a dict representation that indicates we have data
            return {
                'symbol': symbol,
                'bid': quote.bid,
                'ask': quote.ask,
                'last': quote.last,
                'volume': quote.volume,
                'timestamp': quote.timestamp.isoformat()
            }
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError, KeyError) as e:
            logger = self._get_logger()
            self._logger.error(f"Failed to get latest data for {symbol}: {e}")
            return {}

    def is_data_fresh(self, market_data: Any, max_age_seconds: int = 30) -> bool:
        """
        Check if market data is fresh enough for trading decisions.

        Args:
            market_data: Market data structure from get_latest_data
            max_age_seconds: Maximum age in seconds for data to be considered fresh

        Returns:
            True if data is fresh, False otherwise
        """
        if isinstance(market_data, dict) and 'timestamp' in market_data:
            try:
                data_time = datetime.fromisoformat(market_data['timestamp'].replace('Z', '+00:00'))
                age_seconds = (now_ist() - data_time.replace(tzinfo=None)).total_seconds()
                return age_seconds <= max_age_seconds
            except (KeyError, TypeError, ValueError, IndexError):
                pass
        # If we can't determine freshness, assume it's fresh if we have data
        return bool(market_data)

    def subscribe_to_market_data(
        self,
        symbols: list[str],
        callback: Callable[[Any], None]
    ) -> bool:
        """
        Subscribe to real-time market data for symbols.

        Note: NSE does not provide free real-time WebSocket data to retail users
        in the standard API. This would require implementing polling
        or using NSE's official WebSocket (which requires licensing).

        Args:
            symbols: List of symbols to subscribe to
            callback: Function to call when market data arrives

        Returns:
            True if subscription setup successful, False otherwise
        """
        # For NSE, we can't provide true real-time subscriptions via standard API
        # without implementing our own polling mechanism or using licensed WebSocket
        # A full implementation would:
        # 1. Start a background thread for each symbol
        # 2. Periodically fetch quote data (respecting rate limits)
        # 3. Call the callback with new data
        # 4. Handle unsubscription cleanup
        #
        # For this implementation, we'll return False to indicate
        # that real-time subscriptions are not supported via this method
        logger = self._get_logger()
        self._logger.info("NSE adapter does not support real-time subscriptions via standard API")
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
            to_date: End date for historical date
            interval: Data interval (minute, 3minute, 5minute, 15minute, 30minute, 60minute, day)

        Returns:
            List of historical data candles
        """
        try:
            # NSE historical data via API is limited; we'll use yfinance as fallback for now
            # In a production system, you might want to:
            # 1. Use NSE's historical data FTP (requires license)
            # 2. Use a third-party provider with NSE data
            # 3. Store your own historical data from daily downloads

            logger = self._get_logger()
            self._logger.info(f"Fetching historical data for {symbol} from {from_date} to {to_date}")

            # For now, we'll fall back to a simulated response or suggest using yfinance
            # This is a limitation of the free NSE API
            return self._get_fallback_historical_data(symbol, from_date, to_date, interval)

        except RuntimeError:
            raise
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError, KeyError) as e:
            logger = self._get_logger()
            self._logger.error(f"Failed to get historical data for {symbol}: {e}")
            return []

    def _get_fallback_historical_data(self, symbol: str, from_date: datetime, to_date: datetime, interval: str) -> list[dict[str, Any]]:
        """
        Get fallback historical data when NSE API is insufficient.
        Uses yfinance or simulation.
        """
        # Try to use yfinance if available as a fallback
        try:
            import pandas as pd
            import yfinance as yf

            # Convert symbol to yfinance format
            yf_symbol = symbol
            if symbol.upper() in ['NIFTY', 'BANKNIFTY', 'FINNIFTY']:
                yf_symbol = f"^{symbol.upper()}.NS" if symbol.upper() == 'NIFTY' else f"^{symbol.upper()}.NS"
            elif not symbol.endswith('.NS') and not symbol.endswith('.BO'):
                # Assume it's an Indian stock
                yf_symbol = f"{symbol}.NS"

            ticker = yf.Ticker(yf_symbol)

            # Map interval
            yf_interval = {
                "minute": "1m",
                "3minute": "30m",  # Approximation
                "5minute": "5m",
                "15minute": "15m",
                "30minute": "30m",
                "60minute": "60m",
                "day": "1d",
                "week": "1wk",
                "month": "1mo"
            }.get(interval, "1d")

            # Get historical data
            hist_data = ticker.history(
                start=from_date,
                end=to_date,
                interval=yf_interval
            )

            if hist_data.empty:
                raise ValueError("No data returned from yfinance")

            # Convert to our format
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

        except ImportError:
            pass  # yfinance not available
        except (ValueError, TypeError, OSError, KeyError, RuntimeError) as e:
            logger = self._get_logger()
            self._logger.warning(f"yfinance fallback failed for {symbol}: {e}")

        # Final fallback: simulate historical data
        return self._simulate_historical_data(symbol, from_date, to_date, interval)

    def _simulate_historical_data(self, symbol: str, from_date: datetime, to_date: datetime, interval: str) -> list[dict[str, Any]]:
        self._logger.critical(
            f"NSE API and yfinance both failed for {symbol} - "
            "cannot provide simulated data for trading. "
            "This would have returned fictional random data."
        )
        raise RuntimeError(
            f"NSE API and yfinance both failed for {symbol} - "
            "cannot provide simulated data for trading"
        )

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
            # Try nsepython for option chain
            if self._use_nsepython:
                try:
                    nse_symbol = self._get_nse_symbol(symbol)
                    if expiry_date:
                        # Format date for nsepython
                        date_str = expiry_date.strftime("%d-%b-%Y").upper()
                        data = nse_get_option_chain(nse_symbol, date_str)
                    else:
                        data = nse_get_option_chain(nse_symbol)

                    if data:
                        return self._parse_option_chain_data(data, symbol)
                except (KeyError, TypeError, ValueError, IndexError, OSError, ConnectionError) as e:
                    logger = self._get_logger()
                    self._logger.debug(f"nsepython option chain failed for {symbol}: {e}")

            # Fallback to direct API
            # Fallback to direct API
            self._logger.info(f"Fetching option chain for {symbol} via direct API")

            # For NSE indices, we need to use the correct symbol
            if symbol.upper() == "NIFTY":
                nse_symbol = "NIFTY"
            elif symbol.upper() == "BANKNIFTY":
                nse_symbol = "BANKNIFTY"
            elif symbol.upper() == "FINNIFTY":
                nse_symbol = "FINNIFTY"
            else:
                nse_symbol = symbol

            # NSE option chain API
            url = f"https://www.nseindia.com/api/option-chain-indices?symbol={nse_symbol}"
            data = self._make_request_with_retry(url)

            if data:
                return self._parse_option_chain_data(data, symbol)

        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError) as e:
            logger = self._get_logger()
            self._logger.error(f"Failed to get option chain for {symbol}: {e}")

        return []

    def _parse_option_chain_data(self, data: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        """
        Parse option chain data from NSE API response.

        Args:
            data: Raw option chain data from NSE API
            symbol: Underlying symbol

        Returns:
            List of option contracts
        """
        result = []

        try:
            # NSE option chain data structure
            if 'records' in data and 'data' in data['records']:
                options_data = data['records']['data']

                for item in options_data:
                    strike_price = float(item.get('strikePrice', 0))

                    # Process CALL options
                    if 'CE' in item:
                        ce_data = item['CE']
                        result.append({
                            'symbol': f"{symbol}{int(strike_price)}{ce_data.get('identifier', '')[-2:] if ce_data.get('identifier') else 'CE'}",
                            'strike': strike_price,
                            'lastPrice': float(ce_data.get('lastPrice', 0.0)),
                            'bid': float(ce_data.get('bidPrice', 0.0)),
                            'ask': float(ce_data.get('askPrice', 0.0)),
                            'volume': int(ce_data.get('totalTradedVolume', 0)),
                            'openInterest': int(ce_data.get('openInterest', 0)),
                            'impliedVolatility': float(ce_data.get('impliedVolatility', 0.0)) if ce_data.get('impliedVolatility') else 0.0,
                            'inTheMoney': bool(ce_data.get('pChangeinOpenInterest', 0) > 0),  # Simplified
                            'optionType': 'CALL'
                        })

                    # Process PUT options
                    if 'PE' in item:
                        pe_data = item['PE']
                        result.append({
                            'symbol': f"{symbol}{int(strike_price)}{pe_data.get('identifier', '')[-2:] if pe_data.get('identifier') else 'PE'}",
                            'strike': strike_price,
                            'lastPrice': float(pe_data.get('lastPrice', 0.0)),
                            'bid': float(pe_data.get('bidPrice', 0.0)),
                            'ask': float(pe_data.get('askPrice', 0.0)),
                            'volume': int(pe_data.get('totalTradedVolume', 0)),
                            'openInterest': int(pe_data.get('openInterest', 0)),
                            'impliedVolatility': float(pe_data.get('impliedVolatility', 0.0)) if pe_data.get('impliedVolatility') else 0.0,
                            'inTheMoney': bool(pe_data.get('pChangeinOpenInterest', 0) > 0),  # Simplified
                            'optionType': 'PUT'
                        })

        except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError) as e:
            self._logger.error(f"Failed to parse option chain data: {e}")

        return result

    def get_instrument_details(self, symbol: str) -> dict[str, Any]:
        """
        Get instrument details for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Dictionary containing instrument details like lot size, tick size, etc.
        """
        try:
            # Try to get instrument details from NSE API
            if self._use_nsepython:
                try:
                    nse_symbol = self._get_nse_symbol(symbol)
                    # Try to get metadata
                    if nse_symbol in ["NIFTY 50", "NIFTY BANK", "NIFTY FIN SERVICE"]:
                        # For indices, we might need a different approach
                        pass
                    else:
                        # For stocks
                        data = nse_get_quote(nse_symbol)
                        if data:
                            info = {
                                'symbol': symbol,
                                'name': data.get('info', {}).get('companyName', data.get('companyName', '')),
                                'exchange': 'NSE',
                                'currency': 'INR',
                                'market': data.get('info', {}).get('marketType', ''),
                                'sector': data.get('info', {}).get('industry', ''),
                                'industry': data.get('info', {}).get('industry', ''),
                                'lotSize': int(data.get('marketLot', {}).get('marketLot', 1)) if data.get('marketLot') else 1,
                                'tickSize': float(data.get('priceBands', {}).get('lowerBand', 0.05)) if data.get('priceBands') else 0.05,
                                'isin': data.get('info', {}).get('isin', ''),
                                'faceValue': float(data.get('info', {}).get('faceValue', 10.0)) if data.get('info', {}).get('faceValue') else 10.0,
                                'paidUpValue': float(data.get('info', {}).get('paidUpValue', 10.0)) if data.get('info', {}).get('paidUpValue') else 10.0,
                                'marketCap': float(data.get('marketCap', 0)) if data.get('marketCap') else 0,
                            }
                            return info
                except (KeyError, TypeError, ValueError, IndexError, OSError, ConnectionError) as e:
                    self._logger.debug(f"nsepython instrument details failed for {symbol}: {e}")

            # Fallback: return basic details
            return {
                'symbol': symbol,
                'name': symbol,
                'exchange': 'NSE',
                'currency': 'INR',
                'market': 'EQ',
                'sector': 'UNKNOWN',
                'industry': 'UNKNOWN',
                'lotSize': 1,
                'tickSize': 0.05,
                'isin': '',
                'marketCap': 0,
            }

        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError, KeyError) as e:
            logger = self._get_logger()
            self._logger.error(f"Failed to get instrument details for {symbol}: {e}")
            return {}


# Factory function for creating NSE market data adapter instances
def create_nse_adapter(config: dict[str, Any]) -> NSEAdapter:
    """
    Factory function to create an NSEAdapter from configuration.

    Args:
        config: Configuration dictionary containing:
                - enable_rate_limit: Whether to enable rate limiting (optional, default True)
                - max_retries: Maximum retry attempts (optional, default 3)
                - requests_per_second: Rate limit for requests per second (optional, default 1.0)
                - use_nsepython: Whether to use nsepython library if available (optional, default True)

    Returns:
        Configured NSEAdapter instance
    """
    return NSEAdapter(
        enable_rate_limit=config.get('enable_rate_limit', True),
        max_retries=config.get('max_retries', 3),
        requests_per_second=config.get('requests_per_second', 1.0),
        use_nsepython=config.get('use_nsepython', True)
    )


if __name__ == "__main__":
    # This file defines the adapter - no runtime execution needed
    print("NSE Market Data Adapter defined successfully")
    print("Implementation should be tested with actual NSE data")
