"""
Broker-Specific Exception Taxonomy - CRITICAL FIX #5
Implements broker-specific exception handling for proper retry classification.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional


class BrokerExceptionType(Enum):
    """Classification of broker exceptions"""
    TRANSIENT = "TRANSIENT"          # Temporary, retry likely works
    PERMANENT = "PERMANENT"          # Won't work regardless of retry
    AUTH_EXPIRED = "AUTH_EXPIRED"    # Authentication needs refresh
    RATE_LIMIT = "RATE_LIMIT"       # Rate limited, back off
    ORDER_REJECTED = "ORDER_REJECTED"  # Order rejected by broker/exchange
    AMBIGUOUS_STATE = "AMBIGUOUS_STATE"  # Can't determine state
    NETWORK_ERROR = "NETWORK_ERROR"    # Network connectivity issue
    TIMEOUT = "TIMEOUT"              # Request timed out


class BrokerException(Exception):
    """Base broker exception with type classification"""

    def __init__(
        self,
        message: str,
        exception_type: BrokerExceptionType,
        retryable: bool,
        broker_code: Optional[str] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.exception_type = exception_type
        self.retryable = retryable
        self.broker_code = broker_code
        self.original_exception = original_exception

    def should_retry(self) -> bool:
        return self.retryable and self.exception_type in [
            BrokerExceptionType.TRANSIENT,
            BrokerExceptionType.RATE_LIMIT,
            BrokerExceptionType.NETWORK_ERROR,
            BrokerExceptionType.TIMEOUT,
        ]

    def is_auth_issue(self) -> bool:
        return self.exception_type == BrokerExceptionType.AUTH_EXPIRED

    def is_permanent_failure(self) -> bool:
        return self.exception_type == BrokerExceptionType.PERMANENT


class TransientBrokerError(BrokerException):
    """Temporary error - retry likely works"""

    def __init__(self, message: str, broker_code: Optional[str] = None, original: Exception = None):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.TRANSIENT,
            retryable=True,
            broker_code=broker_code,
            original_exception=original,
        )


class PermanentBrokerError(BrokerException):
    """Permanent error - no retry"""

    def __init__(self, message: str, broker_code: Optional[str] = None, original: Exception = None):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.PERMANENT,
            retryable=False,
            broker_code=broker_code,
            original_exception=original,
        )


class AuthExpiredError(BrokerException):
    """Authentication expired - need to refresh"""

    def __init__(self, message: str, broker_code: Optional[str] = None, original: Exception = None):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.AUTH_EXPIRED,
            retryable=False,  # Need auth refresh, not simple retry
            broker_code=broker_code,
            original_exception=original,
        )


class RateLimitError(BrokerException):
    """Rate limit hit - back off"""

    def __init__(self, message: str, broker_code: Optional[str] = None, original: Exception = None):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.RATE_LIMIT,
            retryable=True,
            broker_code=broker_code,
            original_exception=original,
        )


class OrderRejectedError(BrokerException):
    """Order rejected by broker/exchange"""

    def __init__(
        self,
        message: str,
        broker_code: Optional[str] = None,
        reason: Optional[str] = None,
        original: Exception = None,
    ):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.ORDER_REJECTED,
            retryable=False,  # Rejection usually means invalid
            broker_code=broker_code,
            original_exception=original,
        )
        self.reason = reason


class AmbiguousExecutionStateError(BrokerException):
    """Cannot determine order state - ambiguity"""

    def __init__(
        self,
        message: str,
        broker_code: Optional[str] = None,
        broker_order_id: Optional[str] = None,
        original: Exception = None,
    ):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.AMBIGUOUS_STATE,
            retryable=False,  # Need manual reconciliation
            broker_code=broker_code,
            original_exception=original,
        )
        self.broker_order_id = broker_order_id


class NetworkError(BrokerException):
    """Network connectivity issue"""

    def __init__(self, message: str, broker_code: Optional[str] = None, original: Exception = None):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.NETWORK_ERROR,
            retryable=True,
            broker_code=broker_code,
            original_exception=original,
        )


class BrokerTimeoutError(BrokerException):
    """Request timeout"""

    def __init__(self, message: str, broker_code: Optional[str] = None, original: Exception = None):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.TIMEOUT,
            retryable=True,
            broker_code=broker_code,
            original_exception=original,
        )


def classify_broker_exception(
    exception: Exception,
    broker_name: str = "UNKNOWN",
) -> BrokerException:
    """
    Classify a raw exception into proper broker exception type.
    Maps broker-specific error codes to our taxonomy.
    """

    # Kite (Zerodha) error codes
    kite_error_codes = {
        "36001": ("Invalid symbol", BrokerExceptionType.PERMANENT),
        "36002": ("Insufficient margin", BrokerExceptionType.PERMANENT),
        "36003": ("Order quantity exceeds limit", BrokerExceptionType.PERMANENT),
        "36004": ("Product type not allowed", BrokerExceptionType.PERMANENT),
        "36005": ("Invalid order type", BrokerExceptionType.PERMANENT),
        "36101": ("Market closed", BrokerExceptionType.TRANSIENT),
        "36102": ("Order not allowed in this segment", BrokerExceptionType.PERMANENT),
        "36201": ("Duplicate order", BrokerExceptionType.PERMANENT),
        "36202": ("Pending order exists", BrokerExceptionType.TRANSIENT),
        "40001": ("Session expired", BrokerExceptionType.AUTH_EXPIRED),
        "40002": ("Invalid token", BrokerExceptionType.AUTH_EXPIRED),
    }

    # Angel One error codes
    angel_error_codes = {
        "AG001": ("Invalid API key", BrokerExceptionType.PERMANENT),
        "AG002": ("Invalid token", BrokerExceptionType.AUTH_EXPIRED),
        "AG003": ("Token expired", BrokerExceptionType.AUTH_EXPIRED),
        "AG101": ("Insufficient margin", BrokerExceptionType.PERMANENT),
        "AG102": ("Order rejected", BrokerExceptionType.ORDER_REJECTED),
        "AG103": ("Duplicate order", BrokerExceptionType.PERMANENT),
        "AG201": ("Rate limit exceeded", BrokerExceptionType.RATE_LIMIT),
        "AG301": ("Market closed", BrokerExceptionType.TRANSIENT),
    }

    # Map based on error code if present
    error_code = getattr(exception, "code", None) or getattr(exception, "error_code", None)

    if error_code and broker_name.upper() == "KITE":
        if error_code in kite_error_codes:
            msg, exc_type = kite_error_codes[error_code]
            if exc_type == BrokerExceptionType.PERMANENT:
                return PermanentBrokerError(f"{msg} (code: {error_code})", error_code, exception)
            elif exc_type == BrokerExceptionType.AUTH_EXPIRED:
                return AuthExpiredError(f"{msg} (code: {error_code})", error_code, exception)
            elif exc_type == BrokerExceptionType.TRANSIENT:
                return TransientBrokerError(f"{msg} (code: {error_code})", error_code, exception)
            elif exc_type == BrokerExceptionType.RATE_LIMIT:
                return RateLimitError(f"{msg} (code: {error_code})", error_code, exception)
            elif exc_type == BrokerExceptionType.ORDER_REJECTED:
                return OrderRejectedError(f"{msg} (code: {error_code})", error_code, exception)

    if error_code and broker_name.upper() == "ANGEL":
        if error_code in angel_error_codes:
            msg, exc_type = angel_error_codes[error_code]
            if exc_type == BrokerExceptionType.PERMANENT:
                return PermanentBrokerError(f"{msg} (code: {error_code})", error_code, exception)
            # ... similar mapping

    # Fallback classification based on exception type
    exc_msg = str(exception).lower()

    if "timeout" in exc_msg:
        return BrokerTimeoutError(f"Timeout: {exception}", original=exception)

    if "connection" in exc_msg or "network" in exc_msg:
        return NetworkError(f"Network issue: {exception}", original=exception)

    if "rate limit" in exc_msg:
        return RateLimitError(f"Rate limited: {exception}", original=exception)

    if "auth" in exc_msg or "token" in exc_msg or "session" in exc_msg:
        return AuthExpiredError(f"Auth issue: {exception}", original=exception)

    if "margin" in exc_msg or "insufficient" in exc_msg:
        return PermanentBrokerError(f"Insufficient margin: {exception}", original=exception)

    if "rejected" in exc_msg or "invalid" in exc_msg:
        return OrderRejectedError(f"Order rejected: {exception}", original=exception)

    # Default to transient for unknown errors
    return TransientBrokerError(f"Unknown broker error: {exception}", original=exception)