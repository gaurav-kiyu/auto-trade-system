"""
Domain-Specific Exception Hierarchy (Phase 1).

Replaces bare ``except Exception`` with semantically typed catches so that
every failure is: logged, classified, escalated, recovered, and fails closed.

This is the SINGLE canonical exception hierarchy for the trading platform.
``core/common/exceptions/`` is a deprecated re-export shim that points here.

Usage
-----
    from core.exceptions import BrokerTimeoutError, ValidationError
    try:
        broker.place_order(...)
    except BrokerTimeoutError:
        _log.warning("Broker timeout - retrying")
        return _fallback_fill(...)


Exception Tree
--------------
TradingException                    # Base - all trading exceptions
├── AuthenticationError             #   Authentication failures
├── AuthorizationError              #   Authorization failures
├── BrokerException                 # Broker adapter failures
│   ├── BrokerTimeoutError          #   API call exceeded timeout
│   ├── BrokerConnectionError       #   Network / connection refused
│   ├── BrokerAuthError             #   Token expired / invalid
│   ├── BrokerRejectedError         #   Order rejected by broker
│   ├── BrokerRateLimitError        #   Rate limited
│   └── BrokerAuthenticationError   #   Broker auth failure
├── CertificationError              # Certification failures
├── ChaosError                      # Chaos injection failures
├── CircuitBreakerError             # Circuit breaker open
├── ConfigError                     # Config validation / loading
├── ExecutionError                  # Order execution failures
│   ├── IdempotencyError            #   Duplicate order detection
│   └── FillError                   #   Fill verification failed
├── GovernanceError                 # Constitution / AI gate violations
├── HealthCheckError                # Health check failures
├── InsufficientDataError           # Insufficient data for operation
├── InstrumentNotFoundError         # Financial instrument not found
├── MarketDataError                 # Data feed failures
│   ├── StaleDataError              #   Data older than freshness threshold
│   ├── FeedDisconnectedError       #   WebSocket / API feed down
│   ├── MarketDataSourceError       #   Source failed to provide data
│   ├── MarketDataValidationError   #   Data failed validation
│   └── MarketDataStalenessError    #   Data too stale for use
├── PersistenceError                # DB / file I/O failures
│   ├── DatabaseError               #   SQLite / connection errors
│   ├── StateFileError              #   trader_state.json read/write
│   ├── PersistenceConnectionError  #   Connection to persistence failed
│   ├── PersistenceWriteError       #   Write to persistence failed
│   └── PersistenceReadError        #   Read from persistence failed
├── ReconciliationError             # State mismatch / orphan orders
├── RiskException                   # Risk engine violations
│   ├── RiskLimitError              #   MAX_DAILY_LOSS / MAX_DRAWDOWN breached
│   ├── MaxDrawdownError            #   Portfolio drawdown limit hit
│   ├── HardHaltError               #   Hard halt active
│   ├── PositionSizingError         #   Invalid position size
│   ├── CorrelationGuardError       #   Cross-index correlation block
│   ├── RiskLimitExceededError      #   Generic risk limit exceeded
│   ├── MarginInsufficientError     #   Insufficient margin
│   └── PositionLimitExceededError  #   Position limit exceeded
├── SignalError                     # Signal generation pipeline
│   └── SignalValidationError       #   Signal validation failure
├── ValidationError                 # Input/state validation failures
"""

from __future__ import annotations

from typing import Any

# ── Base ──────────────────────────────────────────────────────────────────────

class TradingException(Exception):
    """Base exception for all trading system errors."""

    def __init__(
        self,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
        error_code: str | None = None,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        self.details = details or {}
        self.error_code = error_code or self.__class__.__name__
        self.context = context or {}
        self.cause = cause
        super().__init__(message)

    def classify(self) -> str:
        """Return a human-readable classification tag."""
        return type(self).__name__

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.classify(),
            "message": str(self),
            "error_code": self.error_code,
            "details": self.details,
            "context": self.context,
            "cause": str(self.cause) if self.cause else None,
        }


# ── Authentication & Authorization ────────────────────────────────────────────

class AuthenticationError(TradingException):
    """Exception raised for authentication-related errors."""


class AuthorizationError(TradingException):
    """Exception raised for authorization-related errors."""


# ── Broker ────────────────────────────────────────────────────────────────────

class BrokerException(TradingException):
    """Base for all broker adapter failures."""


class BrokerTimeoutError(BrokerException):
    """Broker API call exceeded configured timeout."""


class BrokerConnectionError(BrokerException):
    """Network-level connection refused / DNS failure."""


class BrokerAuthError(BrokerException):
    """Authentication token expired, invalid, or rejected."""


class BrokerRejectedError(BrokerException):
    """Order explicitly rejected by the broker (insufficient margin, bad symbol, etc.)."""


class BrokerRateLimitError(BrokerException):
    """Broker API rate limit exceeded."""


class BrokerAuthenticationError(BrokerException):
    """Broker authentication failure (distinct from BrokerAuthError for granularity)."""


# ── Certification ─────────────────────────────────────────────────────────────

class CertificationError(TradingException):
    """Base exception for certification failures."""


# ── Chaos ─────────────────────────────────────────────────────────────────────

class ChaosError(TradingException):
    """Chaos injection or verification failure."""


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class CircuitBreakerError(TradingException):
    """Circuit breaker is OPEN - operations blocked."""


# ── Config ────────────────────────────────────────────────────────────────────

class ConfigError(TradingException):
    """Config loading, validation, or merge failure."""


# ── Execution ─────────────────────────────────────────────────────────────────

class ExecutionError(TradingException):
    """Base for order execution failures."""


class IdempotencyError(ExecutionError):
    """Duplicate order detected via idempotency check."""


class FillError(ExecutionError):
    """Fill verification failed - quantity or price mismatch."""


# ── Governance ────────────────────────────────────────────────────────────────

class GovernanceError(TradingException):
    """Constitution validation or AI safety gate violation."""


# ── Health Check ──────────────────────────────────────────────────────────────

class HealthCheckError(TradingException):
    """Base exception for health check failures."""


# ── Insufficient Data / Instrument Not Found ──────────────────────────────────

class InsufficientDataError(TradingException):
    """Raised when there is insufficient data to perform an operation."""


class InstrumentNotFoundError(TradingException):
    """Raised when a financial instrument is not found."""


# ── Market Data ───────────────────────────────────────────────────────────────

class MarketDataError(TradingException):
    """Base for data feed failures."""


class StaleDataError(MarketDataError):
    """Data older than configured freshness threshold."""


class FeedDisconnectedError(MarketDataError):
    """WebSocket or API feed is disconnected."""


class MarketDataSourceError(MarketDataError):
    """Raised when a market data source fails to provide data."""


class MarketDataValidationError(MarketDataError):
    """Raised when market data fails validation checks."""


class MarketDataStalenessError(MarketDataError):
    """Raised when market data is too stale for use."""


# ── Persistence ───────────────────────────────────────────────────────────────

class PersistenceError(TradingException):
    """Base for DB / file I/O failures."""


class DatabaseError(PersistenceError):
    """SQLite connection or query error."""


class StateFileError(PersistenceError):
    """trader_state.json read or write failure."""


class PersistenceConnectionError(PersistenceError):
    """Raised when connecting to a persistence layer fails."""


class PersistenceWriteError(PersistenceError):
    """Raised when writing to a persistence layer fails."""


class PersistenceReadError(PersistenceError):
    """Raised when reading from a persistence layer fails."""


# ── Reconciliation ────────────────────────────────────────────────────────────

class ReconciliationError(TradingException):
    """State mismatch, orphan orders, or reconciliation failure."""


# ── Risk ──────────────────────────────────────────────────────────────────────

class RiskException(TradingException):
    """Base for risk engine violations."""


class RiskLimitError(RiskException):
    """MAX_DAILY_LOSS, MAX_DRAWDOWN, or PORTFOLIO_MAX_SL_RISK_PCT breached."""


class MaxDrawdownError(RiskException):
    """Portfolio drawdown exceeded configured limit."""


class HardHaltError(RiskException):
    """Hard halt is active - all entries blocked."""


class PositionSizingError(RiskException):
    """Invalid or out-of-range position size calculated."""


class CorrelationGuardError(RiskException):
    """Cross-index correlation guard blocked simultaneous entries."""


class RiskLimitExceededError(RiskException):
    """Generic risk limit exceeded (alias for RiskLimitError)."""


class MarginInsufficientError(RiskException):
    """Raised when insufficient margin is available for a trade."""


class PositionLimitExceededError(RiskException):
    """Raised when a position limit is exceeded."""


# ── Signal ────────────────────────────────────────────────────────────────────

class SignalError(TradingException):
    """Signal generation or scoring pipeline failure."""


class SignalValidationError(SignalError):
    """Raised when signal validation fails."""


# ── Validation ────────────────────────────────────────────────────────────────

class ValidationError(TradingException):
    """Input or state validation failure."""


# ── Graceful degradation helpers ──────────────────────────────────────────────

def safe_fallback(value: Any, default: Any = None) -> Any:
    """Return value if truthy, else default - for optional-feature wrappers."""
    return value if value is not None else default


def raise_if_not_true(condition: bool, message: str, error_class: type = ValidationError, **context) -> None:
    """
    Raise an exception if condition is not True.

    Args:
        condition: Condition to check
        message: Error message if condition fails
        error_class: Exception class to raise
        **context: Additional context information

    Raises:
        error_class: If condition is False
    """
    if not condition:
        raise error_class(message, details=context)


def raise_if_none(value: Any, message: str, error_class: type = ValidationError, **context) -> None:
    """
    Raise an exception if value is None.

    Args:
        value: Value to check
        message: Error message if value is None
        error_class: Exception class to raise
        **context: Additional context information

    Raises:
        error_class: If value is None
    """
    if value is None:
        raise error_class(message, details=context)


def raise_if_empty(value: Any, message: str, error_class: type = ValidationError, **context) -> None:
    """
    Raise an exception if value is empty (for strings, lists, dicts, etc).

    Args:
        value: Value to check
        message: Error message if value is empty
        error_class: Exception class to raise
        **context: Additional context information

    Raises:
        error_class: If value is empty
    """
    if not value:
        raise error_class(message, details=context)


def is_trading_platform_error(exc: BaseException) -> bool:
    """Check if an exception is a trading platform error."""
    return isinstance(exc, TradingException)


__all__ = [
    # Base
    "TradingException",
    # Authentication & Authorization
    "AuthenticationError",
    "AuthorizationError",
    # Broker
    "BrokerAuthError",
    "BrokerAuthenticationError",
    "BrokerConnectionError",
    "BrokerException",
    "BrokerRateLimitError",
    "BrokerRejectedError",
    "BrokerTimeoutError",
    # Certification
    "CertificationError",
    # Chaos
    "ChaosError",
    # Circuit Breaker
    "CircuitBreakerError",
    # Config
    "ConfigError",
    # Execution
    "ExecutionError",
    "FillError",
    "IdempotencyError",
    # Governance
    "GovernanceError",
    # Health Check
    "HealthCheckError",
    # Insufficient Data
    "InsufficientDataError",
    "InstrumentNotFoundError",
    # Market Data
    "FeedDisconnectedError",
    "MarketDataError",
    "MarketDataSourceError",
    "MarketDataStalenessError",
    "MarketDataValidationError",
    "StaleDataError",
    # Persistence
    "DatabaseError",
    "PersistenceConnectionError",
    "PersistenceError",
    "PersistenceReadError",
    "PersistenceWriteError",
    "StateFileError",
    # Reconciliation
    "ReconciliationError",
    # Risk
    "CorrelationGuardError",
    "HardHaltError",
    "MarginInsufficientError",
    "MaxDrawdownError",
    "PositionLimitExceededError",
    "PositionSizingError",
    "RiskException",
    "RiskLimitError",
    "RiskLimitExceededError",
    # Signal
    "SignalError",
    "SignalValidationError",
    # Validation
    "ValidationError",
    # Helpers
    "safe_fallback",
    "raise_if_not_true",
    "raise_if_none",
    "raise_if_empty",
    "is_trading_platform_error",
]
