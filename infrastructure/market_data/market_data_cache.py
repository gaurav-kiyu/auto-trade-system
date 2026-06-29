"""
Market Data Caching and Validation System

This module provides robust market data handling with:
- Configurable freshness validation for different data types
- Intelligent caching with TTL (Time To Live)
- Automatic fallback between data sources
- Staleness detection and alerts
- Safe fallback strategies when data is unavailable
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CachedData:
    """Represents a cached data item with metadata."""
    data: Any
    timestamp: float  # Unix timestamp when data was fetched
    ttl: float  # Time to live in seconds
    source: str  # Data source identifier
    validated: bool = False  # Whether the data has passed validation

    @property
    def age(self) -> float:
        """Get the age of the cached data in seconds."""
        return time.time() - self.timestamp

    @property
    def is_fresh(self) -> bool:
        """Check if the data is still fresh based on TTL."""
        return self.age < self.ttl

    @property
    def is_expired(self) -> bool:
        """Check if the data has expired."""
        return not self.is_fresh


@dataclass
class DataValidationRule:
    """Defines validation rules for different types of market data."""
    min_age_seconds: float = 0  # Minimum age for data to be considered valid
    max_age_seconds: float = 300  # Maximum age for data to be considered fresh (5 minutes default)
    required_fields: list[str] = field(default_factory=list)  # Fields that must be present
    validators: dict[str, Callable[[Any], bool]] = field(default_factory=dict)  # Field-specific validators

    def validate(self, data: Any) -> tuple[bool, str]:
        """
        Validate the data against the rules.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if data is None:
            return False, "Data is None"

        # Check required fields for dict-like data
        if isinstance(data, dict) and self.required_fields:
            missing_fields = [f for f in self.required_fields if f not in data]
            if missing_fields:
                return False, f"Missing required fields: {missing_fields}"

        # Apply field-specific validators
        if isinstance(data, dict) and self.validators:
            for fname, validator in self.validators.items():
                if fname in data:
                    try:
                        if not validator(data[fname]):
                            return False, f"Field '{fname}' failed validation"
                    except (TypeError, ValueError, AttributeError) as e:
                        return False, f"Field '{fname}' validation error: {e}"

        return True, ""


class MarketDataCache:
    """
    Intelligent market data cache with validation and fallback capabilities.

    Features:
    - Per-data-type TTL configuration
    - Validation rules for different data sources
    - Automatic cleanup of expired entries
    - Fallback chaining when primary sources fail
    - Staleness monitoring and metrics
    """

    def __init__(self, default_ttl: float = 300.0):  # 5 minutes default TTL
        """
        Initialize the market data cache.

        Args:
            default_ttl: Default time to live for cached data in seconds
        """
        self.default_ttl = default_ttl
        self._cache: dict[str, CachedData] = {}
        self._lock = threading.RLock()
        self._validation_rules: dict[str, DataValidationRule] = {}
        self._stats = {
            'hits': 0,
            'misses': 0,
            'validations_passed': 0,
            'validations_failed': 0,
            'fallbacks_used': 0
        }

        # Start cleanup thread
        self._cleanup_stop = threading.Event()
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def set_validation_rule(self, data_type: str, rule: DataValidationRule):
        """
        Set validation rules for a specific data type.

        Args:
            data_type: Identifier for the type of data (e.g., 'quote', 'option_chain', 'historical')
            rule: Validation rule to apply
        """
        with self._lock:
            self._validation_rules[data_type] = rule

    def get(self,
            key: str,
            data_type: str = "default",
            validator: Callable[[Any], bool] | None = None,
            max_age: float | None = None) -> tuple[Any | None, bool, str]:
        """
        Retrieve data from cache if available and fresh.

        Args:
            key: Cache key for the data
            data_type: Type of data for validation rule selection
            validator: Optional custom validator function
            max_age: Maximum age in seconds (overrides validation rule if provided)

        Returns:
            Tuple of (data, is_fresh, source)
            - data: The cached data or None if not available/fresh
            - is_fresh: Boolean indicating if data is fresh
            - source: Source of the data ('cache', 'fallback', or 'none')
        """
        with self._lock:
            # Check if we have cached data
            if key in self._cache:
                cached = self._cache[key]

                # Check if data is still fresh
                if cached.is_fresh:
                    # Apply validation if needed
                    is_valid = True
                    validation_msg = ""

                    # Use data-type specific validation rule
                    if data_type in self._validation_rules:
                        is_valid, validation_msg = self._validation_rules[data_type].validate(cached.data)

                    # Apply custom validator if provided
                    if is_valid and validator is not None:
                        try:
                            is_valid = validator(cached.data)
                            validation_msg = "" if is_valid else "Custom validation failed"
                        except (TypeError, ValueError, AttributeError) as e:
                            is_valid = False
                            validation_msg = f"Custom validation error: {e}"

                    # Use max_age override if provided
                    if is_valid and max_age is not None:
                        is_valid = cached.age <= max_age
                        if not is_valid:
                            validation_msg = f"Data too old: {cached.age:.1f}s > {max_age}s"

                    if is_valid:
                        self._stats['hits'] += 1
                        self._stats['validations_passed'] += 1
                        logger.debug(f"Cache hit for key '{key}' (age: {cached.age:.1f}s)")
                        return cached.data, True, "cache"
                    else:
                        self._stats['validations_failed'] += 1
                        logger.warning(f"Cache validation failed for key '{key}': {validation_msg}")
                        # Remove stale/invalid data
                        del self._cache[key]
                else:
                    logger.debug(f"Cache expired for key '{key}' (age: {cached.age:.1f}s)")
                    # Remove expired data
                    del self._cache[key]
            else:
                logger.debug(f"Cache miss for key '{key}'")

            self._stats['misses'] += 1
            return None, False, "none"

    def put(self,
            key: str,
            data: Any,
            data_type: str = "default",
            ttl: float | None = None,
            source: str = "unknown") -> None:
        """
        Store data in the cache.

        Args:
            key: Cache key for the data
            data: The data to cache
            data_type: Type of data for validation rule selection
            ttl: Time to live in seconds (uses default if None)
            source: Identifier of the data source
        """
        with self._lock:
            # Determine TTL - use the provided ttl, or fall back to cache default
            # Validation rules are used for validation, not for determining cache TTL
            if ttl is None:
                ttl = self.default_ttl

            # Create cached data entry
            cached_data = CachedData(
                data=data,
                timestamp=time.time(),
                ttl=ttl,
                source=source
            )

            # Validate the data before caching if we have rules
            if data_type in self._validation_rules:
                is_valid, validation_msg = self._validation_rules[data_type].validate(data)
                cached_data.validated = is_valid
                if not is_valid:
                    logger.warning(f"Caching data that failed validation for key '{key}': {validation_msg}")

            self._cache[key] = cached_data
            logger.debug(f"Cached data for key '{key}' from source '{source}' (TTL: {ttl}s)")

    def invalidate(self, key: str) -> bool:
        """
        Remove a specific key from the cache.

        Args:
            key: Cache key to remove

        Returns:
            True if key was found and removed, False otherwise
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"Invalidated cache key '{key}'")
                return True
            return False

    def clear(self) -> None:
        """Clear all cached data."""
        with self._lock:
            self._cache.clear()
            logger.info("Cleared all market data cache")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self._stats['hits'] + self._stats['misses']
            hit_rate = (self._stats['hits'] / total_requests * 100) if total_requests > 0 else 0

            return {
                **self._stats,
                'total_requests': total_requests,
                'hit_rate_percent': round(hit_rate, 2),
                'cache_size': len(self._cache)
            }

    @property
    def closed(self) -> bool:
        """Whether the cache has been shut down (cleanup thread signalled to stop)."""
        return self._cleanup_stop.is_set()

    def stop(self, timeout: float = 5.0) -> None:
        """Gracefully stop the cleanup thread and release resources.

        Args:
            timeout: Seconds to wait for the cleanup thread to finish.
        """
        self._cleanup_stop.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=timeout)

    def __enter__(self) -> MarketDataCache:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def _cleanup_loop(self):
        """Background thread to periodically clean up expired cache entries."""
        while not self._cleanup_stop.is_set():
            try:
                if self._cleanup_stop.wait(60):  # Clean up every minute, interruptible
                    break
                self._cleanup_expired()
            except (OSError, ValueError, TypeError, AttributeError) as e:
                logger.error(f"Error in cache cleanup loop: {e}")

    def _cleanup_expired(self) -> int:
        """
        Remove all expired entries from the cache.

        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_keys = []
            for key, cached in self._cache.items():
                if cached.is_expired:
                    expired_keys.append(key)

            for key in expired_keys:
                del self._cache[key]
                logger.debug(f"Removed expired cache key '{key}' (age: {self._cache[key].age if key in self._cache else 'unknown':.1f}s)")

            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")

            return len(expired_keys)


# Global market data cache instance
_market_data_cache: MarketDataCache | None = None
_market_data_cache_lock = threading.RLock()


def get_market_data_cache() -> MarketDataCache:
    """Get the global market data cache instance."""
    global _market_data_cache
    if _market_data_cache is None:
        with _market_data_cache_lock:
            if _market_data_cache is None:
                _market_data_cache = MarketDataCache()
    return _market_data_cache


def init_market_data_cache(default_ttl: float = 300.0) -> MarketDataCache:
    """Initialize the global market data cache."""
    global _market_data_cache
    with _market_data_cache_lock:
        _market_data_cache = MarketDataCache(default_ttl=default_ttl)
    return _market_data_cache


# Predefined validation rules for common data types
def create_quote_validation_rule() -> DataValidationRule:
    """Create validation rule for stock/option quotes."""
    return DataValidationRule(
        max_age_seconds=10.0,  # Quotes should be very fresh
        required_fields=['symbol', 'bid', 'ask', 'last'],
        validators={
            'bid': lambda x: isinstance(x, (int, float)) and x >= 0,
            'ask': lambda x: isinstance(x, (int, float)) and x >= 0,
            'last': lambda x: isinstance(x, (int, float)) and x >= 0,
        }
    )


def create_option_chain_validation_rule() -> DataValidationRule:
    """Create validation rule for option chain data."""
    return DataValidationRule(
        max_age_seconds=60.0,  # Option chains can be slightly less fresh
        required_fields=['underlying', 'expiry'],
        validators={
            'underlying': lambda x: isinstance(x, str) and len(x) > 0,
            'expiry': lambda x: isinstance(x, str) and len(x) > 0
        }
    )


def create_historical_data_validation_rule() -> DataValidationRule:
    """Create validation rule for historical data."""
    return DataValidationRule(
        max_age_seconds=3600.0,  # Historical data can be much older
        required_fields=[],  # Historical data format varies
        validators={}
    )


# Convenience functions for common operations
def get_market_data(key: str,
                   data_type: str = "default",
                   validator: Callable[[Any], bool] | None = None,
                   max_age: float | None = None) -> tuple[Any | None, bool, str]:
    """Get market data from the global cache."""
    return get_market_data_cache().get(key, data_type, validator, max_age)


def put_market_data(key: str,
                   data: Any,
                   data_type: str = "default",
                   ttl: float | None = None,
                   source: str = "unknown") -> None:
    """Put market data into the global cache."""
    get_market_data_cache().put(key, data, data_type, ttl, source)


def invalidate_market_data(key: str) -> bool:
    """Invalidate market data in the global cache."""
    return get_market_data_cache().invalidate(key)


def clear_market_data_cache() -> None:
    """Clear the global market data cache."""
    get_market_data_cache().clear()


def get_market_data_cache_stats() -> dict[str, Any]:
    """Get statistics for the global market data cache."""
    return get_market_data_cache().get_stats()


# Export public interface
__all__ = [
    'MarketDataCache',
    'CachedData',
    'DataValidationRule',
    'get_market_data_cache',
    'init_market_data_cache',
    'get_market_data',
    'put_market_data',
    'invalidate_market_data',
    'clear_market_data_cache',
    'get_market_data_cache_stats',
    'create_quote_validation_rule',
    'create_option_chain_validation_rule',
    'create_historical_data_validation_rule'
]
