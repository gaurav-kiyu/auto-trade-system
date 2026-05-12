"""
Base exception classes for the trading system.
All custom exceptions should inherit from these base classes.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class TradingSystemError(Exception):
    """
    Base exception for all trading system errors.

    Provides common functionality for error tracking, context, and serialization.
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        """
        Initialize trading system error.

        Args:
            message: Human-readable error message
            error_code: Optional machine-readable error code
            context: Optional dictionary of contextual information
            cause: Optional underlying exception that caused this error
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.context = context or {}
        self.cause = cause

    def __str__(self) -> str:
        """Return formatted error message."""
        if self.context:
            context_str = "; ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} [{context_str}]"
        return self.message

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert exception to dictionary for serialization/logging.

        Returns:
            Dictionary representation of the exception
        """
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code,
            "context": self.context,
            "cause": str(self.cause) if self.cause else None
        }


class ConfigurationError(TradingSystemError):
    """Exception raised for configuration-related errors."""
    pass


class BrokerError(TradingSystemError):
    """Exception raised for broker-related errors."""
    pass


class DataError(TradingSystemError):
    """Exception raised for data-related errors."""
    pass


class ExecutionError(TradingSystemError):
    """Exception raised for order execution-related errors."""
    pass


class RiskError(TradingSystemError):
    """Exception raised for risk management-related errors."""
    pass


class StateError(TradingSystemError):
    """Exception raised for state management-related errors."""
    pass


class NotificationError(TradingSystemError):
    """Exception raised for notification-related errors."""
    pass


class PersistenceError(TradingSystemError):
    """Exception raised for persistence-related errors."""
    pass


class ValidationError(TradingSystemError):
    """Exception raised for validation-related errors."""
    pass


class AuthenticationError(TradingSystemError):
    """Exception raised for authentication-related errors."""
    pass


class AuthorizationError(TradingSystemError):
    """Exception raised for authorization-related errors."""
    pass


# Specific exception types for common scenarios


class InvalidConfigurationError(ConfigurationError):
    """Exception raised when configuration values are invalid."""
    pass


class MissingConfigurationError(ConfigurationError):
    """Exception raised when required configuration is missing."""
    pass


class BrokerConnectionError(BrokerError):
    """Exception raised when broker connection fails."""
    pass


class BrokerAuthenticationError(BrokerError):
    """Exception raised when broker authentication fails."""
    pass


class BrokerRateLimitError(BrokerError):
    """Exception raised when broker rate limits are exceeded."""
    pass


class MarketDataError(DataError):
    """Exception raised when market data is unavailable or invalid."""
    pass


class HistoricalDataError(DataError):
    """Exception raised when historical data is unavailable or invalid."""
    pass


class OrderExecutionError(ExecutionError):
    """Exception raised when order execution fails."""
    pass


class OrderRejectionError(ExecutionError):
    """Exception raised when an order is rejected by the broker."""
    pass


class OrderTimeoutError(ExecutionError):
    """Exception raised when an order times out."""
    pass


class PositionSizingError(RiskError):
    """Exception raised when position sizing calculation fails."""
    pass


class RiskLimitExceededError(RiskError):
    """Exception raised when a risk limit is exceeded."""
    pass


class InvalidStateError(StateError):
    """Exception raised when trading state is invalid."""
    pass


class StatePersistenceError(StateError):
    """Exception raised when state persistence fails."""
    pass


class NotificationDeliveryError(NotificationError):
    """Exception raised when notification delivery fails."""
    pass


class DatabaseConnectionError(PersistenceError):
    """Exception raised when database connection fails."""
    pass


class DatabaseQueryError(PersistenceError):
    """Exception raised when database query fails."""
    pass


class SerializationError(PersistenceError):
    """Exception raised when data serialization fails."""
    pass


class InvalidInputError(ValidationError):
    """Exception raised when input validation fails."""
    pass


class BusinessRuleViolationError(ValidationError):
    """Exception raised when a business rule is violated."""
    pass


# Convenience functions for common error patterns


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
        raise error_class(message, context=context)


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
        raise error_class(message, context=context)


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
        raise error_class(message, context=context)