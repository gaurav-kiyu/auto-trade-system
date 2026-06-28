"""
Circuit Breaker Port Interface

This interface defines the contract that all circuit breaker implementations must implement.
It provides a unified way to protect external dependencies from cascading failures
using the circuit breaker pattern.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation, requests pass through
    OPEN = "open"          # Circuit is open, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service has recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5          # Number of failures before opening
    success_threshold: int = 3          # Number of successes in half-open to close
    timeout: int = 60                   # Seconds to wait before trying half-open
    expected_exception: type = Exception  # Exception type that counts as failure
    sliding_window_size: int = 10       # For sliding window failure counting
    sliding_window_type: str = "time"   # "count" or "time"
    failure_rate_threshold: float = 0.5 # Failure rate threshold (0.0 to 1.0) to trip
    half_open_max_requests: int = 0     # Max requests in half-open (0 = unlimited)
    timeout_exponential_base: float = 2.0  # Exponential backoff base for timeout


@dataclass
class CircuitBreakerStats:
    """Circuit breaker statistics."""
    state: CircuitState
    failure_count: int
    success_count: int
    last_failure_time: datetime | None
    last_success_time: datetime | None
    next_attempt_time: datetime | None
    failure_rate: float  # 0.0 to 1.0
    throughput: float    # Requests per second


class CircuitBreakerPort(ABC):
    """
    Abstract base class for circuit breaker implementations.

    All circuit breaker implementations must inherit from this class
    and implement the required methods.
    """

    @abstractmethod
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function protected by the circuit breaker.

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

    @abstractmethod
    def get_state(self) -> CircuitState:
        """
        Get the current state of the circuit breaker.

        Returns:
            Current circuit state
        """

    @abstractmethod
    def get_stats(self) -> CircuitBreakerStats:
        """
        Get circuit breaker statistics.

        Returns:
            CircuitBreakerStats object with current statistics
        """

    @abstractmethod
    def reset(self) -> None:
        """Reset the circuit breaker to closed state."""

    @abstractmethod
    def force_open(self) -> None:
        """Force the circuit breaker into open state."""

    @abstractmethod
    def force_close(self) -> None:
        """Force the circuit breaker into closed state."""

    @abstractmethod
    def update_config(self, config: CircuitBreakerConfig) -> None:
        """
        Update the circuit breaker configuration.

        Args:
            config: New circuit breaker configuration
        """

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the circuit breaker.

        Returns:
            Dictionary containing health check results
        """


# Exception classes
class CircuitBreakerOpenException(Exception):
    """Exception raised when circuit breaker is open."""


class CircuitBreakerHalfOpenException(Exception):
    """Exception raised when circuit breaker is half-open and rejects call."""


__all__ = [
    "CircuitBreakerConfig",
    "CircuitBreakerHalfOpenException",
    "CircuitBreakerOpenException",
    "CircuitBreakerPort",
    "CircuitBreakerStats",
    "CircuitState",
]

