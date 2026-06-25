"""
Broker-Specific Exception Taxonomy - CRITICAL FIX #5
Implements broker-specific exception handling for proper retry classification.
"""
from __future__ import annotations

from enum import Enum


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
        broker_code: str | None = None,
        original_exception: Exception | None = None,
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

    def __init__(self, message: str, broker_code: str | None = None, original: Exception = None):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.TRANSIENT,
            retryable=True,
            broker_code=broker_code,
            original_exception=original,
        )


class PermanentBrokerError(BrokerException):
    """Permanent error - no retry"""

    def __init__(self, message: str, broker_code: str | None = None, original: Exception = None):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.PERMANENT,
            retryable=False,
            broker_code=broker_code,
            original_exception=original,
        )


class AuthExpiredError(BrokerException):
    """Authentication expired - need to refresh"""

    def __init__(self, message: str, broker_code: str | None = None, original: Exception = None):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.AUTH_EXPIRED,
            retryable=False,  # Need auth refresh, not simple retry
            broker_code=broker_code,
            original_exception=original,
        )


class RateLimitError(BrokerException):
    """Rate limit hit - back off"""

    def __init__(self, message: str, broker_code: str | None = None, original: Exception = None):
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
        broker_code: str | None = None,
        reason: str | None = None,
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
        broker_code: str | None = None,
        broker_order_id: str | None = None,
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

    def __init__(self, message: str, broker_code: str | None = None, original: Exception = None):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.NETWORK_ERROR,
            retryable=True,
            broker_code=broker_code,
            original_exception=original,
        )


class BrokerTimeoutError(BrokerException):
    """Request timeout"""

    def __init__(self, message: str, broker_code: str | None = None, original: Exception = None):
        super().__init__(
            message=message,
            exception_type=BrokerExceptionType.TIMEOUT,
            retryable=True,
            broker_code=broker_code,
            original_exception=original,
        )


_BROKER_ERROR_CODES: dict[str, dict[str, tuple[str, BrokerExceptionType]]] = {}
"""Registry of broker-specific error codes, populated lazily by _get_broker_codes()."""


def _get_broker_codes() -> dict[str, dict[str, tuple[str, BrokerExceptionType]]]:
    """Get or create the broker error code registry."""
    if _BROKER_ERROR_CODES:
        return _BROKER_ERROR_CODES

    codes: dict[str, dict[str, tuple[str, BrokerExceptionType]]] = {
        "KITE": {
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
        },
        "ANGEL": {
            "AG001": ("Invalid API key", BrokerExceptionType.PERMANENT),
            "AG002": ("Invalid token", BrokerExceptionType.AUTH_EXPIRED),
            "AG003": ("Token expired", BrokerExceptionType.AUTH_EXPIRED),
            "AG101": ("Insufficient margin", BrokerExceptionType.PERMANENT),
            "AG102": ("Order rejected", BrokerExceptionType.ORDER_REJECTED),
            "AG103": ("Duplicate order", BrokerExceptionType.PERMANENT),
            "AG201": ("Rate limit exceeded", BrokerExceptionType.RATE_LIMIT),
            "AG301": ("Market closed", BrokerExceptionType.TRANSIENT),
        },
        "FYERS": {
            "F-1000": ("Invalid credentials", BrokerExceptionType.PERMANENT),
            "F-1001": ("Token expired", BrokerExceptionType.AUTH_EXPIRED),
            "F-1002": ("Invalid symbol", BrokerExceptionType.PERMANENT),
            "F-1003": ("Insufficient balance", BrokerExceptionType.PERMANENT),
            "F-1004": ("Order quantity exceeds limit", BrokerExceptionType.PERMANENT),
            "F-1005": ("Market closed", BrokerExceptionType.TRANSIENT),
            "F-2001": ("Rate limit exceeded", BrokerExceptionType.RATE_LIMIT),
            "F-2002": ("Duplicate order", BrokerExceptionType.PERMANENT),
            "F-3001": ("Instrument not traded", BrokerExceptionType.PERMANENT),
            "F-3002": ("Invalid order type", BrokerExceptionType.PERMANENT),
            "F-4001": ("Server error", BrokerExceptionType.TRANSIENT),
            "F-4002": ("Request timeout", BrokerExceptionType.TIMEOUT),
        },
        "DHAN": {
            "DH-001": ("Invalid client ID", BrokerExceptionType.PERMANENT),
            "DH-002": ("Invalid token", BrokerExceptionType.AUTH_EXPIRED),
            "DH-003": ("Token expired", BrokerExceptionType.AUTH_EXPIRED),
            "DH-101": ("Insufficient margin", BrokerExceptionType.PERMANENT),
            "DH-102": ("Invalid symbol", BrokerExceptionType.PERMANENT),
            "DH-103": ("Order rejected", BrokerExceptionType.ORDER_REJECTED),
            "DH-201": ("Rate limit exceeded", BrokerExceptionType.RATE_LIMIT),
            "DH-301": ("Market closed", BrokerExceptionType.TRANSIENT),
            "DH-302": ("Duplicate order", BrokerExceptionType.PERMANENT),
            "DH-401": ("Server error", BrokerExceptionType.TRANSIENT),
            "DH-402": ("Request timeout", BrokerExceptionType.TIMEOUT),
        },
    }

    _BROKER_ERROR_CODES.update(codes)
    return _BROKER_ERROR_CODES


def _dispatch_error_code(
    error_code: str,
    msg: str,
    exc_type: BrokerExceptionType,
    exception: Exception,
) -> BrokerException:
    """Dispatch an error code to the correct exception subclass."""
    constructor_map: dict[BrokerExceptionType, type] = {
        BrokerExceptionType.PERMANENT: PermanentBrokerError,
        BrokerExceptionType.AUTH_EXPIRED: AuthExpiredError,
        BrokerExceptionType.TRANSIENT: TransientBrokerError,
        BrokerExceptionType.RATE_LIMIT: RateLimitError,
        BrokerExceptionType.ORDER_REJECTED: OrderRejectedError,
        BrokerExceptionType.TIMEOUT: BrokerTimeoutError,
    }
    exc_cls = constructor_map.get(exc_type, TransientBrokerError)
    return exc_cls(f"{msg} (code: {error_code})", broker_code=error_code, original=exception)  # type: ignore[call-arg]


def classify_broker_exception(
    exception: Exception,
    broker_name: str = "UNKNOWN",
) -> BrokerException:
    """
    Classify a raw exception into proper broker exception type.
    Maps broker-specific error codes to our taxonomy.

    Supported brokers: KITE, ANGEL, FYERS, DHAN
    """

    # Map based on error code if present
    # Normalize to string to handle int codes from broker SDKs
    error_code = getattr(exception, "code", None) or getattr(exception, "error_code", None)
    if error_code is not None:
        error_code = str(error_code)

    if error_code:
        broker_codes = _get_broker_codes()
        broker_upper = broker_name.upper()
        broker_map = broker_codes.get(broker_upper)
        if broker_map and error_code in broker_map:
            msg, exc_type = broker_map[error_code]
            return _dispatch_error_code(error_code, msg, exc_type, exception)

    # Fallback classification based on exception type
    exc_msg = str(exception).lower()

    if "timeout" in exc_msg or "timed out" in exc_msg:
        return BrokerTimeoutError(f"Timeout: {exception}", original=exception)

    if "connection" in exc_msg or "network" in exc_msg or "reset" in exc_msg:
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


__all__ = [
    "AmbiguousExecutionStateError",
    "AuthExpiredError",
    "BrokerException",
    "BrokerExceptionType",
    "BrokerTimeoutError",
    "NetworkError",
    "OrderRejectedError",
    "PermanentBrokerError",
    "RateLimitError",
    "TransientBrokerError",
    "classify_broker_exception",
]

