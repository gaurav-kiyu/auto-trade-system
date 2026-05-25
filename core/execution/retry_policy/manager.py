"""
Retry Policy Manager for Order Execution.

Implements exponential backoff and retry logic for broker communications.
Distinguishes between SAFE and UNSAFE retries to prevent duplicate orders.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

log = logging.getLogger("retry_policy")


class RetrySafety(Enum):
    """Classification of whether an operation can be safely retried."""
    SAFE = "safe"  # Can retry - network timeouts, temporary unavailability
    UNKNOWN = "unknown"  # MUST NOT RETRY - broker status unknown, ACK not received
    UNSAFE = "unsafe"  # MUST NOT RETRY - permanent failures


class RetryPolicy:
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 10.0,
        exponential_base: float = 2.0,
        allow_unknown_retry: bool = False,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.allow_unknown_retry = allow_unknown_retry

    def classify_error(self, exception: Exception) -> RetrySafety:
        """Classify an exception to determine if retry is safe."""
        error_msg = str(exception).lower()
        error_type = type(exception).__name__.lower()

        if any(x in error_type for x in ["timeout", "connection", "temporary", "unavailable", "503", "502", "504"]):
            return RetrySafety.SAFE
        if any(x in error_msg for x in ["timeout", "connection", "temporary", "unavailable", "503", "502", "504", "network"]):
            return RetrySafety.SAFE

        if any(x in error_type for x in ["unknown", "acknowledgement", "ack", "uncertain"]):
            return RetrySafety.UNKNOWN
        if any(x in error_msg for x in ["unknown", "acknowledgement", "ack", "uncertain", "submission status unknown"]):
            return RetrySafety.UNKNOWN

        if any(x in error_type for x in ["rejected", "invalid", "insufficient", "margin", "not found", "auth", "permission"]):
            return RetrySafety.UNSAFE
        if any(x in error_msg for x in ["rejected", "invalid", "insufficient", "margin", "not found", "auth", "permission", "not allowed", "not permitted"]):
            return RetrySafety.UNSAFE

        return RetrySafety.UNKNOWN

    def execute_with_retry(
        self,
        operation: Callable,
        *args,
        retry_on_error_types: tuple | None = None,
        **kwargs
    ) -> tuple[Any, bool, RetrySafety]:
        """
        Execute operation with retry logic.
        
        Returns:
            tuple: (result, succeeded, safety_classification)
        """
        last_exception = None
        last_safety = RetrySafety.UNKNOWN

        for attempt in range(1, self.max_retries + 1):
            try:
                if attempt > 1:
                    delay = min(
                        self.base_delay * (self.exponential_base ** (attempt - 2)),
                        self.max_delay
                    )
                    log.debug(f"Retry attempt {attempt} after {delay:.1f}s delay")
                    time.sleep(delay)

                result = operation(*args, **kwargs)
                return result, True, RetrySafety.SAFE

            except Exception as e:
                last_exception = e
                safety = self.classify_error(e)
                last_safety = safety

                log.warning(f"Operation attempt {attempt} failed: {e} (safety: {safety.value})")

                if safety == RetrySafety.UNSAFE:
                    log.error(f"Unsafe error - will not retry: {e}")
                    break

                if safety == RetrySafety.UNKNOWN and not self.allow_unknown_retry:
                    log.error(f"Unknown error - will not retry to prevent duplicate: {e}")
                    break

                if attempt == self.max_retries:
                    break

        return None, False, last_safety

    def execute_safe_retry(self, operation: Callable, *args, **kwargs) -> Any:
        """Execute with retry ONLY on safe errors. Raises on unknown/unsafe."""
        result, succeeded, safety = self.execute_with_retry(operation, *args, **kwargs)
        if not succeeded:
            if safety == RetrySafety.UNKNOWN:
                raise RuntimeError(f"Operation failed with unknown status - manual intervention required: {last_exception}")
            elif safety == RetrySafety.UNSAFE:
                raise RuntimeError(f"Operation failed with permanent error - do not retry: {last_exception}")
            else:
                raise RuntimeError(f"Operation failed after {self.max_retries} retries: {last_exception}")
        return result


from dataclasses import dataclass


@dataclass
class RetryResult:
    """Result of a retryable operation."""
    success: bool
    result: Any | None
    safety: RetrySafety
    attempts: int
    error: str | None = None


def safe_retry_operation(
    operation: Callable,
    max_retries: int = 3,
    *args,
    **kwargs
) -> RetryResult:
    """Convenience function for safe retry with classification."""
    policy = RetryPolicy(max_retries=max_retries, allow_unknown_retry=False)
    last_exc = None

    def wrapped_operation(*args, **kwargs):
        nonlocal last_exc
        try:
            return operation(*args, **kwargs)
        except Exception as e:
            last_exc = e
            raise

    result, success, safety = policy.execute_with_retry(wrapped_operation, *args, **kwargs)
    return RetryResult(
        success=success,
        result=result,
        safety=safety,
        attempts=max_retries,
        error=str(last_exc) if not success and last_exc else None
    )
