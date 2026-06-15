"""Tests for core/execution/retry_policy/manager.py — Retry Policy Manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import threading

import pytest

from core.execution.retry_policy.manager import (
    RetryPolicy,
    RetryResult,
    RetrySafety,
    safe_retry_operation,
)


class TestRetrySafety:
    """RetrySafety enum coverage."""

    def test_values(self):
        assert RetrySafety.SAFE.value == "safe"
        assert RetrySafety.UNKNOWN.value == "unknown"
        assert RetrySafety.UNSAFE.value == "unsafe"


class TestRetryPolicy:
    """RetryPolicy coverage."""

    @pytest.fixture
    def policy(self):
        return RetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.1, exponential_base=2.0)

    def test_classify_timeout_error(self, policy):
        safety = policy.classify_error(TimeoutError("Connection timed out"))
        assert safety == RetrySafety.SAFE

    def test_classify_connection_error(self, policy):
        safety = policy.classify_error(ConnectionError("Connection refused"))
        assert safety == RetrySafety.SAFE

    def test_classify_generic_error_with_timeout_msg(self, policy):
        safety = policy.classify_error(ValueError("timeout occurred"))
        assert safety == RetrySafety.SAFE

    def test_classify_network_error_in_msg(self, policy):
        safety = policy.classify_error(ValueError("network error"))
        assert safety == RetrySafety.SAFE

    def test_classify_rejected_error(self, policy):
        safety = policy.classify_error(ValueError("Order rejected"))
        assert safety == RetrySafety.UNSAFE

    def test_classify_auth_error(self, policy):
        safety = policy.classify_error(PermissionError("Auth failed"))
        assert safety == RetrySafety.UNSAFE

    def test_classify_margin_error(self, policy):
        safety = policy.classify_error(ValueError("Insufficient margin"))
        assert safety == RetrySafety.UNSAFE

    def test_classify_unknown_error_falls_back_to_unknown(self, policy):
        safety = policy.classify_error(RuntimeError("Unexpected error"))
        assert safety == RetrySafety.UNKNOWN

    def test_execute_with_retry_success_on_first_try(self, policy):
        operation = MagicMock(return_value="success")
        result, succeeded, safety = policy.execute_with_retry(operation)
        assert result == "success"
        assert succeeded is True
        assert safety == RetrySafety.SAFE
        operation.assert_called_once()

    def test_execute_with_retry_retry_on_safe_error(self, policy):
        operation = MagicMock(
            side_effect=[ConnectionError("timeout"), ConnectionError("timeout"), "success"]
        )
        result, succeeded, safety = policy.execute_with_retry(operation)
        assert result == "success"
        assert succeeded is True
        assert operation.call_count == 3

    def test_execute_with_retry_stops_on_unsafe(self, policy):
        operation = MagicMock(side_effect=ValueError("Order rejected"))
        result, succeeded, safety = policy.execute_with_retry(operation)
        assert result is None
        assert succeeded is False
        assert safety == RetrySafety.UNSAFE
        operation.assert_called_once()  # No retry on UNSAFE

    def test_execute_with_retry_stops_on_unknown_without_flag(self, policy):
        operation = MagicMock(side_effect=RuntimeError("Unexpected"))
        result, succeeded, safety = policy.execute_with_retry(operation)
        assert result is None
        assert succeeded is False
        assert safety == RetrySafety.UNKNOWN
        operation.assert_called_once()  # No retry on UNKNOWN without flag

    def test_execute_with_retry_retry_on_unknown_with_flag(self, policy):
        policy.allow_unknown_retry = True
        operation = MagicMock(
            side_effect=[RuntimeError("Unexpected"), RuntimeError("Unexpected"), "success"]
        )
        result, succeeded, safety = policy.execute_with_retry(operation)
        assert result == "success"
        assert succeeded is True
        assert operation.call_count == 3

    def test_execute_with_retry_exhausts_max_retries(self, policy):
        policy.max_retries = 2
        operation = MagicMock(side_effect=ConnectionError("timeout"))
        result, succeeded, safety = policy.execute_with_retry(operation)
        assert result is None
        assert succeeded is False
        assert operation.call_count == 2

    def test_execute_safe_retry_success(self, policy):
        operation = MagicMock(return_value="ok")
        result = policy.execute_safe_retry(operation)
        assert result == "ok"

    def test_execute_safe_retry_raises_on_unsafe(self, policy):
        operation = MagicMock(side_effect=ValueError("rejected"))
        with pytest.raises(RuntimeError, match="permanent error"):
            policy.execute_safe_retry(operation)

    def test_execute_safe_retry_raises_on_unknown(self, policy):
        operation = MagicMock(side_effect=RuntimeError("weird"))
        with pytest.raises(RuntimeError, match="manual intervention"):
            policy.execute_safe_retry(operation)

    def test_execute_safe_retry_raises_on_all_retries_exhausted(self, policy):
        policy.max_retries = 1
        operation = MagicMock(side_effect=ConnectionError("timeout"))
        with pytest.raises(RuntimeError, match="retries"):
            policy.execute_safe_retry(operation)


class TestRetryPolicyShutdownAware:
    """Shutdown-aware retry policy coverage."""

    def test_shutdown_interrupts_retry(self):
        shutdown_event = threading.Event()
        policy = RetryPolicy(max_retries=3, base_delay=1.0, max_delay=5.0, shutdown_event=shutdown_event)
        operation = MagicMock(side_effect=ConnectionError("timeout"))

        # Set shutdown event immediately
        shutdown_event.set()

        result, succeeded, safety = policy.execute_with_retry(operation)
        assert result is None
        assert succeeded is False


class TestRetryResult:
    """RetryResult dataclass coverage."""

    def test_defaults(self):
        r = RetryResult(success=True, result="ok", safety=RetrySafety.SAFE, attempts=1)
        assert r.error is None
        assert r.success is True

    def test_with_error(self):
        r = RetryResult(success=False, result=None, safety=RetrySafety.UNSAFE, attempts=1, error="Failed")
        assert r.error == "Failed"


class TestSafeRetryOperation:
    """Convenience safe_retry_operation function coverage."""

    def test_success(self):
        result = safe_retry_operation(lambda: "done", max_retries=1)
        assert result.success is True
        assert result.result == "done"

    def test_failure(self):
        def failing():
            raise ConnectionError("timeout")

        result = safe_retry_operation(failing, max_retries=1)
        assert result.success is False
        assert result.result is None
        assert "timeout" in (result.error or "")

    def test_rejected_no_retry(self):
        def rejected():
            raise ValueError("rejected")

        result = safe_retry_operation(rejected, max_retries=3)
        assert result.success is False
        assert result.safety == RetrySafety.UNSAFE

    def test_shutdown_event(self):
        shutdown = threading.Event()
        shutdown.set()

        def failing():
            raise ConnectionError("timeout")

        result = safe_retry_operation(failing, max_retries=3, shutdown_event=shutdown)
        assert result.success is False
