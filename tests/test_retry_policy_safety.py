"""
Tests for retry policy safety classification.
Verifies that safe vs unsafe retries are properly classified.
"""
import pytest
from core.execution.retry_policy.manager import (
    RetryPolicy,
    RetrySafety,
    RetryResult,
    safe_retry_operation,
)


class TestRetryClassification:
    def test_timeout_classified_as_safe(self):
        policy = RetryPolicy()
        err = TimeoutError("Connection timeout")
        assert policy.classify_error(err) == RetrySafety.SAFE

    def test_connection_error_classified_as_safe(self):
        policy = RetryPolicy()
        err = ConnectionError("Temporary unavailable")
        assert policy.classify_error(err) == RetrySafety.SAFE

    def test_unknown_status_classified_as_unknown(self):
        policy = RetryPolicy()
        err = RuntimeError("Submission status unknown")
        assert policy.classify_error(err) == RetrySafety.UNKNOWN

    def test_rejection_classified_as_unsafe(self):
        policy = RetryPolicy()
        err = ValueError("Order rejected: insufficient margin")
        assert policy.classify_error(err) == RetrySafety.UNSAFE

    def test_invalid_parameter_classified_as_unsafe(self):
        policy = RetryPolicy()
        err = ValueError("Invalid quantity: must be positive")
        assert policy.classify_error(err) == RetrySafety.UNSAFE

    def test_default_unknown_classification(self):
        policy = RetryPolicy()
        err = Exception("Something went wrong")
        assert policy.classify_error(err) == RetrySafety.UNKNOWN


class TestRetryExecution:
    def test_safe_retry_succeeds(self):
        call_count = 0

        def flaky_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Temporary")
            return "success"

        policy = RetryPolicy(max_retries=3)
        result, success, safety = policy.execute_with_retry(flaky_operation)
        assert success is True
        assert safety == RetrySafety.SAFE
        assert call_count == 2

    def test_unsafe_error_stops_retry(self):
        call_count = 0

        def bad_operation():
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid parameter")

        policy = RetryPolicy(max_retries=3)
        result, success, safety = policy.execute_with_retry(bad_operation)
        assert success is False
        assert safety == RetrySafety.UNSAFE
        assert call_count == 1

    def test_unknown_error_prevents_retry_by_default(self):
        call_count = 0

        def unknown_operation():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Unknown status")

        policy = RetryPolicy(max_retries=3, allow_unknown_retry=False)
        result, success, safety = policy.execute_with_retry(unknown_operation)
        assert success is False
        assert safety == RetrySafety.UNKNOWN
        assert call_count == 1

    def test_unknown_error_allows_retry_when_enabled(self):
        call_count = 0

        def unknown_operation():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Unknown status")

        policy = RetryPolicy(max_retries=3, allow_unknown_retry=True)
        result, success, safety = policy.execute_with_retry(unknown_operation)
        assert call_count == 3
        assert success is False


class TestConvenienceFunction:
    def test_safe_retry_operation_returns_result(self):
        def success_op():
            return "result"

        result = safe_retry_operation(success_op, max_retries=1)
        assert result.success is True
        assert result.result == "result"
        assert result.safety == RetrySafety.SAFE

    def test_safe_retry_operation_raises_on_unknown(self):
        def unknown_op():
            raise RuntimeError("Unknown")

        result = safe_retry_operation(unknown_op, max_retries=1)
        assert result.success is False
        assert result.safety == RetrySafety.UNKNOWN

    def test_safe_retry_operation_raises_on_unsafe(self):
        def unsafe_op():
            raise ValueError("Rejected")

        result = safe_retry_operation(unsafe_op, max_retries=1)
        assert result.success is False
        assert result.safety == RetrySafety.UNSAFE