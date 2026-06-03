"""
Trading Platform Exception Hierarchy

This module defines a hierarchy of custom exceptions for the trading platform.
Each exception class is designed to be specific to a domain or concern,
making error handling more precise and informative.
"""

from __future__ import annotations




class TradingPlatformError(Exception):
    """Base exception for all trading platform errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.context = context or {}
        self.cause = cause

    def __str__(self) -> str:
        if self.context:
            context_str = "; ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} [{context_str}]"
        return self.message

    def to_dict(self) -> dict[str, Any]:
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


# Configuration Related Exceptions
class ConfigurationError(TradingPlatformError):
    """Base exception for configuration-related errors."""


class ConfigurationValidationError(ConfigurationError):
    """Raised when configuration validation fails."""


class ConfigurationLoadError(ConfigurationError):
    """Raised when loading configuration from a source fails."""


class ConfigurationSecretError(ConfigurationError):
    """Raised when there is an issue with secret handling in configuration."""


class InvalidConfigurationError(ConfigurationError):
    """Exception raised when configuration values are invalid."""


class MissingConfigurationError(ConfigurationError):
    """Exception raised when required configuration is missing."""


# Credential Storage Related Exceptions
class CredentialStorageError(TradingPlatformError):
    """Base exception for credential storage errors."""


class CredentialNotFoundError(CredentialStorageError):
    """Raised when a requested credential is not found in the storage."""


class CredentialStorageBackendError(CredentialStorageError):
    """Raised when a credential storage backend fails."""


# Market Data Related Exceptions
class MarketDataError(TradingPlatformError):
    """Base exception for market data related errors."""


class MarketDataSourceError(MarketDataError):
    """Raised when a market data source fails to provide data."""


class MarketDataValidationError(MarketDataError):
    """Raised when market data fails validation checks."""


class MarketDataStalenessError(MarketDataError):
    """Raised when market data is too stale for use."""


class HistoricalDataError(TradingPlatformError):
    """Exception raised when historical data is unavailable or invalid."""


# Reference Data Related Exceptions
class ReferenceDataError(TradingPlatformError):
    """Base exception for reference data related errors."""


class ReferenceDataSourceError(ReferenceDataError):
    """Raised when a reference data source fails."""


class ReferenceDataValidationError(ReferenceDataError):
    """Raised when reference data fails validation."""


class ReferenceDataNotFoundError(ReferenceDataError):
    """Raised when requested reference data is not available."""


# Order Execution Related Exceptions
class OrderExecutionError(TradingPlatformError):
    """Base exception for order execution related errors."""


class OrderRejectionError(OrderExecutionError):
    """Raised when an order is rejected by the broker or exchange."""


class OrderTimeoutError(OrderExecutionError):
    """Raised when an order execution times out."""


class OrderInvalidError(OrderExecutionError):
    """Raised when an order is invalid (e.g., incorrect parameters)."""


# Risk Management Related Exceptions
class RiskManagementError(TradingPlatformError):
    """Base exception for risk management related errors."""


class RiskLimitExceededError(RiskManagementError):
    """Raised when a risk limit is exceeded."""


class MarginInsufficientError(RiskManagementError):
    """Raised when insufficient margin is available for a trade."""


class PositionLimitExceededError(RiskManagementError):
    """Raised when a position limit is exceeded."""


# Notification Related Exceptions
class NotificationError(TradingPlatformError):
    """Base exception for notification related errors."""


class NotificationSendError(NotificationError):
    """Raised when sending a notification fails."""


class NotificationRateLimitError(NotificationError):
    """Raised when a notification rate limit is exceeded."""


# Broker Related Exceptions
class BrokerError(TradingPlatformError):
    """Base exception for broker-related errors."""


class BrokerConnectionError(BrokerError):
    """Raised when broker connection fails."""


class BrokerAuthenticationError(BrokerError):
    """Raised when broker authentication fails."""


class BrokerRateLimitError(BrokerError):
    """Raised when broker rate limits are exceeded."""


# Persistence Related Exceptions
class PersistenceError(TradingPlatformError):
    """Base exception for persistence related errors."""


class PersistenceConnectionError(PersistenceError):
    """Raised when connecting to a persistence layer fails."""


class PersistenceWriteError(PersistenceError):
    """Raised when writing to a persistence layer fails."""


class PersistenceReadError(PersistenceError):
    """Raised when reading from a persistence layer fails."""


# ML/AI Related Exceptions
class ModelError(TradingPlatformError):
    """Base exception for ML/AI model related errors."""


class ModelLoadError(ModelError):
    """Raised when loading a model fails."""


class ModelPredictionError(ModelError):
    """Raised when making a prediction with a model fails."""


class ModelValidationError(ModelError):
    """Raised when model validation fails."""


# Strategy Related Exceptions
class StrategyError(TradingPlatformError):
    """Base exception for strategy related errors."""


# Risk Related Exceptions (alias for RiskManagementError for backward compatibility)
class RiskError(RiskManagementError):
    """Raised when there is an error in risk management."""


# Validation Related Exceptions
class ValidationError(TradingPlatformError):
    """Exception raised when input validation fails."""


# Authentication and Authorization
class AuthenticationError(TradingPlatformError):
    """Exception raised for authentication-related errors."""


class AuthorizationError(TradingPlatformError):
    """Exception raised for authorization-related errors."""


# Insufficient Data
class InsufficientDataError(TradingPlatformError):
    """Raised when there is insufficient data to perform an operation."""


# Instrument Not Found
class InstrumentNotFoundError(TradingPlatformError):
    """Raised when a financial instrument is not found."""


# Reconciliation Related Exceptions
class ReconciliationError(TradingPlatformError):
    """Base exception for reconciliation failures."""


class ReconciliationIssueError(ReconciliationError):
    """Raised when reconciliation detects issues."""


class ReconciliationFreezeError(ReconciliationError):
    """Raised when reconciliation freezes trading due to ambiguity."""


# Broker Timeout
# Note: core/execution/broker_exceptions.py defines its own BrokerTimeoutError
# that extends BrokerException(Exception). The one below extends TradingPlatformError
# for imports from the common exceptions hierarchy. Both are valid - use the one
# appropriate for your layer. The broker_exceptions version has richer classification.
class BrokerTimeoutError(TradingPlatformError):
    """Raised when a broker request times out.

    Note: There is also a BrokerTimeoutError in core/execution/broker_exceptions.py
    that extends BrokerException. Catch TradingPlatformError to catch both.
    """


# Signal Related Exceptions
class SignalError(TradingPlatformError):
    """Base exception for signal processing errors."""


class SignalProcessingError(SignalError):
    """Raised when signal processing fails."""


class SignalValidationError(SignalError):
    """Raised when signal validation fails."""


# Health Check Exceptions
class HealthCheckError(TradingPlatformError):
    """Base exception for health check failures."""


# Governance Exceptions
class GovernanceError(TradingPlatformError):
    """Base exception for governance violations."""


class ConstitutionViolationError(GovernanceError):
    """Raised when a constitution rule is violated."""


# Certification Exceptions
class CertificationError(TradingPlatformError):
    """Base exception for certification failures."""


class ReplayCertificationError(CertificationError):
    """Raised when replay certification fails."""


class PaperCertificationError(CertificationError):
    """Raised when paper trading certification fails."""


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


# Utility function to check if an exception is a trading platform error
def is_trading_platform_error(exc: BaseException) -> bool:
    """Check if an exception is a trading platform error."""
    return isinstance(exc, TradingPlatformError)


# Export all exceptions
__all__ = [
    # Base
    "TradingPlatformError",
    # Configuration
    "ConfigurationError",
    "ConfigurationValidationError",
    "ConfigurationLoadError",
    "ConfigurationSecretError",
    "InvalidConfigurationError",
    "MissingConfigurationError",
    # Credential Storage
    "CredentialStorageError",
    "CredentialNotFoundError",
    "CredentialStorageBackendError",
    # Market Data
    "MarketDataError",
    "MarketDataSourceError",
    "MarketDataValidationError",
    "MarketDataStalenessError",
    "HistoricalDataError",
    # Reference Data
    "ReferenceDataError",
    "ReferenceDataSourceError",
    "ReferenceDataValidationError",
    "ReferenceDataNotFoundError",
    # Order Execution
    "OrderExecutionError",
    "OrderRejectionError",
    "OrderTimeoutError",
    "OrderInvalidError",
    # Risk Management
    "RiskManagementError",
    "RiskError",  # Alias for RiskManagementError for backward compatibility
    "RiskLimitExceededError",
    "MarginInsufficientError",
    "PositionLimitExceededError",
    # Broker Related
    "BrokerError",
    "BrokerConnectionError",
    "BrokerAuthenticationError",
    "BrokerRateLimitError",
    # Notification
    "NotificationError",
    "NotificationSendError",
    "NotificationRateLimitError",
    # Persistence
    "PersistenceError",
    "PersistenceConnectionError",
    "PersistenceWriteError",
    "PersistenceReadError",
    # ML/AI
    "ModelError",
    "ModelLoadError",
    "ModelPredictionError",
    "ModelValidationError",
    # Strategy
    "StrategyError",
    # Validation
    "ValidationError",
    # Authentication and Authorization
    "AuthenticationError",
    "AuthorizationError",
    # Insufficient Data
    "InsufficientDataError",
    # Instrument Not Found
    "InstrumentNotFoundError",
    # Reconciliation
    "ReconciliationError",
    "ReconciliationIssueError",
    "ReconciliationFreezeError",
    # Broker
    "BrokerTimeoutError",
    # Signal
    "SignalError",
    "SignalProcessingError",
    "SignalValidationError",
    # Health Check
    "HealthCheckError",
    # Governance
    "GovernanceError",
    "ConstitutionViolationError",
    # Certification
    "CertificationError",
    "ReplayCertificationError",
    "PaperCertificationError",
    # Utilities
    "raise_if_not_true",
    "raise_if_none",
    "raise_if_empty",
    "is_trading_platform_error",
]
