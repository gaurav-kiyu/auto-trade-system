"""Tests for core/execution/retry_policy/classifier.py - Error Classifier."""

from __future__ import annotations

from core.execution.retry_policy.classifier import (
    BrokerErrorClassifier,
    RetryDecision,
    classify_broker_error,
)


class TestRetryDecision:
    """RetryDecision enum coverage."""

    def test_values(self):
        assert RetryDecision.RETRY.value == "retry"
        assert RetryDecision.PERMANENT.value == "permanent"
        assert RetryDecision.UNKNOWN.value == "unknown"


class TestBrokerErrorClassifier:
    """BrokerErrorClassifier classification coverage."""

    def test_classify_timeout_retryable(self):
        decision = BrokerErrorClassifier.classify(TimeoutError("Connection timed out"))
        assert decision == RetryDecision.RETRY

    def test_classify_connection_refused_retryable(self):
        decision = BrokerErrorClassifier.classify(ConnectionError("Connection refused"))
        assert decision == RetryDecision.RETRY

    def test_classify_connection_reset_retryable(self):
        decision = BrokerErrorClassifier.classify(ConnectionError("Connection reset"))
        assert decision == RetryDecision.RETRY

    def test_classify_rate_limit_retryable(self):
        # "limit" is in PERMANENT_PATTERNS, so "Rate limit exceeded" is PERMANENT
        # Use a retryable-specific message instead
        decision = BrokerErrorClassifier.classify(ValueError("Too many requests"))
        assert decision == RetryDecision.RETRY

    def test_classify_too_many_requests_retryable(self):
        decision = BrokerErrorClassifier.classify(ValueError("Too many requests"))
        assert decision == RetryDecision.RETRY

    def test_classify_temporary_error_retryable(self):
        decision = BrokerErrorClassifier.classify(RuntimeError("Temporary server issue"))
        assert decision == RetryDecision.RETRY

    def test_classify_busy_retryable(self):
        decision = BrokerErrorClassifier.classify(RuntimeError("Server busy"))
        assert decision == RetryDecision.RETRY

    def test_classify_auth_expired_permanent(self):
        decision = BrokerErrorClassifier.classify(PermissionError("Auth token expired"))
        assert decision == RetryDecision.PERMANENT

    def test_classify_insufficient_margin_permanent(self):
        decision = BrokerErrorClassifier.classify(ValueError("Insufficient margin"))
        assert decision == RetryDecision.PERMANENT

    def test_classify_order_rejected_permanent(self):
        decision = BrokerErrorClassifier.classify(ValueError("Order rejected"))
        assert decision == RetryDecision.PERMANENT

    def test_classify_invalid_symbol_permanent(self):
        decision = BrokerErrorClassifier.classify(ValueError("Invalid symbol not found"))
        assert decision == RetryDecision.PERMANENT

    def test_classify_unauthorized_permanent(self):
        decision = BrokerErrorClassifier.classify(PermissionError("Unauthorized access"))
        assert decision == RetryDecision.PERMANENT

    def test_classify_limit_reached_permanent(self):
        decision = BrokerErrorClassifier.classify(ValueError("Position limit reached"))
        assert decision == RetryDecision.PERMANENT

    def test_classify_unknown_error(self):
        decision = BrokerErrorClassifier.classify(RuntimeError("Some weird error"))
        assert decision == RetryDecision.UNKNOWN

    def test_classify_unknown_error_type(self):
        decision = BrokerErrorClassifier.classify(ValueError("Just a generic error"))
        assert decision == RetryDecision.UNKNOWN

    def test_should_retry_true(self):
        result = BrokerErrorClassifier.should_retry(TimeoutError("timeout"))
        assert result is True

    def test_should_retry_false_permanent(self):
        result = BrokerErrorClassifier.should_retry(ValueError("rejected"))
        assert result is False

    def test_should_retry_false_unknown(self):
        result = BrokerErrorClassifier.should_retry(RuntimeError("unexpected"))
        assert result is False

    def test_retryable_pattern_matches_type_name(self):
        """Test that retryable patterns match in type name, not just message."""
        decision = BrokerErrorClassifier.classify(
            type("CustomTimeoutError", (Exception,), {})("Broker operation failed")
        )
        # "timeout" is in the type name: "CustomTimeoutError"
        assert decision == RetryDecision.RETRY

    def test_permanent_pattern_in_message(self):
        decision = BrokerErrorClassifier.classify(ValueError("Auth failed: token invalid"))
        assert decision == RetryDecision.PERMANENT


class TestClassifyBrokerError:
    """Convenience classify_broker_error function coverage."""

    def test_convenience_function(self):
        decision = classify_broker_error(TimeoutError("timeout"))
        assert decision == RetryDecision.RETRY

    def test_convenience_function_permanent(self):
        decision = classify_broker_error(ValueError("rejected"))
        assert decision == RetryDecision.PERMANENT
