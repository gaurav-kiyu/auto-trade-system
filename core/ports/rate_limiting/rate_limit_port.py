"""
Rate Limiting Port Interface

This interface defines the contract that all rate limiting implementations must implement.
It provides a unified way to protect external dependencies from excessive requests
using various rate limiting algorithms.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class LimitResult(Enum):
    """Result of a rate limit check."""
    ALLOWED = "allowed"
    DENIED = "denied"
    RETRY_AFTER = "retry_after"


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    limit: int  # Number of requests allowed
    window: int  # Time window in seconds
    algorithm: str = "fixed_window"  # fixed_window, sliding_window, token_bucket
    burst_limit: int | None = None  # For token bucket algorithm
    retry_after_header: bool = True  # Whether to include retry-after information


@dataclass
class RateLimitStatus:
    """Current status of a rate limiter."""
    allowed: bool
    remaining: int  # Number of requests remaining in current window
    reset_time: datetime  # When the limit resets
    retry_after: float | None = None  # Seconds to wait before retrying
    limit: int = 0
    window: int = 0
    algorithm: str = ""


class RateLimitPort(ABC):
    """
    Abstract base class for rate limiting implementations.

    All rate limiting implementations must inherit from this class
    and implement the required methods.
    """

    @abstractmethod
    def is_allowed(self, key: str, cost: int = 1) -> LimitResult:
        """
        Check if a request is allowed under the rate limit.

        Args:
            key: Identifier for the rate limit (e.g., IP address, API key, endpoint)
            cost: Cost of the request (default 1)

        Returns:
            LimitResult indicating whether the request is allowed
        """
        pass

    @abstractmethod
    def get_status(self, key: str) -> RateLimitStatus:
        """
        Get the current rate limit status for a key.

        Args:
            key: Identifier for the rate limit

        Returns:
            RateLimitStatus object with current status information
        """
        pass

    @abstractmethod
    def reset(self, key: str) -> None:
        """
        Reset the rate limit for a key.

        Args:
            key: Identifier for the rate limit to reset
        """
        pass

    @abstractmethod
    def get_retry_after(self, key: str) -> float | None:
        """
        Get the number of seconds to wait before retrying.

        Args:
            key: Identifier for the rate limit

        Returns:
            Number of seconds to wait, or None if no retry is needed
        """
        pass

    @abstractmethod
    def update_config(self, key: str, config: RateLimitConfig) -> None:
        """
        Update the rate limit configuration for a key.

        Args:
            key: Identifier for the rate limit
            config: New rate limit configuration
        """
        pass

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the rate limiting service.

        Returns:
            Dictionary containing health check results
        """
        pass
