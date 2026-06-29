"""
Tests for core/execution/broker_exceptions.py - Broker Exception Taxonomy.

Covers (40 tests):
- BrokerExceptionType enum (8 classifications)
- All 8 exception subclasses (TransientBrokerError, PermanentBrokerError, etc.)
- should_retry(), is_auth_issue(), is_permanent_failure() methods
- classify_broker_exception() with Kite and Angel error codes
- Fallback classification based on error message keywords
"""

from __future__ import annotations

from core.execution.broker_exceptions import (
    AmbiguousExecutionStateError,
    AuthExpiredError,
    BrokerException,
    BrokerExceptionType,
    BrokerTimeoutError,
    NetworkError,
    OrderRejectedError,
    PermanentBrokerError,
    RateLimitError,
    TransientBrokerError,
    classify_broker_exception,
)

# ── BrokerExceptionType Enum Tests ─────────────────────────────────────────


class TestBrokerExceptionType:
    """BrokerExceptionType enum - 8 classifications."""

    def test_values(self):
        assert BrokerExceptionType.TRANSIENT.value == "TRANSIENT"
        assert BrokerExceptionType.PERMANENT.value == "PERMANENT"
        assert BrokerExceptionType.AUTH_EXPIRED.value == "AUTH_EXPIRED"
        assert BrokerExceptionType.RATE_LIMIT.value == "RATE_LIMIT"
        assert BrokerExceptionType.ORDER_REJECTED.value == "ORDER_REJECTED"
        assert BrokerExceptionType.AMBIGUOUS_STATE.value == "AMBIGUOUS_STATE"
        assert BrokerExceptionType.NETWORK_ERROR.value == "NETWORK_ERROR"
        assert BrokerExceptionType.TIMEOUT.value == "TIMEOUT"

    def test_all_types_distinct(self):
        """All enum values should be unique."""
        values = [t.value for t in BrokerExceptionType]
        assert len(values) == len(set(values))


# ── Base BrokerException Tests ─────────────────────────────────────────────


class TestBrokerException:
    """Base broker exception with type classification."""

    def test_constructor_defaults(self):
        exc = BrokerException("test error", BrokerExceptionType.TRANSIENT, retryable=True)
        assert exc.message == "test error"
        assert exc.exception_type == BrokerExceptionType.TRANSIENT
        assert exc.retryable is True
        assert exc.broker_code is None
        assert exc.original_exception is None
        assert str(exc) == "test error"

    def test_constructor_with_all_fields(self):
        original = ValueError("original")
        exc = BrokerException(
            "detailed error",
            BrokerExceptionType.PERMANENT,
            retryable=False,
            broker_code="ERR001",
            original_exception=original,
        )
        assert exc.message == "detailed error"
        assert exc.exception_type == BrokerExceptionType.PERMANENT
        assert exc.retryable is False
        assert exc.broker_code == "ERR001"
        assert exc.original_exception is original

    def test_should_retry_transient(self):
        exc = BrokerException("transient", BrokerExceptionType.TRANSIENT, retryable=True)
        assert exc.should_retry() is True

    def test_should_retry_permanent_returns_false(self):
        exc = BrokerException("permanent", BrokerExceptionType.PERMANENT, retryable=True)
        assert exc.should_retry() is False  # retryable=True but type is PERMANENT

    def test_should_retry_auth_expired_returns_false(self):
        exc = BrokerException("auth", BrokerExceptionType.AUTH_EXPIRED, retryable=True)
        assert exc.should_retry() is False  # AUTH_EXPIRED not in retryable types

    def test_should_retry_false_explicit(self):
        exc = BrokerException("no retry", BrokerExceptionType.TRANSIENT, retryable=False)
        assert exc.should_retry() is False  # explicitly not retryable

    def test_is_auth_issue_true(self):
        exc = BrokerException("auth", BrokerExceptionType.AUTH_EXPIRED, retryable=False)
        assert exc.is_auth_issue() is True

    def test_is_auth_issue_false(self):
        exc = BrokerException("not auth", BrokerExceptionType.PERMANENT, retryable=False)
        assert exc.is_auth_issue() is False

    def test_is_permanent_failure_true(self):
        exc = BrokerException("perm", BrokerExceptionType.PERMANENT, retryable=False)
        assert exc.is_permanent_failure() is True

    def test_is_permanent_failure_false(self):
        exc = BrokerException("transient", BrokerExceptionType.TRANSIENT, retryable=True)
        assert exc.is_permanent_failure() is False


# ── Exception Subclass Tests ───────────────────────────────────────────────


class TestTransientBrokerError:
    def test_retryable(self):
        exc = TransientBrokerError("temporary issue")
        assert exc.exception_type == BrokerExceptionType.TRANSIENT
        assert exc.retryable is True
        assert exc.should_retry() is True

    def test_with_code(self):
        exc = TransientBrokerError("temp error", broker_code="TMP001")
        assert exc.broker_code == "TMP001"


class TestPermanentBrokerError:
    def test_not_retryable(self):
        exc = PermanentBrokerError("permanent failure")
        assert exc.exception_type == BrokerExceptionType.PERMANENT
        assert exc.retryable is False
        assert exc.should_retry() is False
        assert exc.is_permanent_failure() is True

    def test_with_original(self):
        original = KeyError("missing")
        exc = PermanentBrokerError("perm error", original=original)
        assert exc.original_exception is original


class TestAuthExpiredError:
    def test_not_retryable(self):
        exc = AuthExpiredError("session expired")
        assert exc.exception_type == BrokerExceptionType.AUTH_EXPIRED
        assert exc.retryable is False
        assert exc.should_retry() is False
        assert exc.is_auth_issue() is True


class TestRateLimitError:
    def test_retryable(self):
        exc = RateLimitError("too many requests")
        assert exc.exception_type == BrokerExceptionType.RATE_LIMIT
        assert exc.retryable is True
        assert exc.should_retry() is True


class TestOrderRejectedError:
    def test_defaults(self):
        exc = OrderRejectedError("order rejected")
        assert exc.exception_type == BrokerExceptionType.ORDER_REJECTED
        assert exc.retryable is False
        assert exc.reason is None
        assert exc.should_retry() is False

    def test_with_reason(self):
        exc = OrderRejectedError("rejected", reason="insufficient_margin")
        assert exc.reason == "insufficient_margin"


class TestAmbiguousExecutionStateError:
    def test_defaults(self):
        exc = AmbiguousExecutionStateError("ambiguous state")
        assert exc.exception_type == BrokerExceptionType.AMBIGUOUS_STATE
        assert exc.retryable is False
        assert exc.broker_order_id is None

    def test_with_order_id(self):
        exc = AmbiguousExecutionStateError(
            "ambiguous", broker_order_id="ORDER123"
        )
        assert exc.broker_order_id == "ORDER123"


class TestNetworkError:
    def test_retryable(self):
        exc = NetworkError("connection lost")
        assert exc.exception_type == BrokerExceptionType.NETWORK_ERROR
        assert exc.retryable is True
        assert exc.should_retry() is True


class TestBrokerTimeoutError:
    def test_retryable(self):
        exc = BrokerTimeoutError("request timed out")
        assert exc.exception_type == BrokerExceptionType.TIMEOUT
        assert exc.retryable is True
        assert exc.should_retry() is True


# ── classify_broker_exception Tests ────────────────────────────────────────


class TestClassifyBrokerException:
    """classify_broker_exception - maps raw exceptions to broker taxonomy."""

    def test_timeout_message(self):
        exc = TimeoutError("request timed out")
        result = classify_broker_exception(exc)
        assert isinstance(result, BrokerTimeoutError)
        assert result.exception_type == BrokerExceptionType.TIMEOUT
        assert result.should_retry() is True

    def test_connection_message(self):
        exc = ConnectionError("connection refused")
        result = classify_broker_exception(exc)
        assert isinstance(result, NetworkError)
        assert result.should_retry() is True

    def test_network_message(self):
        exc = OSError("network is unreachable")
        result = classify_broker_exception(exc)
        assert isinstance(result, NetworkError)

    def test_rate_limit_message(self):
        exc = Exception("rate limit exceeded")
        result = classify_broker_exception(exc)
        assert isinstance(result, RateLimitError)
        assert result.should_retry() is True

    def test_auth_message(self):
        exc = Exception("auth token expired")
        result = classify_broker_exception(exc)
        assert isinstance(result, AuthExpiredError)
        assert result.is_auth_issue() is True

    def test_token_message(self):
        exc = Exception("invalid token")
        result = classify_broker_exception(exc)
        assert isinstance(result, AuthExpiredError)

    def test_session_message(self):
        exc = Exception("session expired")
        result = classify_broker_exception(exc)
        assert isinstance(result, AuthExpiredError)

    def test_margin_message(self):
        exc = Exception("insufficient margin")
        result = classify_broker_exception(exc)
        assert isinstance(result, PermanentBrokerError)
        assert result.is_permanent_failure() is True

    def test_rejected_message(self):
        exc = Exception("order rejected by exchange")
        result = classify_broker_exception(exc)
        assert isinstance(result, OrderRejectedError)

    def test_invalid_message(self):
        exc = Exception("invalid order quantity")
        result = classify_broker_exception(exc)
        assert isinstance(result, OrderRejectedError)

    def test_default_to_transient(self):
        exc = Exception("some unknown error")
        result = classify_broker_exception(exc)
        assert isinstance(result, TransientBrokerError)
        assert result.should_retry() is True

    def test_kite_error_code_mapping(self):
        """Kite error codes should map to correct exception types."""
        class MockKiteError(Exception):
            def __init__(self, code):
                self.code = code
                super().__init__(f"Kite error {code}")

        # Invalid symbol -> PERMANENT
        exc = MockKiteError("36001")
        result = classify_broker_exception(exc, broker_name="KITE")
        assert isinstance(result, PermanentBrokerError)
        assert result.broker_code == "36001"

        # Market closed -> TRANSIENT
        exc = MockKiteError("36101")
        result = classify_broker_exception(exc, broker_name="KITE")
        assert isinstance(result, TransientBrokerError)
        assert result.should_retry() is True

        # Session expired -> AUTH_EXPIRED
        exc = MockKiteError("40001")
        result = classify_broker_exception(exc, broker_name="KITE")
        assert isinstance(result, AuthExpiredError)

        # Invalid token -> AUTH_EXPIRED
        exc = MockKiteError("40002")
        result = classify_broker_exception(exc, broker_name="KITE")
        assert isinstance(result, AuthExpiredError)

    def test_angel_error_code_mapping(self):
        """Angel One error codes should map to correct exception types."""
        class MockAngelError(Exception):
            def __init__(self, code):
                self.error_code = code
                super().__init__(f"Angel error {code}")

        # Invalid API key -> PERMANENT
        exc = MockAngelError("AG001")
        result = classify_broker_exception(exc, broker_name="ANGEL")
        assert isinstance(result, PermanentBrokerError)
        assert result.broker_code == "AG001"

        # Rate limit exceeded
        exc = MockAngelError("AG201")
        result = classify_broker_exception(exc, broker_name="ANGEL")
        assert isinstance(result, RateLimitError)
        assert result.should_retry() is True

        # Order rejected -> ORDER_REJECTED
        exc = MockAngelError("AG102")
        result = classify_broker_exception(exc, broker_name="ANGEL")
        assert isinstance(result, OrderRejectedError)
        assert result.exception_type.value == "ORDER_REJECTED"

    def test_kite_duplicate_order_mapping(self):
        """Kite duplicate order code -> PERMANENT."""
        class MockKiteError(Exception):
            def __init__(self, code):
                self.code = code
                super().__init__(f"Kite error {code}")

        exc = MockKiteError("36201")
        result = classify_broker_exception(exc, broker_name="KITE")
        assert isinstance(result, PermanentBrokerError)
        assert result.broker_code == "36201"

    def test_angel_token_expired_mapping(self):
        """Angel token expired -> AUTH_EXPIRED."""
        class MockAngelError(Exception):
            def __init__(self, code):
                self.error_code = code
                super().__init__(f"Angel error {code}")

        exc = MockAngelError("AG003")
        result = classify_broker_exception(exc, broker_name="ANGEL")
        assert isinstance(result, AuthExpiredError)

    # ── Fyers Error Code Tests ────────────────────────────────────────

    def test_fyers_invalid_credentials(self):
        """Fyers F-1000 -> PERMANENT."""
        class MockFyersError(Exception):
            def __init__(self, code):
                self.code = code
                super().__init__(f"Fyers error {code}")

        exc = MockFyersError("F-1000")
        result = classify_broker_exception(exc, broker_name="FYERS")
        assert isinstance(result, PermanentBrokerError)
        assert result.broker_code == "F-1000"

    def test_fyers_token_expired(self):
        """Fyers F-1001 -> AUTH_EXPIRED."""
        class MockFyersError(Exception):
            def __init__(self, code):
                self.code = code
                super().__init__(f"Fyers error {code}")

        exc = MockFyersError("F-1001")
        result = classify_broker_exception(exc, broker_name="FYERS")
        assert isinstance(result, AuthExpiredError)

    def test_fyers_rate_limit(self):
        """Fyers F-2001 -> RATE_LIMIT."""
        class MockFyersError(Exception):
            def __init__(self, code):
                self.code = code
                super().__init__(f"Fyers error {code}")

        exc = MockFyersError("F-2001")
        result = classify_broker_exception(exc, broker_name="FYERS")
        assert isinstance(result, RateLimitError)
        assert result.should_retry() is True

    def test_fyers_timeout(self):
        """Fyers F-4002 -> TIMEOUT."""
        class MockFyersError(Exception):
            def __init__(self, code):
                self.code = code
                super().__init__(f"Fyers error {code}")

        exc = MockFyersError("F-4002")
        result = classify_broker_exception(exc, broker_name="FYERS")
        assert isinstance(result, BrokerTimeoutError)
        assert result.should_retry() is True

    def test_fyers_market_closed(self):
        """Fyers F-1005 -> TRANSIENT."""
        class MockFyersError(Exception):
            def __init__(self, code):
                self.code = code
                super().__init__(f"Fyers error {code}")

        exc = MockFyersError("F-1005")
        result = classify_broker_exception(exc, broker_name="FYERS")
        assert isinstance(result, TransientBrokerError)
        assert result.should_retry() is True

    def test_fyers_insufficient_balance(self):
        """Fyers F-1003 -> PERMANENT."""
        class MockFyersError(Exception):
            def __init__(self, code):
                self.code = code
                super().__init__(f"Fyers error {code}")

        exc = MockFyersError("F-1003")
        result = classify_broker_exception(exc, broker_name="FYERS")
        assert isinstance(result, PermanentBrokerError)

    # ── Dhan Error Code Tests ────────────────────────────────────────

    def test_dhan_invalid_client_id(self):
        """Dhan DH-001 -> PERMANENT."""
        class MockDhanError(Exception):
            def __init__(self, code):
                self.error_code = code
                super().__init__(f"Dhan error {code}")

        exc = MockDhanError("DH-001")
        result = classify_broker_exception(exc, broker_name="DHAN")
        assert isinstance(result, PermanentBrokerError)
        assert result.broker_code == "DH-001"

    def test_dhan_token_expired(self):
        """Dhan DH-003 -> AUTH_EXPIRED."""
        class MockDhanError(Exception):
            def __init__(self, code):
                self.error_code = code
                super().__init__(f"Dhan error {code}")

        exc = MockDhanError("DH-003")
        result = classify_broker_exception(exc, broker_name="DHAN")
        assert isinstance(result, AuthExpiredError)

    def test_dhan_rate_limit(self):
        """Dhan DH-201 -> RATE_LIMIT."""
        class MockDhanError(Exception):
            def __init__(self, code):
                self.error_code = code
                super().__init__(f"Dhan error {code}")

        exc = MockDhanError("DH-201")
        result = classify_broker_exception(exc, broker_name="DHAN")
        assert isinstance(result, RateLimitError)
        assert result.should_retry() is True

    def test_dhan_timeout(self):
        """Dhan DH-402 -> TIMEOUT."""
        class MockDhanError(Exception):
            def __init__(self, code):
                self.error_code = code
                super().__init__(f"Dhan error {code}")

        exc = MockDhanError("DH-402")
        result = classify_broker_exception(exc, broker_name="DHAN")
        assert isinstance(result, BrokerTimeoutError)
        assert result.should_retry() is True

    def test_dhan_order_rejected(self):
        """Dhan DH-103 -> ORDER_REJECTED."""
        class MockDhanError(Exception):
            def __init__(self, code):
                self.error_code = code
                super().__init__(f"Dhan error {code}")

        exc = MockDhanError("DH-103")
        result = classify_broker_exception(exc, broker_name="DHAN")
        assert isinstance(result, OrderRejectedError)

    def test_dhan_insufficient_margin(self):
        """Dhan DH-101 -> PERMANENT."""
        class MockDhanError(Exception):
            def __init__(self, code):
                self.error_code = code
                super().__init__(f"Dhan error {code}")

        exc = MockDhanError("DH-101")
        result = classify_broker_exception(exc, broker_name="DHAN")
        assert isinstance(result, PermanentBrokerError)

    # ── Unknown Broker Fallback Tests ─────────────────────────────────

    def test_unknown_broker_name_uses_fallback(self):
        """Unknown broker names should use message-based fallback."""
        exc = Exception("timeout in unknown broker")
        result = classify_broker_exception(exc, broker_name="UNKNOWN")
        assert isinstance(result, BrokerTimeoutError)
