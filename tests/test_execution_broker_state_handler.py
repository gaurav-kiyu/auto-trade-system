"""
Tests for core/execution/broker_state_handler.py - Broker State Handler.

Covers:
- BrokerStateCategory and ActionRecommendation enums
- StateResolution dataclass
- BrokerStateHandler (resolve_status, should_retry, handle_timeout, handle_exception, pending count, clear)
- Factory function create_state_handler
"""

from __future__ import annotations

import pytest

from core.execution.broker_state_handler import (
    ActionRecommendation,
    BrokerStateCategory,
    BrokerStateHandler,
    StateResolution,
    create_state_handler,
)
from core.datetime_ist import now_ist


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def handler():
    """BrokerStateHandler with default settings."""
    return BrokerStateHandler(max_retries=3, timeout_seconds=30)


# ── Enum Tests ────────────────────────────────────────────────────────────────


class TestBrokerStateCategory:
    """BrokerStateCategory enum - 6 categories."""

    def test_values(self):
        assert BrokerStateCategory.KNOWN_TERMINAL.value == "KNOWN_TERMINAL"
        assert BrokerStateCategory.KNOWN_PENDING.value == "KNOWN_PENDING"
        assert BrokerStateCategory.TIMEOUT.value == "TIMEOUT"
        assert BrokerStateCategory.NETWORK_ERROR.value == "NETWORK_ERROR"
        assert BrokerStateCategory.UNKNOWN_STATUS.value == "UNKNOWN_STATUS"
        assert BrokerStateCategory.NO_RESPONSE.value == "NO_RESPONSE"


class TestActionRecommendation:
    """ActionRecommendation enum - 5 recommendations."""

    def test_values(self):
        assert ActionRecommendation.PROCEED.value == "PROCEED"
        assert ActionRecommendation.RETRY.value == "RETRY"
        assert ActionRecommendation.BLOCK_RETRY.value == "BLOCK_RETRY"
        assert ActionRecommendation.MANUAL_REVIEW.value == "MANUAL_REVIEW"
        assert ActionRecommendation.UNKNOWN.value == "UNKNOWN"


# ── StateResolution Tests ─────────────────────────────────────────────────────


class TestStateResolution:
    """StateResolution dataclass."""

    def test_timestamp_defaults_to_now(self):
        sr = StateResolution(
            category=BrokerStateCategory.KNOWN_TERMINAL,
            action=ActionRecommendation.PROCEED,
            message="ok",
            can_retry=False,
            is_terminal=True,
        )
        assert sr.timestamp is not None


# ── BrokerStateHandler Tests ───────────────────────────────────────────────────


class TestResolveStatus:
    """Status resolution for various broker responses."""

    # ── KNOWN_TERMINAL states ─────────────────────────────────────────────

    def test_resolve_complete(self, handler):
        sr = handler.resolve_status("COMPLETE")
        assert sr.category == BrokerStateCategory.KNOWN_TERMINAL
        assert sr.action == ActionRecommendation.PROCEED
        assert sr.is_terminal is True
        assert sr.can_retry is False

    def test_resolve_filled(self, handler):
        sr = handler.resolve_status("FILLED")
        assert sr.category == BrokerStateCategory.KNOWN_TERMINAL
        assert sr.action == ActionRecommendation.PROCEED

    def test_resolve_rejected(self, handler):
        sr = handler.resolve_status("REJECTED")
        assert sr.category == BrokerStateCategory.KNOWN_TERMINAL
        assert sr.action == ActionRecommendation.BLOCK_RETRY
        assert sr.can_retry is False

    def test_resolve_cancelled(self, handler):
        sr = handler.resolve_status("CANCELLED")
        assert sr.category == BrokerStateCategory.KNOWN_TERMINAL
        assert sr.action == ActionRecommendation.BLOCK_RETRY

    def test_resolve_expired(self, handler):
        sr = handler.resolve_status("EXPIRED")
        assert sr.category == BrokerStateCategory.KNOWN_TERMINAL

    # ── KNOWN_PENDING states ───────────────────────────────────────────────

    def test_resolve_open_within_timeout(self, handler):
        sr = handler.resolve_status("OPEN", last_update=now_ist())
        assert sr.category == BrokerStateCategory.KNOWN_PENDING
        assert sr.action == ActionRecommendation.PROCEED

    def test_resolve_pending_within_timeout(self, handler):
        sr = handler.resolve_status("PENDING", last_update=now_ist())
        assert sr.category == BrokerStateCategory.KNOWN_PENDING

    def test_resolve_submitted_within_timeout(self, handler):
        sr = handler.resolve_status("SUBMITTED", last_update=now_ist())
        assert sr.category == BrokerStateCategory.KNOWN_PENDING

    def test_resolve_trigger_pending_within_timeout(self, handler):
        sr = handler.resolve_status("TRIGGER PENDING", last_update=now_ist())
        assert sr.category == BrokerStateCategory.KNOWN_PENDING

    def test_resolve_open_exceeded_timeout(self, handler):
        old_time = now_ist().replace(hour=0, minute=0, second=0)
        sr = handler.resolve_status("OPEN", last_update=old_time)
        assert sr.category == BrokerStateCategory.TIMEOUT
        assert sr.action == ActionRecommendation.RETRY

    def test_resolve_partially_filled(self, handler):
        sr = handler.resolve_status("PARTIALLY FILLED")
        assert sr.category == BrokerStateCategory.KNOWN_PENDING
        assert sr.action == ActionRecommendation.PROCEED

    def test_resolve_partial(self, handler):
        sr = handler.resolve_status("PARTIAL")
        assert sr.category == BrokerStateCategory.KNOWN_PENDING

    # ── NETWORK_ERROR states ───────────────────────────────────────────────

    def test_resolve_network_error(self, handler):
        sr = handler.resolve_status("NETWORK_ERROR", last_error="connection reset")
        assert sr.category == BrokerStateCategory.NETWORK_ERROR
        assert sr.action == ActionRecommendation.RETRY
        assert sr.can_retry is True

    def test_resolve_connection_error(self, handler):
        sr = handler.resolve_status("CONNECTION_ERROR")
        assert sr.category == BrokerStateCategory.NETWORK_ERROR

    def test_resolve_timeout_status(self, handler):
        sr = handler.resolve_status("TIMEOUT_ERROR")
        assert sr.category == BrokerStateCategory.NETWORK_ERROR

    # ── NO_RESPONSE state ──────────────────────────────────────────────────

    def test_resolve_none_status(self, handler):
        sr = handler.resolve_status(None)
        assert sr.category == BrokerStateCategory.NO_RESPONSE
        assert sr.action == ActionRecommendation.RETRY

    def test_resolve_empty_status(self, handler):
        sr = handler.resolve_status("")
        assert sr.category == BrokerStateCategory.NO_RESPONSE

    # ── UNKNOWN_STATUS state ───────────────────────────────────────────────

    def test_resolve_unknown_status_first_time(self, handler):
        sr = handler.resolve_status("SOME_UNKNOWN_STATUS")
        assert sr.category == BrokerStateCategory.UNKNOWN_STATUS
        assert sr.action == ActionRecommendation.RETRY
        assert sr.can_retry is True

    def test_resolve_unknown_status_threshold_reached(self, handler):
        """After UNKNOWN_STATUS_THRESHOLD times, action becomes MANUAL_REVIEW."""
        for _ in range(handler.UNKNOWN_STATUS_THRESHOLD):
            handler.resolve_status("WEIRD_STATUS")

        sr = handler.resolve_status("WEIRD_STATUS")
        assert sr.category == BrokerStateCategory.UNKNOWN_STATUS
        assert sr.action == ActionRecommendation.MANUAL_REVIEW
        assert sr.can_retry is False


class TestShouldRetry:
    """Retry decision logic."""

    def test_should_retry_no_resolution(self, handler):
        # OPEN without last_update returns KNOWN_PENDING with can_retry=False
        assert handler.should_retry("OPEN", 0) is False

    def test_should_retry_with_resolution_terminal(self, handler):
        sr = handler.resolve_status("FILLED")
        assert handler.should_retry("FILLED", 0, sr) is False

    def test_should_retry_max_retries_exceeded(self, handler):
        assert handler.should_retry("OPEN", 3) is False

    def test_should_retry_below_max(self, handler):
        # With stale last_update, OPEN becomes TIMEOUT which allows retry
        from datetime import timedelta
        stale_time = now_ist() - timedelta(seconds=60)
        sr = handler.resolve_status("OPEN", last_update=stale_time)
        assert handler.should_retry("OPEN", 2, sr) is True


class TestHandleTimeout:
    """Timeout handling."""

    def test_handle_timeout_under_max_retries(self, handler):
        sr = handler.handle_timeout("order-1", 0)
        assert sr.category == BrokerStateCategory.TIMEOUT
        assert sr.action == ActionRecommendation.RETRY
        assert sr.can_retry is True

    def test_handle_timeout_exceeds_max(self, handler):
        sr = handler.handle_timeout("order-1", 3)
        assert sr.action == ActionRecommendation.BLOCK_RETRY
        assert sr.can_retry is False


class TestHandleException:
    """Exception handling for various error types."""

    def test_handle_timeout_exception(self, handler):
        sr = handler.handle_exception("order-1", TimeoutError("timed out"), 0)
        assert sr.category == BrokerStateCategory.TIMEOUT
        assert sr.action == ActionRecommendation.RETRY

    def test_handle_network_exception(self, handler):
        sr = handler.handle_exception("order-1", ConnectionError("connection lost"), 0)
        assert sr.category == BrokerStateCategory.NETWORK_ERROR
        assert sr.action == ActionRecommendation.RETRY

    def test_handle_network_exception_max_retries(self, handler):
        sr = handler.handle_exception("order-1", ConnectionError("connection lost"), 3)
        assert sr.action == ActionRecommendation.BLOCK_RETRY

    def test_handle_auth_exception(self, handler):
        sr = handler.handle_exception("order-1", PermissionError("auth failed"), 0)
        assert sr.action == ActionRecommendation.BLOCK_RETRY
        assert sr.can_retry is False

    def test_handle_margin_exception(self, handler):
        sr = handler.handle_exception("order-1", ValueError("insufficient margin"), 0)
        assert sr.action == ActionRecommendation.BLOCK_RETRY
        assert sr.is_terminal is True

    def test_handle_unknown_exception_under_max(self, handler):
        sr = handler.handle_exception("order-1", RuntimeError("weird error"), 0)
        assert sr.action == ActionRecommendation.RETRY

    def test_handle_unknown_exception_max_retries(self, handler):
        sr = handler.handle_exception("order-1", RuntimeError("weird error"), 3)
        assert sr.action == ActionRecommendation.BLOCK_RETRY


class TestPendingOrdersCount:
    """Pending orders with unknown status count."""

    def test_pending_count_initial(self, handler):
        assert handler.get_pending_orders_count() == 0

    def test_pending_count_after_unknown(self, handler):
        handler.resolve_status("WEIRD_STATUS_1")
        handler.resolve_status("WEIRD_STATUS_2")
        assert handler.get_pending_orders_count() == 2


class TestClearUnknownStatus:
    """Clear unknown status count."""

    def test_clear_unknown_status(self, handler):
        handler.resolve_status("WEIRD_STATUS")
        assert handler.get_pending_orders_count() == 1
        handler.clear_unknown_status("WEIRD_STATUS")
        assert handler.get_pending_orders_count() == 0

    def test_clear_nonexistent_status(self, handler):
        handler.clear_unknown_status("NONEXISTENT")  # Should not raise
        assert True


class TestCreateStateHandler:
    """Factory function create_state_handler."""

    def test_create_with_defaults(self):
        h = create_state_handler()
        assert isinstance(h, BrokerStateHandler)
        assert h._max_retries == 3
        assert h._timeout_seconds == 30

    def test_create_with_custom_values(self):
        h = create_state_handler(max_retries=5, timeout_seconds=60)
        assert h._max_retries == 5
        assert h._timeout_seconds == 60
