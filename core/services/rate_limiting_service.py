"""
Rate Limiting Service Implementation

Implements various rate limiting algorithms to protect external dependencies:
- Fixed window counter
- Sliding window log
- Sliding window counter
- Token bucket
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.ports.rate_limiting.rate_limit_port import LimitResult, RateLimitConfig, RateLimitPort, RateLimitStatus
from trading_system.core.logging.service import LoggingService


@dataclass
class _WindowCounter:
    """Counter for a fixed time window."""
    count: int = 0
    window_start: float = field(default_factory=time.time)


@dataclass
class _TokenBucket:
    """Token bucket for token bucket algorithm."""
    capacity: int
    tokens: float
    refill_rate: float  # Tokens per second
    last_refill: float = field(default_factory=time.time)


class RateLimitingService(RateLimitPort):
    """
    Rate limiting service supporting multiple algorithms.

    Features:
    - Multiple rate limiting algorithms (fixed_window, sliding_window, token_bucket)
    - Per-key rate limiting (different limits for different API keys, IPs, endpoints)
    - Thread-safe operations
    - Configurable windows and limits
    - Automatic cleanup of old entries
    """

    def __init__(self, default_config: RateLimitConfig | None = None):
        """
        Initialize the rate limiting service.

        Args:
            default_config: Default configuration for rate limits
        """
        self._default_config = default_config or RateLimitConfig(
            limit=100,
            window=60,  # 1 minute
            algorithm="fixed_window"
        )

        # Storage for rate limit data
        self._lock = threading.RLock()
        self._counters: dict[str, _WindowCounter] = {}  # For fixed window
        self._sliding_windows: dict[str, deque[float]] = {}  # For sliding window
        self._token_buckets: dict[str, _TokenBucket] = {}  # For token bucket
        self._custom_configs: dict[str, RateLimitConfig] = {}  # Per-key configs

        self._logger = LoggingService(
            log_dir="logs",
            log_filename_prefix="rate_limiting_service_",
            retain_days=30,
            json_log_file="",
            version="UNKNOWN",
            enable_correlation_ids=True,
            enable_contextual_logging=True
        )

        self._logger.info("RateLimitingService initialized")

    def is_allowed(self, key: str, cost: int = 1) -> LimitResult:
        """
        Check if a request is allowed under the rate limit.

        Args:
            key: Identifier for the rate limit (e.g., IP address, API key, endpoint)
            cost: Cost of the request (default 1)

        Returns:
            LimitResult indicating whether the request is allowed
        """
        with self._lock:
            config = self._get_config(key)

            if config.algorithm == "fixed_window":
                return self._is_allowed_fixed_window(key, cost, config)
            elif config.algorithm == "sliding_window":
                return self._is_allowed_sliding_window(key, cost, config)
            elif config.algorithm == "token_bucket":
                return self._is_allowed_token_bucket(key, cost, config)
            else:
                # Default to fixed window
                return self._is_allowed_fixed_window(key, cost, config)

    def get_status(self, key: str) -> RateLimitStatus:
        """
        Get the current rate limit status for a key.

        Args:
            key: Identifier for the rate limit

        Returns:
            RateLimitStatus object with current status information
        """
        with self._lock:
            config = self._get_config(key)

            if config.algorithm == "fixed_window":
                return self._get_status_fixed_window(key, config)
            elif config.algorithm == "sliding_window":
                return self._get_status_sliding_window(key, config)
            elif config.algorithm == "token_bucket":
                return self._get_status_token_bucket(key, config)
            else:
                # Default to fixed window
                return self._get_status_fixed_window(key, config)

    def reset(self, key: str) -> None:
        """
        Reset the rate limit for a key.

        Args:
            key: Identifier for the rate limit to reset
        """
        with self._lock:
            self._counters.pop(key, None)
            self._sliding_windows.pop(key, None)
            self._token_buckets.pop(key, None)
            self._logger.debug(f"Rate limit reset for key: {key}")

    def get_retry_after(self, key: str) -> float | None:
        """
        Get the number of seconds to wait before retrying.

        Args:
            key: Identifier for the rate limit

        Returns:
            Number of seconds to wait, or None if no retry is needed
        """
        with self._lock:
            config = self._get_config(key)

            if config.algorithm == "fixed_window":
                counter = self._counters.get(key)
                if counter and counter.count >= config.limit:
                    # Time until window reset
                    elapsed = time.time() - counter.window_start
                    return max(0, config.window - elapsed)
                return 0.0

            elif config.algorithm == "sliding_window":
                timestamps = self._sliding_windows.get(key, deque())
                if len(timestamps) >= config.limit and timestamps:
                    # Time until oldest request falls out of window
                    oldest = timestamps[0]
                    elapsed = time.time() - oldest
                    return max(0, config.window - elapsed)
                return 0.0

            elif config.algorithm == "token_bucket":
                bucket = self._token_buckets.get(key)
                if bucket and bucket.tokens < 1:
                    # Time to refill enough tokens
                    tokens_needed = 1 - bucket.tokens
                    return tokens_needed / bucket.refill_rate if bucket.refill_rate > 0 else 0.0
                return 0.0

            return 0.0

    def update_config(self, key: str, config: RateLimitConfig) -> None:
        """
        Update the rate limit configuration for a key.

        Args:
            key: Identifier for the rate limit
            config: New rate limit configuration
        """
        with self._lock:
            self._custom_configs[key] = config
            self._logger.debug(f"Rate limit config updated for key: {key}")

    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the rate limiting service.

        Returns:
            Dictionary containing health check results
        """
        with self._lock:
            return {
                "status": "healthy",
                "service": "RateLimitingService",
                "tracked_keys": len(self._counters) + len(self._sliding_windows) + len(self._token_buckets),
                "fixed_window_counters": len(self._counters),
                "sliding_windows": len(self._sliding_windows),
                "token_buckets": len(self._token_buckets),
                "custom_configs": len(self._custom_configs)
            }

    # Private helper methods

    def _get_config(self, key: str) -> RateLimitConfig:
        """Get configuration for a key (custom or default)."""
        return self._custom_configs.get(key, self._default_config)

    def _is_allowed_fixed_window(self, key: str, cost: int, config: RateLimitConfig) -> LimitResult:
        """Fixed window algorithm."""
        now = time.time()
        counter = self._counters.get(key)

        # Reset window if expired
        if not counter or (now - counter.window_start) >= config.window:
            counter = _WindowCounter()
            self._counters[key] = counter

        # Check if limit would be exceeded
        if counter.count + cost > config.limit:
            return LimitResult.DENIED

        # Allow request
        counter.count += cost
        return LimitResult.ALLOWED

    def _get_status_fixed_window(self, key: str, config: RateLimitConfig) -> RateLimitStatus:
        """Get status for fixed window algorithm."""
        counter = self._counters.get(key)
        if not counter:
            # No requests yet
            return RateLimitStatus(
                allowed=True,
                remaining=config.limit,
                reset_time=datetime.fromtimestamp(time.time() + config.window),
                retry_after=None,
                limit=config.limit,
                window=config.window,
                algorithm=config.algorithm
            )

        # Calculate remaining and reset time
        elapsed = time.time() - counter.window_start
        remaining_window = max(0, config.window - elapsed)
        reset_time = datetime.fromtimestamp(time.time() + remaining_window)
        remaining = max(0, config.limit - counter.count)

        return RateLimitStatus(
            allowed=(counter.count < config.limit),
            remaining=remaining,
            reset_time=reset_time,
            retry_after=remaining_window if counter.count >= config.limit else None,
            limit=config.limit,
            window=config.window,
            algorithm=config.algorithm
        )

    def _is_allowed_sliding_window(self, key: str, cost: int, config: RateLimitConfig) -> LimitResult:
        """Sliding window log algorithm."""
        now = time.time()
        window_start = now - config.window

        # Get or create sliding window for this key
        if key not in self._sliding_windows:
            self._sliding_windows[key] = deque()

        timestamps = self._sliding_windows[key]

        # Remove old entries outside the window
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        # Check if limit would be exceeded
        if len(timestamps) + cost > config.limit:
            return LimitResult.DENIED

        # Add current request(s) timestamps
        for _ in range(cost):
            timestamps.append(now)

        return LimitResult.ALLOWED

    def _get_status_sliding_window(self, key: str, config: RateLimitConfig) -> RateLimitStatus:
        """Get status for sliding window algorithm."""
        now = time.time()
        window_start = now - config.window

        timestamps = self._sliding_windows.get(key, deque())

        # Remove old entries
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        # Calculate status
        count = len(timestamps)
        remaining = max(0, config.limit - count)

        # Calculate reset time (when oldest request falls out of window)
        if timestamps:
            oldest = timestamps[0]
            reset_time = datetime.fromtimestamp(oldest + config.window)
            retry_after = max(0, (oldest + config.window) - time.time()) if count >= config.limit else None
        else:
            # No requests in window
            reset_time = datetime.fromtimestamp(now + config.window)
            retry_after = None

        return RateLimitStatus(
            allowed=(count < config.limit),
            remaining=remaining,
            reset_time=reset_time,
            retry_after=retry_after,
            limit=config.limit,
            window=config.window,
            algorithm=config.algorithm
        )

    def _is_allowed_token_bucket(self, key: str, cost: int, config: RateLimitConfig) -> LimitResult:
        """Token bucket algorithm."""
        now = time.time()
        bucket = self._token_buckets.get(key)

        # Initialize bucket if needed
        if not bucket:
            bucket = _TokenBucket(
                capacity=config.limit,
                tokens=float(config.limit),
                refill_rate=config.limit / config.window if config.window > 0 else 0.0
            )
            self._token_buckets[key] = bucket

        # Refill tokens based on time passed
        time_passed = now - bucket.last_refill
        if time_passed > 0 and bucket.refill_rate > 0:
            tokens_to_add = time_passed * bucket.refill_rate
            bucket.tokens = min(bucket.capacity, bucket.tokens + tokens_to_add)
            bucket.last_refill = now

        # Check if we have enough tokens
        if bucket.tokens < cost:
            return LimitResult.DENIED

        # Consume tokens
        bucket.tokens -= cost
        return LimitResult.ALLOWED

    def _get_status_token_bucket(self, key: str, config: RateLimitConfig) -> RateLimitStatus:
        """Get status for token bucket algorithm."""
        now = time.time()
        bucket = self._token_buckets.get(key)

        if not bucket:
            # Initialize with default values
            bucket = _TokenBucket(
                capacity=config.limit,
                tokens=float(config.limit),
                refill_rate=config.limit / config.window if config.window > 0 else 0.0
            )
            self._token_buckets[key] = bucket

        # Calculate refill since last update
        time_passed = now - bucket.last_refill
        if time_passed > 0 and bucket.refill_rate > 0:
            tokens_to_add = time_passed * bucket.refill_rate
            bucket.tokens = min(bucket.capacity, bucket.tokens + tokens_to_add)
            bucket.last_refill = now

        # Calculate time to refill one token (for retry-after)
        retry_after = None
        if bucket.tokens < 1 and bucket.refill_rate > 0:
            retry_after = (1 - bucket.tokens) / bucket.refill_rate

        return RateLimitStatus(
            allowed=(bucket.tokens >= 1),
            remaining=int(bucket.tokens),
            reset_time=datetime.fromtimestamp(now + config.window),  # Approximate
            retry_after=retry_after,
            limit=config.limit,
            window=config.window,
            algorithm=config.algorithm
        )


# Convenience decorator for rate limiting functions
def rate_limit(key_func: Callable[[], str] | None = None,
               cost: int = 1,
               service: RateLimitingService | None = None):
    """
    Decorator to apply rate limiting to a function.

    Args:
        key_func: Function that returns the rate limit key (defaults to "global")
        cost: Cost of the function call
        service: Rate limiting service to use (creates default if None)
    """
    def decorator(func):
        nonlocal service
        if service is None:
            service = RateLimitingService()

        def wrapper(*args, **kwargs):
            # Determine the key
            if key_func:
                key = key_func()
            else:
                key = "global"

            # Check rate limit
            result = service.is_allowed(key, cost)
            if result == LimitResult.DENIED:
                raise Exception(f"Rate limit exceeded for key: {key}")

            # Execute function
            return func(*args, **kwargs)

        return wrapper
    return decorator
