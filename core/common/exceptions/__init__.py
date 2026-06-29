"""
Trading Platform Exception Hierarchy — DEPRECATED SHIM

⚠️  DEPRECATED: This module is preserved for backward compatibility only.
   Import directly from ``core.exceptions`` instead:

       from core.exceptions import TradingException, ValidationError, ...

   All exception classes defined here are re-exported from ``core.exceptions``.
   This shim will be removed in v3.0.
"""

from __future__ import annotations

import warnings

from core.exceptions import (
    # Authentication & Authorization
    AuthenticationError,
    AuthorizationError,
    BrokerAuthenticationError,
    # Broker
    BrokerAuthError,
    BrokerConnectionError,
    BrokerException,
    BrokerRateLimitError,
    BrokerRejectedError,
    BrokerTimeoutError,
    # Certification
    CertificationError,
    # Chaos
    ChaosError,
    # Circuit Breaker
    CircuitBreakerError,
    # Config
    ConfigError,
    # Risk
    CorrelationGuardError,
    # Persistence
    DatabaseError,
    # Execution
    ExecutionError,
    # Market Data
    FeedDisconnectedError,
    FillError,
    # Governance
    GovernanceError,
    HardHaltError,
    # Health Check
    HealthCheckError,
    IdempotencyError,
    InstrumentNotFoundError,
    # Insufficient Data
    InsufficientDataError,
    MarginInsufficientError,
    MarketDataError,
    MarketDataSourceError,
    MarketDataStalenessError,
    MarketDataValidationError,
    MaxDrawdownError,
    PersistenceConnectionError,
    PersistenceError,
    PersistenceReadError,
    PersistenceWriteError,
    PositionLimitExceededError,
    PositionSizingError,
    # Reconciliation
    ReconciliationError,
    RiskException,
    RiskLimitError,
    RiskLimitExceededError,
    # Signal
    SignalError,
    SignalValidationError,
    StaleDataError,
    StateFileError,
    # Base
    TradingException,
    # Validation
    ValidationError,
    # Helpers
    is_trading_platform_error,
    raise_if_empty,
    raise_if_none,
    raise_if_not_true,
    safe_fallback,
)

# ── Backward-compat aliases (these names existed in earlier versions) ──────────

ConfigurationError = ConfigError
ConfigurationValidationError = ValidationError
ConfigurationLoadError = ConfigError
ConfigurationSecretError = ConfigError
InvalidConfigurationError = ConfigError
MissingConfigurationError = ConfigError

CredentialStorageError = TradingException
CredentialNotFoundError = TradingException
CredentialStorageBackendError = TradingException

HistoricalDataError = MarketDataError

ReferenceDataError = MarketDataError
ReferenceDataSourceError = MarketDataSourceError
ReferenceDataValidationError = MarketDataValidationError
ReferenceDataNotFoundError = InsufficientDataError

OrderExecutionError = ExecutionError
OrderRejectionError = ExecutionError
OrderTimeoutError = ExecutionError
OrderInvalidError = ValidationError

RiskManagementError = RiskException
RiskError = RiskException

NotificationError = TradingException
NotificationSendError = TradingException
NotificationRateLimitError = TradingException

ModelError = TradingException
ModelLoadError = TradingException
ModelPredictionError = TradingException
ModelValidationError = TradingException

StrategyError = TradingException

ReconciliationIssueError = ReconciliationError
ReconciliationFreezeError = ReconciliationError

SignalProcessingError = SignalError

ConstitutionViolationError = GovernanceError

ReplayCertificationError = CertificationError
PaperCertificationError = CertificationError

# ── Emit deprecation warning on first import ──────────────────────────────────

warnings.warn(
    "core.common.exceptions is deprecated. Import from core.exceptions instead. "
    "This shim will be removed in v3.0.",
    DeprecationWarning,
    stacklevel=2,
)

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
    # Config (and backward-compat aliases)
    "ConfigError",
    "ConfigurationError",
    "ConfigurationLoadError",
    "ConfigurationSecretError",
    "ConfigurationValidationError",
    "InvalidConfigurationError",
    "MissingConfigurationError",
    # Credential Storage (backward-compat)
    "CredentialNotFoundError",
    "CredentialStorageBackendError",
    "CredentialStorageError",
    # Execution
    "ExecutionError",
    "FillError",
    "IdempotencyError",
    # Governance
    "GovernanceError",
    "ConstitutionViolationError",
    # Health Check
    "HealthCheckError",
    # Historical Data (backward-compat)
    "HistoricalDataError",
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
    # Model (backward-compat)
    "ModelError",
    "ModelLoadError",
    "ModelPredictionError",
    "ModelValidationError",
    # Notification (backward-compat)
    "NotificationError",
    "NotificationRateLimitError",
    "NotificationSendError",
    # Order Execution (backward-compat)
    "OrderExecutionError",
    "OrderInvalidError",
    "OrderRejectionError",
    "OrderTimeoutError",
    # Persistence
    "DatabaseError",
    "PersistenceConnectionError",
    "PersistenceError",
    "PersistenceReadError",
    "PersistenceWriteError",
    "StateFileError",
    # Reconciliation
    "ReconciliationError",
    "ReconciliationFreezeError",
    "ReconciliationIssueError",
    # Reference Data (backward-compat)
    "ReferenceDataError",
    "ReferenceDataNotFoundError",
    "ReferenceDataSourceError",
    "ReferenceDataValidationError",
    # Risk
    "CorrelationGuardError",
    "HardHaltError",
    "MarginInsufficientError",
    "MaxDrawdownError",
    "PositionLimitExceededError",
    "PositionSizingError",
    "RiskError",
    "RiskException",
    "RiskLimitError",
    "RiskLimitExceededError",
    "RiskManagementError",
    # Signal
    "SignalError",
    "SignalProcessingError",
    "SignalValidationError",
    # Strategy
    "StrategyError",
    # Validation
    "ValidationError",
    # Certification
    "CertificationError",
    "ReplayCertificationError",
    "PaperCertificationError",
    # Helpers
    "is_trading_platform_error",
    "raise_if_empty",
    "raise_if_none",
    "raise_if_not_true",
    "safe_fallback",
]
