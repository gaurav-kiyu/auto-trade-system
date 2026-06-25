"""
Broker Error Classifier (Additional Fix).

Classifies broker errors to determine retry strategy:
- Retriable (timeout, network)
- Non-retriable (auth, margin, invalid)
- Unknown (fallback)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    RETRIABLE = "RETRIABLE"
    NON_RETRIABLE = "NON_RETRIABLE"
    UNKNOWN = "UNKNOWN"


@dataclass
class ErrorClassification:
    category: ErrorCategory
    can_retry: bool
    retry_delay: float
    message: str


class BrokerErrorClassifier:
    """
    Classifies broker errors to determine retry strategy.

    Prevents blind retries on non-retriable errors while
    properly handling transient failures.
    """

    DEFAULT_RETRY_DELAY = 1.0
    MAX_RETRY_DELAY = 30.0

    RETRIABLE_PATTERNS = [
        "timeout",
        "timed out",
        "network",
        "connection",
        "refused",
        "reset",
        "temporarily unavailable",
        "service unavailable",
        "503",
        "502",
    ]

    NON_RETRIABLE_PATTERNS = [
        "unauthorized",
        "auth",
        "token",
        "invalid",
        "insufficient",
        "margin",
        "balance",
        "not sufficient",
        "rejected",
        "expired",
        "disabled",
        "blocked",
        "not allowed",
        "401",
        "403",
        "400",
    ]

    def classify(self, error: Exception) -> ErrorClassification:
        """Classify an exception and determine retry strategy."""
        error_type = type(error).__name__
        error_msg = str(error).lower()

        if any(p in error_msg for p in self.NON_RETRIABLE_PATTERNS):
            return ErrorClassification(
                category=ErrorCategory.NON_RETRIABLE,
                can_retry=False,
                retry_delay=0,
                message=f"Non-retriable error: {error_type} - {error}",
            )

        if any(p in error_msg for p in self.RETRIABLE_PATTERNS):
            retry_delay = self._estimate_retry_delay(error_msg)
            return ErrorClassification(
                category=ErrorCategory.RETRIABLE,
                can_retry=True,
                retry_delay=retry_delay,
                message=f"Retriable error: {error_type}",
            )

        return ErrorClassification(
            category=ErrorCategory.UNKNOWN,
            can_retry=True,
            retry_delay=self.DEFAULT_RETRY_DELAY,
            message=f"Unknown error: {error_type} - {error}",
        )

    def _estimate_retry_delay(self, error_msg: str) -> float:
        """Estimate appropriate retry delay based on error type."""
        if "timeout" in error_msg:
            return 5.0
        if "connection" in error_msg:
            return 2.0
        if "network" in error_msg:
            return 3.0
        return self.DEFAULT_RETRY_DELAY


def classify_broker_error(error: Exception) -> ErrorClassification:
    """Convenience function for error classification."""
    classifier = BrokerErrorClassifier()
    return classifier.classify(error)


__all__ = [
    "BrokerErrorClassifier",
    "ErrorCategory",
    "ErrorClassification",
    "classify_broker_error",
    "log",
]

