"""
Circuit Breaker Service Implementation

Implements the circuit breaker pattern to protect external dependencies from
cascading failures and provide graceful degradation.
"""

from __future__ import annotations

import logging

__all__ = [
    "CircuitBreakerService",
]
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from core.datetime_ist import now_ist
from core.ports.circuit_breaker.circuit_breaker_port import (
    CircuitBreakerConfig,
    CircuitBreakerOpenException,
    CircuitBreakerPort,
    CircuitBreakerStats,
    CircuitState,
)

logger = logging.getLogger(__name__)


@dataclass
class _CircuitBreakerState:
    """Internal state of a circuit breaker."""
    config: CircuitBreakerConfig
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: datetime | None = None
    last_success_time: datetime | None = None
    next_attempt_time: datetime | None = None
    # For sliding window failure counting
    failure_timestamps: deque[float] = field(default_factory=deque)
    success_timestamps: deque[float] = field(default_factory=deque)
    # v2 circuit breaker state
    _consecutive_open_count: int = 0
    _half_open_requests: int = 0


class CircuitBreakerService(CircuitBreakerPort):
    """
    Circuit breaker service implementation.

    Features:
    - Multiple circuit breaker instances (one per dependency)
    - Configurable failure thresholds and timeouts
    - Sliding window failure counting
    - Automatic transition between states
    - Detailed statistics and monitoring
    """

    def __init__(self):
        """Initialize the circuit breaker service."""
        self._lock = threading.RLock()
        self._breakers: dict[str, _CircuitBreakerState] = {}
        logger.info("CircuitBreakerService initialized")

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function protected by the circuit breaker.

        Uses a default key "global" for backward compatibility.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Result of the function execution

        Raises:
            The exception from the function if circuit is closed or half-open
            CircuitBreakerOpenException if circuit is open
        """
        return self.call_with_key("global", func, *args, **kwargs)

    def call_with_key(self, key: str, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function protected by a circuit breaker identified by key.

        Args:
            key: Identifier for the circuit breaker
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Result of the function execution

        Raises:
            The exception from the function if circuit is closed or half-open
            CircuitBreakerOpenException if circuit is open
            CircuitBreakerHalfOpenException if circuit is half-open and rejects call
        """
        with self._lock:
            # Get or create circuit breaker state for this key
            if key not in self._breakers:
                self._breakers[key] = _CircuitBreakerState(
                    config=CircuitBreakerConfig()  # Default config
                )

            breaker = self._breakers[key]

            # Check if we should attempt the call
            if not self._should_attempt_call(breaker):
                # Circuit is open and timeout hasn't elapsed
                if breaker.state == CircuitState.OPEN:
                    raise CircuitBreakerOpenException(
                        f"Circuit breaker is OPEN for key '{key}'. "
                        f"Next attempt allowed at {breaker.next_attempt_time}"
                    )
                else:
                    # This shouldn't happen, but treat as open for safety
                    raise CircuitBreakerOpenException(
                        f"Circuit breaker is not allowing calls for key '{key}'"
                    )

            # Attempt the call
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed_time = time.time() - start_time

                # Call succeeded
                self._on_success(breaker, elapsed_time)
                return result

            except Exception as e:
                elapsed_time = time.time() - start_time

                # Check if this is an expected exception that should trigger failure
                if isinstance(e, breaker.config.expected_exception):
                    self._on_failure(breaker, elapsed_time, e)
                else:
                    # Unexpected exception - still count as failure for safety
                    self._on_failure(breaker, elapsed_time, e)

                # Re-raise the original exception
                raise

    def get_state(self, key: str = "global") -> CircuitState:
        """
        Get the current state of the circuit breaker for a key.

        Args:
            key: Identifier for the circuit breaker (defaults to "global")

        Returns:
            Current circuit state
        """
        with self._lock:
            if key not in self._breakers:
                return CircuitState.CLOSED  # Default state for unknown breaker
            return self._breakers[key].state

    def get_stats(self, key: str = "global") -> CircuitBreakerStats:
        """
        Get circuit breaker statistics for a key.

        Args:
            key: Identifier for the circuit breaker (defaults to "global")

        Returns:
            CircuitBreakerStats object with current statistics
        """
        with self._lock:
            if key not in self._breakers:
                # Return default stats for unknown breaker
                return CircuitBreakerStats(
                    state=CircuitState.CLOSED,
                    failure_count=0,
                    success_count=0,
                    last_failure_time=None,
                    last_success_time=None,
                    next_attempt_time=None,
                    failure_rate=0.0,
                    throughput=0.0
                )

            breaker = self._breakers[key]

            # Calculate failure rate (sliding window)
            failure_rate = self._calculate_failure_rate(breaker)

            # Calculate throughput (requests per second over last minute)
            throughput = self._calculate_throughput(breaker)

            return CircuitBreakerStats(
                state=breaker.state,
                failure_count=breaker.failure_count,
                success_count=breaker.success_count,
                last_failure_time=breaker.last_failure_time,
                last_success_time=breaker.last_success_time,
                next_attempt_time=breaker.next_attempt_time,
                failure_rate=failure_rate,
                throughput=throughput
            )

    def reset(self, key: str = "global") -> None:
        """
        Reset the circuit breaker to closed state for a key.

        Args:
            key: Identifier for the circuit breaker to reset (defaults to "global")
        """
        with self._lock:
            if key not in self._breakers:
                self._breakers[key] = _CircuitBreakerState(
                    config=CircuitBreakerConfig()
                )

            breaker = self._breakers[key]
            breaker.state = CircuitState.CLOSED
            breaker.failure_count = 0
            breaker.success_count = 0
            breaker.last_failure_time = None
            breaker.last_success_time = None
            breaker.next_attempt_time = None
            breaker.failure_timestamps.clear()
            breaker.success_timestamps.clear()
            breaker._consecutive_open_count = 0
            breaker._half_open_requests = 0

            logger.info(f"Circuit breaker reset for key: {key}")

    def force_open(self, key: str = "global") -> None:
        """
        Force the circuit breaker into open state for a key.

        Args:
            key: Identifier for the circuit breaker (defaults to "global")
        """
        with self._lock:
            if key not in self._breakers:
                self._breakers[key] = _CircuitBreakerState(
                    config=CircuitBreakerConfig()
                )

            breaker = self._breakers[key]
            breaker.state = CircuitState.OPEN
            breaker.next_attempt_time = now_ist() + self._compute_timeout(breaker)

            logger.warning(f"Circuit breaker forced OPEN for key: {key}")

    def force_close(self, key: str = "global") -> None:
        """
        Force the circuit breaker into closed state for a key.

        Args:
            key: Identifier for the circuit breaker (defaults to "global")
        """
        with self._lock:
            if key not in self._breakers:
                self._breakers[key] = _CircuitBreakerState(
                    config=CircuitBreakerConfig()
                )

            breaker = self._breakers[key]
            breaker.state = CircuitState.CLOSED
            breaker.failure_count = 0
            breaker.success_count = 0
            breaker.last_failure_time = None
            breaker.last_success_time = None
            breaker.next_attempt_time = None
            breaker.failure_timestamps.clear()
            breaker.success_timestamps.clear()
            breaker._consecutive_open_count = 0
            breaker._half_open_requests = 0

            logger.info(f"Circuit breaker forced CLOSED for key: {key}")

    def update_config(self, key: str, config: CircuitBreakerConfig) -> None:
        """
        Update the circuit breaker configuration for a key.

        Args:
            key: Identifier for the circuit breaker
            config: New circuit breaker configuration
        """
        with self._lock:
            if key not in self._breakers:
                self._breakers[key] = _CircuitBreakerState(config=config)
            else:
                self._breakers[key].config = config
                # If currently in half-open state, we might want to reset
                # depending on the new config, but we'll keep current state

            logger.info(f"Circuit breaker config updated for key: {key}")

    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the circuit breaker service.

        Returns:
            Dictionary containing health check results
        """
        with self._lock:
            breaker_states = {}
            for key, breaker in self._breakers.items():
                breaker_states[key] = {
                    "state": breaker.state.value,
                    "failure_count": breaker.failure_count,
                    "success_count": breaker.success_count,
                    "last_failure_time": breaker.last_failure_time.isoformat() if breaker.last_failure_time else None,
                    "last_success_time": breaker.last_success_time.isoformat() if breaker.last_success_time else None,
                    "next_attempt_time": breaker.next_attempt_time.isoformat() if breaker.next_attempt_time else None
                }

            return {
                "status": "healthy",
                "service": "CircuitBreakerService",
                "breakers": breaker_states,
                "total_breakers": len(self._breakers)
            }

    # Private helper methods

    def _should_attempt_call(self, breaker: _CircuitBreakerState) -> bool:
        """
        Determine if we should attempt a call based on circuit breaker state.

        Args:
            breaker: Circuit breaker state to check

        Returns:
            True if we should attempt the call, False otherwise
        """
        if breaker.state == CircuitState.CLOSED:
            # Normal operation - always allow calls
            return True
        elif breaker.state == CircuitState.OPEN:
            # Check if timeout has elapsed for half-open attempt
            if breaker.next_attempt_time and now_ist() >= breaker.next_attempt_time:
                # Time to try half-open
                breaker.state = CircuitState.HALF_OPEN
                breaker.success_count = 0  # Reset success count for half-open trial
                breaker._half_open_requests = 0
                logger.info("Circuit breaker transitioning to HALF_OPEN")
                return True
            else:
                # Still in timeout period
                return False
        elif breaker.state == CircuitState.HALF_OPEN:
            # Check half-open max requests cap
            max_reqs = getattr(breaker.config, "half_open_max_requests", 0)
            half_open_reqs = getattr(breaker, "_half_open_requests", 0)
            if max_reqs > 0 and half_open_reqs >= max_reqs:
                return False
            return True
        else:
            # Unknown state - fail closed for safety
            return False

    def _on_success(self, breaker: _CircuitBreakerState, elapsed_time: float) -> None:
        """
        Handle a successful call.

        Args:
            breaker: Circuit breaker state
            elapsed_time: Time taken for the call in seconds
        """
        breaker.last_success_time = now_ist()
        breaker.success_count += 1
        getattr(breaker, "_half_open_requests", 0)

        if breaker.state == CircuitState.HALF_OPEN:
            # Track half-open request count
            breaker._half_open_requests = getattr(breaker, "_half_open_requests", 0) + 1

        # Add to success timestamps for sliding window
        breaker.success_timestamps.append(time.time())
        self._trim_timestamps(breaker.success_timestamps, breaker.config.sliding_window_size, breaker)

        if breaker.state == CircuitState.HALF_OPEN:
            # In half-open state, check if we've had enough successes to close
            if breaker.success_count >= breaker.config.success_threshold:
                breaker.state = CircuitState.CLOSED
                breaker.failure_count = 0  # Reset failure count on successful recovery
                breaker.next_attempt_time = None
                breaker._consecutive_open_count = 0
                logger.info("Circuit breaker CLOSED after successful recovery")
        elif breaker.state == CircuitState.CLOSED:
            # In closed state, reset failure count on success
            breaker.failure_count = 0

    def _compute_timeout(self, breaker: _CircuitBreakerState) -> timedelta:
        """Compute timeout with optional exponential backoff.

        Args:
            breaker: Circuit breaker state

        Returns:
            timedelta for the next attempt wait
        """
        base = float(breaker.config.timeout)
        exp_base = float(getattr(breaker.config, "timeout_exponential_base", 2.0))
        consecutive_open = breaker._consecutive_open_count + 1
        breaker._consecutive_open_count = consecutive_open
        delay = base * (exp_base ** (consecutive_open - 1))
        # Cap at reasonable maximum (8 hours)
        max_delay = 28800.0
        delay = min(delay, max_delay)
        return timedelta(seconds=delay)

    def _on_failure(self, breaker: _CircuitBreakerState, elapsed_time: float, exception: Exception) -> None:
        """
        Handle a failed call.

        Args:
            breaker: Circuit breaker state
            elapsed_time: Time taken for the call in seconds
            exception: The exception that occurred
        """
        breaker.last_failure_time = now_ist()
        breaker.failure_count += 1

        # Add to failure timestamps for sliding window
        breaker.failure_timestamps.append(time.time())
        self._trim_timestamps(breaker.failure_timestamps, breaker.config.sliding_window_size, breaker)

        if breaker.state == CircuitState.HALF_OPEN:
            # Any failure in half-open state goes back to open
            breaker.state = CircuitState.OPEN
            breaker.next_attempt_time = now_ist() + self._compute_timeout(breaker)
            logger.warning("Circuit breaker OPEN again after failure in half-open state")
        elif breaker.state == CircuitState.CLOSED:
            # Check if we've reached the failure threshold
            if self._should_trip_breaker(breaker):
                breaker.state = CircuitState.OPEN
                breaker.next_attempt_time = now_ist() + self._compute_timeout(breaker)
                logger.warning(f"Circuit breaker OPEN after {breaker.failure_count} failures")

    def _should_trip_breaker(self, breaker: _CircuitBreakerState) -> bool:
        """
        Determine if the circuit breaker should trip based on failure count or rate.

        Args:
            breaker: Circuit breaker state to check

        Returns:
            True if the breaker should trip, False otherwise
        """
        # Check based on configured failure threshold (absolute count)
        if breaker.failure_count >= breaker.config.failure_threshold:
            return True

        # Check based on failure rate in sliding window (if configured)
        if breaker.config.sliding_window_size > 0:
            failure_rate = self._calculate_failure_rate(breaker)
            rate_threshold = getattr(breaker.config, "failure_rate_threshold", 0.5)
            if failure_rate > rate_threshold:
                return True

        return False

    def _calculate_failure_rate(self, breaker: _CircuitBreakerState) -> float:
        """
        Calculate failure rate based on sliding window.

        Args:
            breaker: Circuit breaker state

        Returns:
            Failure rate as a float between 0.0 and 1.0
        """
        if breaker.config.sliding_window_size <= 0:
            # Fallback to simple ratio if sliding window not configured
            total = breaker.failure_count + breaker.success_count
            if total == 0:
                return 0.0
            return breaker.failure_count / total

        # Use sliding window for more accurate rate
        cutoff_time = time.time() - breaker.config.sliding_window_size if breaker.config.sliding_window_type == "time" else None

        if breaker.config.sliding_window_type == "time" and cutoff_time is not None:
            # Count failures and successes in the time window
            recent_failures = sum(1 for ts in breaker.failure_timestamps if ts >= cutoff_time)
            recent_successes = sum(1 for ts in breaker.success_timestamps if ts >= cutoff_time)
            total = recent_failures + recent_successes
            if total == 0:
                return 0.0
            return recent_failures / total
        else:
            # Count-based sliding window
            # Just use the last N entries
            failure_count = len(breaker.failure_timestamps)
            success_count = len(breaker.success_timestamps)
            total = failure_count + success_count
            if total == 0:
                return 0.0
            return failure_count / total

    def _calculate_throughput(self, breaker: _CircuitBreakerState) -> float:
        """
        Calculate throughput (requests per second) based on recent history.

        Args:
            breaker: Circuit breaker state

        Returns:
            Throughput as requests per second
        """
        if breaker.config.sliding_window_size <= 0:
            # Simple approximation based on total counts
            # This is rough but better than nothing
            return 0.0  # Would need timestamps to calculate properly

        # Use sliding window for throughput calculation
        cutoff_time = time.time() - breaker.config.sliding_window_size if breaker.config.sliding_window_type == "time" else None

        if breaker.config.sliding_window_type == "time" and cutoff_time is not None:
            # Count requests in the time window
            recent_failures = sum(1 for ts in breaker.failure_timestamps if ts >= cutoff_time)
            recent_successes = sum(1 for ts in breaker.success_timestamps if ts >= cutoff_time)
            total_requests = recent_failures + recent_successes
            if breaker.config.sliding_window_size > 0:
                return total_requests / breaker.config.sliding_window_size
            else:
                return 0.0
        else:
            # Count-based - less accurate but still useful
            failure_count = len(breaker.failure_timestamps)
            success_count = len(breaker.success_timestamps)
            total_requests = failure_count + success_count
            # Assume window of 60 seconds for approximation
            return total_requests / 60.0 if total_requests > 0 else 0.0

    def _trim_timestamps(self, timestamps: deque[float], max_size: int, breaker: _CircuitBreakerState | None = None) -> None:
        """
        Trim timestamps deque to maximum size.

        Args:
            timestamps: Deque of timestamps to trim
            max_size: Maximum number of timestamps to keep
            breaker: Breaker state to determine sliding window type (optional)
        """
        if breaker and breaker.config.sliding_window_type == "time":
            # Time-based sliding window - remove old entries
            cutoff_time = time.time() - breaker.config.sliding_window_size
            while timestamps and timestamps[0] < cutoff_time:
                timestamps.popleft()
        else:
            # Count-based sliding window - keep only last N entries
            while len(timestamps) > max_size:
                timestamps.popleft()
