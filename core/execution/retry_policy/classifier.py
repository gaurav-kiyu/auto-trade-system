"""
Retry Classification for Broker Errors (Phase 0 - Critical).

Classifies broker errors as RETRYABLE or PERMANENT to prevent:
- Blind retries on permanent failures (e.g., auth expiry)
- Duplicate submissions on uncertain states
"""

from __future__ import annotations

import logging
from enum import Enum

log = logging.getLogger(__name__)


class RetryDecision(Enum):
    """Decision on whether to retry a broker error."""
    RETRY = "retry"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"  # Requires manual intervention


class BrokerErrorClassifier:
    """
    Classifies broker errors to determine retry strategy.

    PERMANENT errors (never retry):
    - Authentication expired (AuthExpiredError)
    - Insufficient margin
    - Position limit reached
    - Symbol not found (invalid instrument)
    - Order rejected with permanent reason

    RETRYABLE errors (can retry with backoff):
    - Network timeout
    - Broker server busy (rate limit)
    - Temporary market halt
    - Connection reset

    UNKNOWN errors (require investigation):
    - Any other exception
    """

    # Permanent error patterns
    PERMANENT_PATTERNS = [
        "auth",
        "token",
        "expired",
        "insufficient",
        "margin",
        "limit",
        "rejected",
        "invalid",
        "not found",
        "unauthorized",
    ]

    RETRYABLE_PATTERNS = [
        "timeout",
        "timed out",
        "connection",
        "refused",
        "reset",
        "temporary",
        "busy",
        "rate limit",
        "too many requests",
    ]

    @staticmethod
    def classify(error: Exception) -> RetryDecision:
        """
        Classify an exception to determine retry strategy.

        Args:
            error: The exception from broker call

        Returns:
            RetryDecision enum
        """
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()

        # Check for permanent errors first
        for pattern in BrokerErrorClassifier.PERMANENT_PATTERNS:
            if pattern in error_str or pattern in error_type:
                log.warning(
                    f"PERMANENT error detected: {error_type} - {str(error)[:100]}"
                )
                return RetryDecision.PERMANENT

        # Check for retryable errors
        for pattern in BrokerErrorClassifier.RETRYABLE_PATTERNS:
            if pattern in error_str or pattern in error_type:
                log.info(f"RETRYABLE error: {error_type} - {str(error)[:100]}")
                return RetryDecision.RETRY

        # Unknown - log for investigation but don't retry blindly
        log.error(
            f"UNKNOWN error type: {error_type} - {str(error)[:100]}. "
            f"Manual investigation required."
        )
        return RetryDecision.UNKNOWN

    @staticmethod
    def should_retry(error: Exception) -> bool:
        """Quick check if error is retryable."""
        decision = BrokerErrorClassifier.classify(error)
        return decision == RetryDecision.RETRY


def classify_broker_error(error: Exception) -> RetryDecision:
    """Convenience function for error classification."""
    return BrokerErrorClassifier.classify(error)


__all__ = [
    "BrokerErrorClassifier",
    "RetryDecision",
    "classify_broker_error",
    "log",
]

