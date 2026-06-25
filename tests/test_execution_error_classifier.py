"""Tests for core.execution_error_classifier - broker error classification."""

from __future__ import annotations

from core.execution_error_classifier import (
    BrokerErrorClassifier,
    ErrorCategory,
    classify_broker_error,
)


class TestBrokerErrorClassifier:
    """Tests for BrokerErrorClassifier - error classification for retry strategy."""

    def setup_method(self) -> None:
        self.classifier = BrokerErrorClassifier()

    # ── Retriable Errors ────────────────────────────────────────────────

    def test_timeout_is_retriable(self) -> None:
        err = TimeoutError("Connection timeout after 5s")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.RETRIABLE
        assert result.can_retry is True
        assert result.retry_delay == 5.0

    def test_connection_refused_is_retriable(self) -> None:
        err = ConnectionRefusedError("Connection refused")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.RETRIABLE
        assert result.can_retry is True
        assert result.retry_delay == 2.0

    def test_network_error_is_retriable(self) -> None:
        err = ConnectionError("Network is unreachable")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.RETRIABLE
        assert result.can_retry is True
        assert result.retry_delay == 3.0

    def test_http_503_is_retriable(self) -> None:
        err = Exception("HTTP 503 Service Unavailable")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.RETRIABLE
        assert result.can_retry is True

    def test_generic_timeout_message_is_retriable(self) -> None:
        err = Exception("timed out")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.RETRIABLE
        assert result.can_retry is True
        assert result.retry_delay == BrokerErrorClassifier.DEFAULT_RETRY_DELAY

    def test_reset_error_is_retriable(self) -> None:
        err = ConnectionResetError("Connection reset by peer")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.RETRIABLE
        assert result.can_retry is True

    # ── Non-Retriable Errors ────────────────────────────────────────────

    def test_unauthorized_is_non_retriable(self) -> None:
        err = PermissionError("Unauthorized: invalid token")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.NON_RETRIABLE
        assert result.can_retry is False
        assert result.retry_delay == 0

    def test_margin_insufficient_is_non_retriable(self) -> None:
        err = Exception("Insufficient margin for order")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.NON_RETRIABLE
        assert result.can_retry is False

    def test_rejected_order_is_non_retriable(self) -> None:
        err = Exception("Order rejected: price out of range")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.NON_RETRIABLE
        assert result.can_retry is False

    def test_token_expired_is_non_retriable(self) -> None:
        err = Exception("Token has expired")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.NON_RETRIABLE
        assert result.can_retry is False

    def test_http_401_is_non_retriable(self) -> None:
        err = Exception("HTTP 401 Unauthorized")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.NON_RETRIABLE
        assert result.can_retry is False

    def test_blocked_account_is_non_retriable(self) -> None:
        err = Exception("Account blocked")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.NON_RETRIABLE
        assert result.can_retry is False

    # ── Unknown Errors ──────────────────────────────────────────────────

    def test_unknown_error_is_retriable_with_default_delay(self) -> None:
        err = Exception("Some random error occurred")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.UNKNOWN
        assert result.can_retry is True
        assert result.retry_delay == BrokerErrorClassifier.DEFAULT_RETRY_DELAY

    def test_custom_exception_type_is_unknown(self) -> None:
        class CustomError(Exception):
            pass

        err = CustomError("custom message")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.UNKNOWN
        assert result.can_retry is True

    # ── Message Precedence ──────────────────────────────────────────────

    def test_non_retriable_takes_precedence_over_retriable(self) -> None:
        """Non-retriable patterns should be checked first."""
        err = Exception("timeout with insufficient balance")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.NON_RETRIABLE
        assert result.can_retry is False

    def test_case_insensitive_matching(self) -> None:
        err = Exception("TIMEOUT")
        result = self.classifier.classify(err)
        assert result.category == ErrorCategory.RETRIABLE

    # ── Convenience Function ────────────────────────────────────────────

    def test_classify_broker_error_convenience(self) -> None:
        err = Exception("timed out")
        result = classify_broker_error(err)
        assert result.category == ErrorCategory.RETRIABLE
        assert result.can_retry is True
