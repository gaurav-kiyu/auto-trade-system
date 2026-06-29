"""Tests for core/exceptions.py - domain-specific exception hierarchy.

Covers:
- All 23 exception classes
- TradingException base: __init__, classify(), to_dict()
- Inheritance hierarchy validation
- Graceful degradation helper: safe_fallback
"""
from __future__ import annotations

from core.exceptions import (
    BrokerAuthError,
    BrokerConnectionError,
    BrokerException,
    BrokerRateLimitError,
    BrokerRejectedError,
    BrokerTimeoutError,
    ChaosError,
    CircuitBreakerError,
    ConfigError,
    CorrelationGuardError,
    DatabaseError,
    ExecutionError,
    FeedDisconnectedError,
    FillError,
    GovernanceError,
    HardHaltError,
    IdempotencyError,
    MarketDataError,
    MaxDrawdownError,
    PersistenceError,
    PositionSizingError,
    ReconciliationError,
    RiskException,
    RiskLimitError,
    SignalError,
    StaleDataError,
    StateFileError,
    TradingException,
    ValidationError,
    safe_fallback,
)


class TestTradingException:
    def test_default_message(self):
        exc = TradingException()
        assert str(exc) == ""

    def test_with_message(self):
        exc = TradingException("Something went wrong")
        assert str(exc) == "Something went wrong"

    def test_with_details(self):
        exc = TradingException("Error", details={"code": 500})
        assert exc.details == {"code": 500}

    def test_default_details_is_empty_dict(self):
        exc = TradingException("Error")
        assert exc.details == {}

    def test_classify_returns_class_name(self):
        exc = TradingException("Error")
        assert exc.classify() == "TradingException"

    def test_to_dict(self):
        exc = TradingException("Test error", details={"key": "val"})
        d = exc.to_dict()
        assert d["type"] == "TradingException"
        assert d["message"] == "Test error"
        assert d["details"] == {"key": "val"}

    def test_is_exception(self):
        exc = TradingException("Error")
        assert isinstance(exc, Exception)


class TestExceptionHierarchy:
    """Validate all exception classes exist and inherit correctly."""

    def test_broker_exceptions(self):
        assert issubclass(BrokerException, TradingException)
        assert issubclass(BrokerTimeoutError, BrokerException)
        assert issubclass(BrokerConnectionError, BrokerException)
        assert issubclass(BrokerAuthError, BrokerException)
        assert issubclass(BrokerRejectedError, BrokerException)
        assert issubclass(BrokerRateLimitError, BrokerException)

    def test_risk_exceptions(self):
        assert issubclass(RiskException, TradingException)
        assert issubclass(RiskLimitError, RiskException)
        assert issubclass(MaxDrawdownError, RiskException)
        assert issubclass(HardHaltError, RiskException)
        assert issubclass(PositionSizingError, RiskException)
        assert issubclass(CorrelationGuardError, RiskException)

    def test_persistence_exceptions(self):
        assert issubclass(PersistenceError, TradingException)
        assert issubclass(DatabaseError, PersistenceError)
        assert issubclass(StateFileError, PersistenceError)

    def test_market_data_exceptions(self):
        assert issubclass(MarketDataError, TradingException)
        assert issubclass(StaleDataError, MarketDataError)
        assert issubclass(FeedDisconnectedError, MarketDataError)

    def test_execution_exceptions(self):
        assert issubclass(ExecutionError, TradingException)
        assert issubclass(IdempotencyError, ExecutionError)
        assert issubclass(FillError, ExecutionError)

    def test_other_exceptions(self):
        assert issubclass(ValidationError, TradingException)
        assert issubclass(ReconciliationError, TradingException)
        assert issubclass(ConfigError, TradingException)
        assert issubclass(SignalError, TradingException)
        assert issubclass(CircuitBreakerError, TradingException)
        assert issubclass(ChaosError, TradingException)
        assert issubclass(GovernanceError, TradingException)

    def test_all_raise_and_catch(self):
        """Verify all exception types can be raised and caught as TradingException."""
        exc_types = [
            BrokerTimeoutError("timeout"),
            BrokerConnectionError("conn"),
            BrokerAuthError("auth"),
            BrokerRejectedError("rejected"),
            BrokerRateLimitError("rate"),
            RiskLimitError("risk"),
            MaxDrawdownError("dd"),
            HardHaltError("halt"),
            PositionSizingError("size"),
            CorrelationGuardError("corr"),
            ValidationError("val"),
            ReconciliationError("recon"),
            DatabaseError("db"),
            StateFileError("state"),
            ConfigError("config"),
            SignalError("signal"),
            StaleDataError("stale"),
            FeedDisconnectedError("feed"),
            CircuitBreakerError("cb"),
            IdempotencyError("idem"),
            FillError("fill"),
            ChaosError("chaos"),
            GovernanceError("gov"),
        ]
        for exc in exc_types:
            assert isinstance(exc, TradingException), f"{type(exc).__name__} not a TradingException"


class TestExceptionClassify:
    def test_broker_timeout_classify(self):
        exc = BrokerTimeoutError("Broker API timeout")
        assert exc.classify() == "BrokerTimeoutError"

    def test_risk_limit_classify(self):
        exc = RiskLimitError("Daily loss breached")
        assert exc.classify() == "RiskLimitError"

    def test_custom_message(self):
        exc = DatabaseError("Connection failed", details={"host": "localhost"})
        assert exc.classify() == "DatabaseError"
        assert exc.details["host"] == "localhost"


class TestExceptionToDict:
    def test_broker_exception_to_dict(self):
        exc = BrokerConnectionError("Network error", details={"host": "api.kite.com"})
        d = exc.to_dict()
        assert d["type"] == "BrokerConnectionError"
        assert d["message"] == "Network error"
        assert d["details"]["host"] == "api.kite.com"

    def test_risk_exception_to_dict(self):
        exc = HardHaltError("Hard halt active")
        d = exc.to_dict()
        assert d["type"] == "HardHaltError"
        assert d["message"] == "Hard halt active"

    def test_governance_exception_serializable(self):
        exc = GovernanceError("Constitution violation", details={"category": "RSK-01", "score": 4.5})
        d = exc.to_dict()
        assert d["type"] == "GovernanceError"
        assert d["details"]["category"] == "RSK-01"
        assert d["details"]["score"] == 4.5


class TestSafeFallback:
    def test_returns_value_when_not_none(self):
        assert safe_fallback("hello") == "hello"
        assert safe_fallback(42) == 42
        assert safe_fallback(0) == 0  # 0 is truthy in this context
        assert safe_fallback(False) is False  # False returned as-is
        assert safe_fallback([]) == []

    def test_returns_default_when_none(self):
        assert safe_fallback(None) is None
        assert safe_fallback(None, default="fallback") == "fallback"
        assert safe_fallback(None, default=42) == 42

    def test_default_none_implicit(self):
        assert safe_fallback(None) is None
