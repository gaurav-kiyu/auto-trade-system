"""Tests for core/exceptions.py — Domain-Specific Exception Hierarchy."""

from __future__ import annotations

import pytest

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
    """TradingException base class coverage."""

    def test_basic_exception(self):
        exc = TradingException("Something went wrong")
        assert str(exc) == "Something went wrong"
        assert exc.details == {}

    def test_with_details(self):
        exc = TradingException("Risk breach", details={"limit": 1000, "actual": 1500})
        assert exc.details["limit"] == 1000
        assert exc.details["actual"] == 1500

    def test_classify(self):
        exc = TradingException("test")
        assert exc.classify() == "TradingException"

    def test_to_dict(self):
        exc = TradingException("test", details={"key": "val"})
        d = exc.to_dict()
        assert d["type"] == "TradingException"
        assert d["message"] == "test"
        assert d["details"] == {"key": "val"}

    def test_default_message(self):
        exc = TradingException()
        assert str(exc) == ""


class TestBrokerExceptions:
    """Broker exception hierarchy coverage."""

    def test_broker_exception_is_subclass(self):
        assert issubclass(BrokerException, TradingException)

    def test_broker_timeout(self):
        exc = BrokerTimeoutError("API timeout after 5s")
        assert str(exc) == "API timeout after 5s"
        assert exc.classify() == "BrokerTimeoutError"

    def test_broker_connection_error(self):
        exc = BrokerConnectionError("Connection refused")
        assert exc.classify() == "BrokerConnectionError"

    def test_broker_auth_error(self):
        exc = BrokerAuthError("Token expired")
        assert exc.classify() == "BrokerAuthError"

    def test_broker_rejected_error(self):
        exc = BrokerRejectedError("Insufficient margin")
        assert exc.classify() == "BrokerRejectedError"

    def test_broker_rate_limit(self):
        exc = BrokerRateLimitError("Rate limit exceeded")
        assert exc.classify() == "BrokerRateLimitError"

    def test_all_broker_exceptions_are_broker_exception(self):
        exceptions = [
            BrokerTimeoutError("a"),
            BrokerConnectionError("b"),
            BrokerAuthError("c"),
            BrokerRejectedError("d"),
            BrokerRateLimitError("e"),
        ]
        for exc in exceptions:
            assert isinstance(exc, BrokerException)


class TestRiskExceptions:
    """Risk exception hierarchy coverage."""

    def test_risk_exception_is_subclass(self):
        assert issubclass(RiskException, TradingException)

    def test_risk_limit_error(self):
        exc = RiskLimitError("Max daily loss exceeded")
        assert exc.classify() == "RiskLimitError"

    def test_max_drawdown_error(self):
        exc = MaxDrawdownError("Drawdown exceeds limit")
        assert exc.classify() == "MaxDrawdownError"

    def test_hard_halt_error(self):
        exc = HardHaltError("Hard halt active")
        assert exc.classify() == "HardHaltError"

    def test_position_sizing_error(self):
        exc = PositionSizingError("Invalid size")
        assert exc.classify() == "PositionSizingError"

    def test_correlation_guard_error(self):
        exc = CorrelationGuardError("Correlation block")
        assert exc.classify() == "CorrelationGuardError"

    def test_all_risk_exceptions_are_risk_exception(self):
        exceptions = [
            RiskLimitError("a"),
            MaxDrawdownError("b"),
            HardHaltError("c"),
            PositionSizingError("d"),
            CorrelationGuardError("e"),
        ]
        for exc in exceptions:
            assert isinstance(exc, RiskException)


class TestValidationException:
    """ValidationError coverage."""

    def test_validation_error(self):
        exc = ValidationError("Invalid input")
        assert exc.classify() == "ValidationError"
        assert isinstance(exc, TradingException)

    def test_with_details(self):
        exc = ValidationError("Field required", details={"field": "symbol"})
        assert exc.details["field"] == "symbol"


class TestReconciliationException:
    """ReconciliationError coverage."""

    def test_reconciliation_error(self):
        exc = ReconciliationError("State mismatch")
        assert exc.classify() == "ReconciliationError"
        assert isinstance(exc, TradingException)


class TestPersistenceExceptions:
    """Persistence exception hierarchy coverage."""

    def test_persistence_error(self):
        exc = PersistenceError("File error")
        assert exc.classify() == "PersistenceError"
        assert isinstance(exc, TradingException)

    def test_database_error(self):
        exc = DatabaseError("SQLite error")
        assert exc.classify() == "DatabaseError"
        assert isinstance(exc, PersistenceError)

    def test_state_file_error(self):
        exc = StateFileError("trader_state.json write failed")
        assert exc.classify() == "StateFileError"
        assert isinstance(exc, PersistenceError)


class TestConfigException:
    """ConfigError coverage."""

    def test_config_error(self):
        exc = ConfigError("Missing key")
        assert exc.classify() == "ConfigError"
        assert isinstance(exc, TradingException)


class TestSignalException:
    """SignalError coverage."""

    def test_signal_error(self):
        exc = SignalError("Pipeline error")
        assert exc.classify() == "SignalError"
        assert isinstance(exc, TradingException)


class TestMarketDataExceptions:
    """Market data exception hierarchy coverage."""

    def test_market_data_error(self):
        exc = MarketDataError("Feed error")
        assert exc.classify() == "MarketDataError"
        assert isinstance(exc, TradingException)

    def test_stale_data_error(self):
        exc = StaleDataError("Data too old")
        assert exc.classify() == "StaleDataError"
        assert isinstance(exc, MarketDataError)

    def test_feed_disconnected_error(self):
        exc = FeedDisconnectedError("WebSocket down")
        assert exc.classify() == "FeedDisconnectedError"
        assert isinstance(exc, MarketDataError)


class TestCircuitBreakerException:
    """CircuitBreakerError coverage."""

    def test_circuit_breaker_error(self):
        exc = CircuitBreakerError("Circuit open")
        assert exc.classify() == "CircuitBreakerError"
        assert isinstance(exc, TradingException)


class TestExecutionExceptions:
    """Execution exception hierarchy coverage."""

    def test_execution_error(self):
        exc = ExecutionError("Execution failed")
        assert exc.classify() == "ExecutionError"
        assert isinstance(exc, TradingException)

    def test_idempotency_error(self):
        exc = IdempotencyError("Duplicate order")
        assert exc.classify() == "IdempotencyError"
        assert isinstance(exc, ExecutionError)

    def test_fill_error(self):
        exc = FillError("Fill mismatch")
        assert exc.classify() == "FillError"
        assert isinstance(exc, ExecutionError)


class TestChaosException:
    """ChaosError coverage."""

    def test_chaos_error(self):
        exc = ChaosError("Injection failed")
        assert exc.classify() == "ChaosError"
        assert isinstance(exc, TradingException)


class TestGovernanceException:
    """GovernanceError coverage."""

    def test_governance_error(self):
        exc = GovernanceError("Constitution violation")
        assert exc.classify() == "GovernanceError"
        assert isinstance(exc, TradingException)


class TestSafeFallback:
    """safe_fallback helper coverage."""

    def test_returns_value_when_not_none(self):
        assert safe_fallback(42) == 42
        assert safe_fallback("hello") == "hello"
        assert safe_fallback(0) == 0
        assert safe_fallback(False) is False
        assert safe_fallback([]) == []

    def test_returns_default_when_none(self):
        assert safe_fallback(None) is None
        assert safe_fallback(None, "default") == "default"
        assert safe_fallback(None, 0) == 0

    def test_returns_none_default_when_not_specified(self):
        result = safe_fallback(None)
        assert result is None


class TestExceptionDictConsistency:
    """Verify all exceptions have consistent to_dict output."""

    @pytest.mark.parametrize("exc_cls, message", [
        (TradingException, "base"),
        (BrokerTimeoutError, "timeout"),
        (RiskLimitError, "limit"),
        (ValidationError, "validation"),
        (DatabaseError, "db"),
        (StaleDataError, "stale"),
        (CircuitBreakerError, "cb"),
        (GovernanceError, "gov"),
        (ChaosError, "chaos"),
    ])
    def test_to_dict_consistency(self, exc_cls, message):
        exc = exc_cls(message, details={"code": 123})
        d = exc.to_dict()
        assert d["type"] == exc_cls.__name__
        assert d["message"] == message
        assert d["details"] == {"code": 123}

    def test_all_exceptions_have_unique_classify(self):
        """Every exception type should return its own class name."""
        exceptions = [
            TradingException,
            BrokerException,
            BrokerTimeoutError,
            RiskException,
            RiskLimitError,
            ValidationError,
            ReconciliationError,
            PersistenceError,
            DatabaseError,
            ConfigError,
            SignalError,
            MarketDataError,
            StaleDataError,
            CircuitBreakerError,
            ExecutionError,
            IdempotencyError,
            GovernanceError,
        ]
        class_names = [e.__name__ for e in exceptions]
        assert len(class_names) == len(set(class_names))
