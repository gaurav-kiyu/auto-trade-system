"""
Market Reference Data Service

This service provides dynamic resolution of exchange-governed parameters such as:
- Lot sizes
- Expiry dates
- Market holidays
- Margin requirements

It fetches data from authoritative sources (NSE, etc.) with validation, caching,
staleness detection, and safe fallbacks to ensure the system remains functional
even when external sources are unavailable.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LotSizeInfo:
    """Information about lot size for a symbol."""
    symbol: str
    lot_size: int
    effective_from: date  # Date from which this lot size is effective
    note: str = ""  # Any additional information


@dataclass(frozen=True)
class ExpiryInfo:
    """Information about expiry dates for a symbol."""
    symbol: str
    expiry_dates: List[date]  # List of expiry dates
    expiry_type: str = ""  # e.g., "WEEKLY", "MONTHLY", "QUARTERLY"
    note: str = ""


@dataclass(frozen=True)
class HolidayInfo:
    """Information about market holidays."""
    holiday_date: date
    description: str = ""
    exchange: str = ""  # e.g., "NSE", "BSE"
    note: str = ""


@dataclass
class MarginInfo:
    """Information about margin requirements."""
    symbol: str
    margin_type: str  # e.g., "SPAN", "EXPOSURE", "PREMIUM"
    margin_value: float  # Percentage or absolute value
    currency: str = "INR"
    effective_from: date = field(default_factory=date.today)
    note: str = ""


class ReferenceDataError(Exception):
    """Custom exception for reference data errors."""
    pass


class ReferenceDataService:
    """
    Service for dynamically resolving exchange-governed reference data.

    Features:
    - Fetches data from authoritative sources (NSE API, etc.)
    - Caches data with configurable TTL
    - Validates data for correctness
    - Provides safe fallbacks to last known good data or defaults
    - Thread-safe access
    """

    def __init__(self,
                 data_engine: Optional[DataEngine] = None,
                 cache_ttl: Dict[str, float] = None,
                 enable_fallback_to_file: bool = True,
                 fallback_file_dir: Optional[Path] = None):
        """
        Initialize the reference data service.

        Args:
            data_engine: DataEngine instance for fetching data (optional)
            cache_ttl: Dictionary mapping data type to TTL in seconds
                      (e.g., {'lot_size': 86400, 'expiry': 86400, 'holiday': 31536000})
            enable_fallback_to_file: Whether to cache data to disk for fallback
            fallback_file_dir: Directory to store fallback data files
        """
        self._lock = threading.RLock()
        self._data_engine = data_engine
        self._enable_fallback_to_file = enable_fallback_to_file
        self._fallback_file_dir = fallback_file_dir or (Path.home() / ".opb" / "reference_data")

        # Set up cache TTLs (default values)
        self._cache_ttl: Dict[str, float] = {
            'lot_size': 86400.0,      # 1 day
            'expiry': 86400.0,        # 1 day
            'holiday': 31536000.0,    # 1 year
            'margin': 604800.0,       # 1 week
        }
        if cache_ttl:
            self._cache_ttl.update(cache_ttl)

        # In-memory caches
        self._lot_sizes: Dict[str, LotSizeInfo] = {}
        self._expiries: Dict[str, ExpiryInfo] = {}
        self._holidays: Set[HolidayInfo] = set()
        self._margins: Dict[str, List[MarginInfo]] = {}

        # Timestamps for when data was last updated
        self._last_updated: Dict[str, float] = {}

        # Flags to track if we have ever successfully loaded data
        self._has_ever_loaded: Dict[str, bool] = {
            'lot_size': False,
            'expiry': False,
            'holiday': False,
            'margin': False
        }

        # Ensure fallback directory exists if needed
        if self._enable_fallback_to_file:
            self._fallback_file_dir.mkdir(parents=True, exist_ok=True)

        # Load initial data
        self._refresh_all_data()

    def _get_cache_key(self, data_type: str, identifier: Optional[str] = None) -> str:
        """Generate a cache key for the given data type and optional identifier."""
        if identifier:
            return f"refdata:{data_type}:{identifier}"
        return f"refdata:{data_type}"

    def _is_data_fresh(self, data_type: str) -> bool:
        """Check if the cached data for the given type is still fresh."""
        last_updated = self._last_updated.get(data_type, 0)
        ttl = self._cache_ttl.get(data_type, 3600.0)  # Default 1 hour if not specified
        return (time.time() - last_updated) < ttl

    def _save_to_fallback_file(self, data_type: str, data: Any) -> None:
        """Save data to a fallback file for persistent storage."""
        if not self._enable_fallback_to_file or not self._fallback_file_dir:
            return

        try:
            file_path = self._fallback_file_dir / f"{data_type}.json"
            # Convert data to a serializable format
            serializable_data = self._serialize_for_fallback(data_type, data)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(serializable_data, f, indent=2, default=str)
            logger.debug(f"Saved {data_type} reference data to fallback file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to save {data_type} reference data to fallback file: {e}")

    def _load_from_fallback_file(self, data_type: str) -> Optional[Any]:
        """Load data from a fallback file if available."""
        if not self._enable_fallback_to_file or not self._fallback_file_dir:
            return None

        try:
            file_path = self._fallback_file_dir / f"{data_type}.json"
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.debug(f"Loaded {data_type} reference data from fallback file: {file_path}")
                return self._deserialize_from_fallback(data_type, data)
        except Exception as e:
            logger.warning(f"Failed to load {data_type} reference data from fallback file: {e}")
        return None

    def _serialize_for_fallback(self, data_type: str, data: Any) -> Any:
        """Convert data to a JSON-serializable format for fallback storage."""
        if data_type == 'lot_size':
            return {symbol: {
                'lot_size': info.lot_size,
                'effective_from': info.effective_from.isoformat(),
                'note': info.note
            } for symbol, info in data.items()}
        elif data_type == 'expiry':
            return {symbol: {
                'expiry_dates': [d.isoformat() for d in info.expiry_dates],
                'expiry_type': info.expiry_type,
                'note': info.note
            } for symbol, info in data.items()}
        elif data_type == 'holiday':
            return [{
                'holiday_date': h.holiday_date.isoformat(),
                'description': h.description,
                'exchange': h.exchange,
                'note': h.note
            } for h in data]
        elif data_type == 'margin':
            return {symbol: [{
                'margin_type': m.margin_type,
                'margin_value': m.margin_value,
                'currency': m.currency,
                'effective_from': m.effective_from.isoformat(),
                'note': m.note
            } for m in info] for symbol, info in data.items()}
        else:
            return data

    def _deserialize_from_fallback(self, data_type: str, data: Any) -> Any:
        """Convert data from JSON format back to internal representation."""
        if data_type == 'lot_size':
            result = {}
            for symbol, info_dict in data.items():
                result[symbol] = LotSizeInfo(
                    symbol=symbol,
                    lot_size=info_dict['lot_size'],
                    effective_from=date.fromisoformat(info_dict['effective_from']),
                    note=info_dict.get('note', '')
                )
            return result
        elif data_type == 'expiry':
            result = {}
            for symbol, info_dict in data.items():
                result[symbol] = ExpiryInfo(
                    symbol=symbol,
                    expiry_dates=[date.fromisoformat(d) for d in info_dict['expiry_dates']],
                    expiry_type=info_dict.get('expiry_type', ''),
                    note=info_dict.get('note', '')
                )
            return result
        elif data_type == 'holiday':
            result = set()
            for h_dict in data:
                result.add(HolidayInfo(
                    holiday_date=date.fromisoformat(h_dict['holiday_date']),
                    description=h_dict.get('description', ''),
                    exchange=h_dict.get('exchange', ''),
                    note=h_dict.get('note', '')
                ))
            return result
        elif data_type == 'margin':
            result = {}
            for symbol, margin_list in data.items():
                result[symbol] = []
                for m_dict in margin_list:
                    result[symbol].append(MarginInfo(
                        symbol=symbol,
                        margin_type=m_dict['margin_type'],
                        margin_value=m_dict['margin_value'],
                        currency=m_dict.get('currency', 'INR'),
                        effective_from=date.fromisoformat(m_dict['effective_from']),
                        note=m_dict.get('note', '')
                    ))
            return result
        else:
            return data

    def _fetch_lot_sizes_from_source(self) -> Dict[str, LotSizeInfo]:
        """
        Fetch lot sizes from the authoritative source.

        This is a placeholder implementation. In a real system, this would:
        1. Call the NSE API or download the lot size CSV from NSE website
        2. Parse the response
        3. Validate the data
        4. Return a dictionary mapping symbol to LotSizeInfo

        For now, we return an empty dict to indicate that we need to implement
        the actual fetching logic based on the available data sources in the system.
        """
        logger.info("Fetching lot sizes from authoritative source (placeholder)")
        # TODO: Implement actual fetching from NSE API or other source
        # For now, we'll return an empty dict to trigger fallback behavior
        return {}

    def _fetch_expiries_from_source(self) -> Dict[str, ExpiryInfo]:
        """
        Fetch expiry dates from the authoritative source.

        Placeholder implementation.
        """
        logger.info("Fetching expiry dates from authoritative source (placeholder)")
        return {}

    def _fetch_holidays_from_source(self) -> Set[HolidayInfo]:
        """
        Fetch market holidays from the authoritative source.

        Placeholder implementation.
        """
        logger.info("Fetching market holidays from authoritative source (placeholder)")
        return set()

    def _fetch_margins_from_source(self) -> Dict[str, List[MarginInfo]]:
        """
        Fetch margin requirements from the authoritative source.

        Placeholder implementation.
        """
        logger.info("Fetching margin requirements from authoritative source (placeholder)")
        return {}

    def _validate_lot_sizes(self, data: Dict[str, LotSizeInfo]) -> Tuple[bool, str]:
        """Validate lot size data."""
        if not isinstance(data, dict):
            return False, "Lot sizes data is not a dictionary"

        for symbol, info in data.items():
            if not isinstance(info, LotSizeInfo):
                return False, f"Invalid lot size info for symbol {symbol}"
            if info.lot_size <= 0:
                return False, f"Lot size must be positive for symbol {symbol}: {info.lot_size}"
            if not isinstance(info.effective_from, date):
                return False, f"Invalid effective_from date for symbol {symbol}"

        return True, ""

    def _validate_expiries(self, data: Dict[str, ExpiryInfo]) -> Tuple[bool, str]:
        """Validate expiry data."""
        if not isinstance(data, dict):
            return False, "Expiries data is not a dictionary"

        for symbol, info in data.items():
            if not isinstance(info, ExpiryInfo):
                return False, f"Invalid expiry info for symbol {symbol}"
            if not info.expiry_dates:
                return False, f"No expiry dates provided for symbol {symbol}"
            for expiry_date in info.expiry_dates:
                if not isinstance(expiry_date, date):
                    return False, f"Invalid expiry date for symbol {symbol}: {expiry_date}"
                if expiry_date < date.today():
                    # Allow historical expiries but warn
                    logger.warning(f"Historical expiry date found for {symbol}: {expiry_date}")

        return True, ""

    def _validate_holidays(self, data: Set[HolidayInfo]) -> Tuple[bool, str]:
        """Validate holiday data."""
        if not isinstance(data, set):
            return False, "Holidays data is not a set"

        for h in data:
            if not isinstance(h, HolidayInfo):
                return False, f"Invalid holiday info: {h}"
            if not isinstance(h.holiday_date, date):
                return False, f"Invalid holiday date: {h.holiday_date}"

        return True, ""

    def _validate_margins(self, data: Dict[str, List[MarginInfo]]) -> Tuple[bool, str]:
        """Validate margin data."""
        if not isinstance(data, dict):
            return False, "Margins data is not a dictionary"

        for symbol, margin_list in data.items():
            if not isinstance(margin_list, list):
                return False, f"Margin info for symbol {symbol} is not a list"
            for m in margin_list:
                if not isinstance(m, MarginInfo):
                    return False, f"Invalid margin info for symbol {symbol}: {m}"
                if m.margin_value < 0:
                    return False, f"Margin value cannot be negative for symbol {symbol}: {m.margin_value}"

        return True, ""

    def _refresh_lot_sizes(self) -> bool:
        """Refresh lot size data from the source."""
        try:
            logger.debug("Refreshing lot size data")
            new_data = self._fetch_lot_sizes_from_source()

            # If we got no data from the source, try to load from fallback
            if not new_data:
                logger.warning("No lot size data received from source, trying fallback")
                fallback_data = self._load_from_fallback_file('lot_size')
                if fallback_data is not None:
                    new_data = fallback_data
                    logger.info("Loaded lot size data from fallback file")
                else:
                    logger.error("Failed to get lot size data from source and no fallback available")
                    return False

            # Validate the data
            is_valid, error_msg = self._validate_lot_sizes(new_data)
            if not is_valid:
                logger.error(f"Lot size data validation failed: {error_msg}")
                # Try to use fallback data if validation fails
                fallback_data = self._load_from_fallback_file('lot_size')
                if fallback_data is not None:
                    is_valid, error_msg = self._validate_lot_sizes(fallback_data)
                    if is_valid:
                        logger.info("Using fallback lot size data after validation failure")
                        new_data = fallback_data
                    else:
                        logger.error(f"Fallback lot size data also invalid: {error_msg}")
                        return False
                else:
                    return False

            # Update the cache
            with self._lock:
                self._lot_sizes = new_data
                self._last_updated['lot_size'] = time.time()
                self._has_ever_loaded['lot_size'] = True

            # Save to fallback file for future use
            self._save_to_fallback_file('lot_size', new_data)

            logger.info(f"Successfully refreshed lot size data for {len(new_data)} symbols")
            return True

        except Exception as e:
            logger.error(f"Error refreshing lot size data: {e}")
            return False

    def _refresh_expiries(self) -> bool:
        """Refresh expiry data from the source."""
        try:
            logger.debug("Refreshing expiry data")
            new_data = self._fetch_expiries_from_source()

            if not new_data:
                logger.warning("No expiry data received from source, trying fallback")
                fallback_data = self._load_from_fallback_file('expiry')
                if fallback_data is not None:
                    new_data = fallback_data
                    logger.info("Loaded expiry data from fallback file")
                else:
                    logger.error("Failed to get expiry data from source and no fallback available")
                    return False

            # Validate the data
            is_valid, error_msg = self._validate_expiries(new_data)
            if not is_valid:
                logger.error(f"Expiry data validation failed: {error_msg}")
                fallback_data = self._load_from_fallback_file('expiry')
                if fallback_data is not None:
                    is_valid, error_msg = self._validate_lot_sizes(fallback_data)  # Reuse validation for now
                    if is_valid:
                        logger.info("Using fallback expiry data after validation failure")
                        new_data = fallback_data
                    else:
                        logger.error(f"Fallback expiry data also invalid: {error_msg}")
                        return False
                else:
                    return False

            # Update the cache
            with self._lock:
                self._expiries = new_data
                self._last_updated['expiry'] = time.time()
                self._has_ever_loaded['expiry'] = True

            # Save to fallback file
            self._save_to_fallback_file('expiry', new_data)

            logger.info(f"Successfully refreshed expiry data for {len(new_data)} symbols")
            return True

        except Exception as e:
            logger.error(f"Error refreshing expiry data: {e}")
            return False

    def _refresh_holidays(self) -> bool:
        """Refresh holiday data from the source."""
        try:
            logger.debug("Refreshing holiday data")
            new_data = self._fetch_holidays_from_source()

            if not new_data:
                logger.warning("No holiday data received from source, trying fallback")
                fallback_data = self._load_from_fallback_file('holiday')
                if fallback_data is not None:
                    new_data = fallback_data
                    logger.info("Loaded holiday data from fallback file")
                else:
                    logger.error("Failed to get holiday data from source and no fallback available")
                    return False

            # Validate the data
            is_valid, error_msg = self._validate_holidays(new_data)
            if not is_valid:
                logger.error(f"Holiday data validation failed: {error_msg}")
                fallback_data = self._load_from_fallback_file('holiday')
                if fallback_data is not None:
                    is_valid, error_msg = self._validate_holidays(fallback_data)
                    if is_valid:
                        logger.info("Using fallback holiday data after validation failure")
                        new_data = fallback_data
                    else:
                        logger.error(f"Fallback holiday data also invalid: {error_msg}")
                        return False
                else:
                    return False

            # Update the cache
            with self._lock:
                self._holidays = new_data
                self._last_updated['holiday'] = time.time()
                self._has_ever_loaded['holiday'] = True

            # Save to fallback file
            self._save_to_fallback_file('holiday', new_data)

            logger.info(f"Successfully refreshed holiday data: {len(new_data)} holidays")
            return True

        except Exception as e:
            logger.error(f"Error refreshing holiday data: {e}")
            return False

    def _refresh_margins(self) -> bool:
        """Refresh margin data from the source."""
        try:
            logger.debug("Refreshing margin data")
            new_data = self._fetch_margins_from_source()

            if not new_data:
                logger.warning("No margin data received from source, trying fallback")
                fallback_data = self._load_from_fallback_file('margin')
                if fallback_data is not None:
                    new_data = fallback_data
                    logger.info("Loaded margin data from fallback file")
                else:
                    logger.error("Failed to get margin data from source and no fallback available")
                    return False

            # Validate the data
            is_valid, error_msg = self._validate_margins(new_data)
            if not is_valid:
                logger.error(f"Margin data validation failed: {error_msg}")
                fallback_data = self._load_from_fallback_file('margin')
                if fallback_data is not None:
                    is_valid, error_msg = self._validate_margins(fallback_data)
                    if is_valid:
                        logger.info("Using fallback margin data after validation failure")
                        new_data = fallback_data
                    else:
                        logger.error(f"Fallback margin data also invalid: {error_msg}")
                        return False
                else:
                    return False

            # Update the cache
            with self._lock:
                self._margins = new_data
                self._last_updated['margin'] = time.time()
                self._has_ever_loaded['margin'] = True

            # Save to fallback file
            self._save_to_fallback_file('margin', new_data)

            logger.info(f"Successfully refreshed margin data for {len(new_data)} symbols")
            return True

        except Exception as e:
            logger.error(f"Error refreshing margin data: {e}")
            return False

    def _refresh_all_data(self) -> None:
        """Refresh all reference data types."""
        logger.info("Refreshing all reference data...")
        self._refresh_lot_sizes()
        self._refresh_expiries()
        self._refresh_holidays()
        self._refresh_margins()
        logger.info("Finished refreshing all reference data")

    def get_lot_size(self, symbol: str) -> Optional[int]:
        """
        Get the lot size for a given symbol.

        Returns:
            The lot size as an integer, or None if not available.
        """
        with self._lock:
            # Check if we have ever loaded data; if not, try to load now
            if not self._has_ever_loaded['lot_size']:
                self._refresh_lot_sizes()

            # Check if data is fresh; if not, try to refresh
            if not self._is_data_fresh('lot_size'):
                self._refresh_lot_sizes()

            info = self._lot_sizes.get(symbol)
            return info.lot_size if info else None

    def get_expiry_dates(self, symbol: str) -> Optional[List[date]]:
        """
        Get the expiry dates for a given symbol.

        Returns:
            A list of expiry dates, or None if not available.
        """
        with self._lock:
            if not self._has_ever_loaded['expiry']:
                self._refresh_expiries()

            if not self._is_data_fresh('expiry'):
                self._refresh_expiries()

            info = self._expiries.get(symbol)
            return info.expiry_dates if info else None

    def get_holidays(self) -> Optional[Set[date]]:
        """
        Get the set of market holiday dates.

        Returns:
            A set of dates representing market holidays, or None if not available.
        """
        with self._lock:
            if not self._has_ever_loaded['holiday']:
                self._refresh_holidays()

            if not self._is_data_fresh('holiday'):
                self._refresh_holidays()

            return {h.holiday_date for h in self._holidays} if self._holidays else None

    def is_market_open(self, check_date: Optional[date] = None) -> bool:
        """
        Check if the market is open on a given date.

        Args:
            check_date: The date to check (defaults to today)

        Returns:
            True if the market is open, False if it's a holiday.
        """
        if check_date is None:
            check_date = date.today()

        holidays = self.get_holidays()
        if holidays is None:
            # If we don't have holiday data, assume market is open (fail-safe for trading)
            logger.warning("No holiday data available, assuming market is open")
            return True

        return check_date not in holidays

    def get_margin_info(self, symbol: str) -> Optional[List[MarginInfo]]:
        """
        Get margin information for a given symbol.

        Returns:
            A list of MarginInfo objects, or None if not available.
        """
        with self._lock:
            if not self._has_ever_loaded['margin']:
                self._refresh_margins()

            if not self._is_data_fresh('margin'):
                self._refresh_margins()

            return self._margins.get(symbol)

    def get_reference_data_status(self) -> Dict[str, Any]:
        """
        Get the status of the reference data service.

        Returns:
            A dictionary with status information.
        """
        with self._lock:
            status = {
                'lot_size': {
                    'has_data': bool(self._lot_sizes),
                    'last_updated': self._last_updated.get('lot_size', 0),
                    'is_fresh': self._is_data_fresh('lot_size'),
                    'has_ever_loaded': self._has_ever_loaded['lot_size'],
                    'symbol_count': len(self._lot_sizes)
                },
                'expiry': {
                    'has_data': bool(self._expiries),
                    'last_updated': self._last_updated.get('expiry', 0),
                    'is_fresh': self._is_data_fresh('expiry'),
                    'has_ever_loaded': self._has_ever_loaded['expiry'],
                    'symbol_count': len(self._expiries)
                },
                'holiday': {
                    'has_data': bool(self._holidays),
                    'last_updated': self._last_updated.get('holiday', 0),
                    'is_fresh': self._is_data_fresh('holiday'),
                    'has_ever_loaded': self._has_ever_loaded['holiday'],
                    'holiday_count': len(self._holidays)
                },
                'margin': {
                    'has_data': bool(self._margins),
                    'last_updated': self._last_updated.get('margin', 0),
                    'is_fresh': self._is_data_fresh('margin'),
                    'has_ever_loaded': self._has_ever_loaded['margin'],
                    'symbol_count': len(self._margins)
                }
            }
            return status


# Global reference data service instance
_reference_data_service: Optional[ReferenceDataService] = None
_reference_data_service_lock = threading.Lock()


def get_reference_data_service() -> ReferenceDataService:
    """Get the global reference data service instance."""
    global _reference_data_service
    if _reference_data_service is None:
        with _reference_data_service_lock:
            if _reference_data_service is None:
                _reference_data_service = ReferenceDataService()
    return _reference_data_service


def init_reference_data_service(data_engine: Optional[DataEngine] = None,
                              cache_ttl: Optional[Dict[str, float]] = None,
                              enable_fallback_to_file: bool = True,
                              fallback_file_dir: Optional[Path] = None) -> ReferenceDataService:
    """Initialize the global reference data service."""
    global _reference_data_service
    with _reference_data_service_lock:
        _reference_data_service = ReferenceDataService(
            data_engine=data_engine,
            cache_ttl=cache_ttl,
            enable_fallback_to_file=enable_fallback_to_file,
            fallback_file_dir=fallback_file_dir
        )
    return _reference_data_service


# Convenience functions for common operations
def get_lot_size(symbol: str) -> Optional[int]:
    """Get the lot size for a symbol using the global service."""
    return get_reference_data_service().get_lot_size(symbol)


def get_expiry_dates(symbol: str) -> Optional[List[date]]:
    """Get the expiry dates for a symbol using the global service."""
    return get_reference_data_service().get_expiry_dates(symbol)


def get_holidays() -> Optional[Set[date]]:
    """Get the set of market holiday dates using the global service."""
    return get_reference_data_service().get_holidays()


def is_market_open(check_date: Optional[date] = None) -> bool:
    """Check if the market is open on a given date using the global service."""
    return get_reference_data_service().is_market_open(check_date)


def get_margin_info(symbol: str) -> Optional[List[MarginInfo]]:
    """Get margin information for a symbol using the global service."""
    return get_reference_data_service().get_margin_info(symbol)


# Export public interface
__all__ = [
    'ReferenceDataService',
    'LotSizeInfo',
    'ExpiryInfo',
    'HolidayInfo',
    'MarginInfo',
    'ReferenceDataError',
    'get_reference_data_service',
    'init_reference_data_service',
    'get_lot_size',
    'get_expiry_dates',
    'get_holidays',
    'is_market_open',
    'get_margin_info'
]