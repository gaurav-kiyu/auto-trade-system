"""
Tests for core/execution/broker_state_handler.py - Broker State Handler.

Covers:
  - BrokerStateCategory enum values
  - ActionRecommendation enum values
  - StateResolution dataclass (defaults, custom)
  - BrokerStateHandler initialization (defaults, custom)
  - resolve_status (None/empty → RETRY, COMPLETE/FILLED → PROCEED,
    REJECTED/CANCELLED/EXPIRED → BLOCK_RETRY, OPEN/PENDING → PROCEED,
    timeout on pending → RETRY, PARTIALLY FILLED → PROCEED,
    network errors → RETRY, unknown status escalation → MANUAL_REVIEW)
  - should_retry (can_retry, max retries exceeded)
  - handle_timeout (within retries, max exceeded → BLOCK_RETRY)
  - handle_exception (timeout, network, auth, margin, unknown)
  - get_pending_orders_count
  - clear_unknown_status
  - create_state_handler factory function
"""

from __future__ import annotations

from datetime import datetime, timedelta


from core.execution.broker_state_handler import (
    ActionRecommendation,
    BrokerStateCategory,
    BrokerStateHandler,
    StateResolution,
    create_state_handler,
)
from core.datetime_ist import now_ist


# ═══════════════════════════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════════════════════════


class TestBrokerStateCategory:
    def test_values(self):
        assert BrokerStateCategory.KNOWN_TERMINAL == "KNOWN_TERMINAL"
        assert BrokerStateCategory.KNOWN_PENDING == "KNOWN_PENDING"
        assert BrokerStateCategory.TIMEOUT == "TIMEOUT"
        assert BrokerStateCategory.NETWORK_ERROR == "NETWORK_ERROR"
        assert BrokerStateCategory.UNKNOWN_STATUS == "UNKNOWN_STATUS"
        assert BrokerStateCategory.NO_RESPONSE == "NO_RESPONSE"


class TestActionRecommendation:
    def test_values(self):
        assert ActionRecommendation.PROCEED == "PROCEED"
        assert ActionRecommendation.RETRY == "RETRY"
        assert ActionRecommendation.BLOCK_RETRY == "BLOCK_RETRY"
        assert ActionRecommendation.MANUAL_REVIEW == "MANUAL_REVIEW"
        assert ActionRecommendation.UNKNOWN == "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════════
#  StateResolution
# ═══════════════════════════════════════════════════════════════════════


class TestStateResolution:
    def test_fields(self):
        resolution = StateResolution(
            category=BrokerStateCategory.KNOWN_TERMINAL,
            action=ActionRecommendation.PROCEED,
            message="Order filled",
            can_retry=False,
            is_terminal=True,
        )
        assert resolution.category == BrokerStateCategory.KNOWN_TERMINAL
        assert resolution.action == ActionRecommendation.PROCEED
        assert resolution.message == "Order filled"
        assert resolution.can_retry is False
        assert resolution.is_terminal is True


# ═══════════════════════════════════════════════════════════════════════
#  BrokerStateHandler
# ═══════════════════════════════════════════════════════════════════════


class TestBrokerStateHandlerInit:
    def test_defaults(self):
        handler = BrokerStateHandler()
        assert handler._max_retries == BrokerStateHandler.MAX_RETRY_COUNT
        assert handler._timeout_seconds == BrokerStateHandler.TIMEOUT_SECONDS
        assert handler._unknown_status_counts == {}

    def test_custom(self):
        handler = BrokerStateHandler(max_retries=5, timeout_seconds=60)
        assert handler._max_retries == 5
        assert handler._timeout_seconds == 60


class TestResolveStatus:
    # ── None / Empty ────────────────────────────────────────────────

    def test_none_status(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status(None)
        assert resolution.category == BrokerStateCategory.NO_RESPONSE
        assert resolution.action == ActionRecommendation.RETRY
        assert resolution.can_retry is True

    def test_empty_status(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("")
        assert resolution.category == BrokerStateCategory.NO_RESPONSE
        assert resolution.action == ActionRecommendation.RETRY

    # ── COMPLETE / FILLED ───────────────────────────────────────────

    def test_complete(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("COMPLETE")
        assert resolution.category == BrokerStateCategory.KNOWN_TERMINAL
        assert resolution.action == ActionRecommendation.PROCEED
        assert resolution.is_terminal is True

    def test_filled(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("FILLED")
        assert resolution.category == BrokerStateCategory.KNOWN_TERMINAL
        assert resolution.action == ActionRecommendation.PROCEED

    def test_filled_lowercase(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("filled")
        assert resolution.category == BrokerStateCategory.KNOWN_TERMINAL

    def test_filled_with_whitespace(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("  FILLED  ")
        assert resolution.category == BrokerStateCategory.KNOWN_TERMINAL

    # ── REJECTED / CANCELLED / EXPIRED ──────────────────────────────

    def test_rejected(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("REJECTED")
        assert resolution.category == BrokerStateCategory.KNOWN_TERMINAL
        assert resolution.action == ActionRecommendation.BLOCK_RETRY
        assert resolution.can_retry is False

    def test_cancelled(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("CANCELLED")
        assert resolution.category == BrokerStateCategory.KNOWN_TERMINAL
        assert resolution.action == ActionRecommendation.BLOCK_RETRY

    def test_expired(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("EXPIRED")
        assert resolution.category == BrokerStateCategory.KNOWN_TERMINAL
        assert resolution.action == ActionRecommendation.BLOCK_RETRY

    # ── OPEN / PENDING / SUBMITTED ──────────────────────────────────

    def test_open_no_timeout(self):
        handler = BrokerStateHandler(timeout_seconds=30)
        recent = now_ist()
        resolution = handler.resolve_status("OPEN", last_update=recent)
        assert resolution.category == BrokerStateCategory.KNOWN_PENDING
        assert resolution.action == ActionRecommendation.PROCEED
        assert resolution.can_retry is False

    def test_open_with_timeout(self):
        handler = BrokerStateHandler(timeout_seconds=30)
        old = now_ist() - timedelta(seconds=60)
        resolution = handler.resolve_status("OPEN", last_update=old)
        assert resolution.category == BrokerStateCategory.TIMEOUT
        assert resolution.action == ActionRecommendation.RETRY
        assert resolution.can_retry is True

    def test_pending_no_timeout(self):
        handler = BrokerStateHandler()
        recent = now_ist()
        resolution = handler.resolve_status("PENDING", last_update=recent)
        assert resolution.category == BrokerStateCategory.KNOWN_PENDING

    def test_submitted_no_timeout(self):
        handler = BrokerStateHandler()
        recent = now_ist()
        resolution = handler.resolve_status("SUBMITTED", last_update=recent)
        assert resolution.category == BrokerStateCategory.KNOWN_PENDING

    def test_no_last_update_does_not_timeout(self):
        """Without last_update, pending status should not trigger timeout."""
        handler = BrokerStateHandler(timeout_seconds=1)
        resolution = handler.resolve_status("PENDING")
        assert resolution.category == BrokerStateCategory.KNOWN_PENDING
        assert resolution.action == ActionRecommendation.PROCEED

    # ── PARTIALLY FILLED ────────────────────────────────────────────

    def test_partially_filled(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("PARTIALLY FILLED")
        assert resolution.category == BrokerStateCategory.KNOWN_PENDING
        assert resolution.action == ActionRecommendation.PROCEED

    def test_partial_shorthand(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("PARTIAL")
        assert resolution.category == BrokerStateCategory.KNOWN_PENDING

    # ── Network errors ──────────────────────────────────────────────

    def test_network_error_in_status(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("NETWORK_ERROR")
        assert resolution.category == BrokerStateCategory.NETWORK_ERROR
        assert resolution.action == ActionRecommendation.RETRY
        assert resolution.can_retry is True

    def test_connection_error_in_status(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("CONNECTION_LOST")
        assert resolution.category == BrokerStateCategory.NETWORK_ERROR

    def test_timeout_in_status(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("TIMEOUT")
        assert resolution.category == BrokerStateCategory.NETWORK_ERROR

    # ── Unknown status escalation ───────────────────────────────────

    def test_unknown_status_first_time_retries(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("NEW_STATUS")
        assert resolution.category == BrokerStateCategory.UNKNOWN_STATUS
        assert resolution.action == ActionRecommendation.RETRY
        assert resolution.can_retry is True

    def test_unknown_status_escalates_to_manual(self):
        handler = BrokerStateHandler()
        handler.UNKNOWN_STATUS_THRESHOLD = 2
        # With threshold=2, it takes 3 calls to trigger MANUAL_REVIEW:
        # count goes 0→1 (call1), 1→2 (call2), 2>=2 on call3
        handler.resolve_status("MYSTERY")
        handler.resolve_status("MYSTERY")
        resolution = handler.resolve_status("MYSTERY")
        assert resolution.category == BrokerStateCategory.UNKNOWN_STATUS
        assert resolution.action == ActionRecommendation.MANUAL_REVIEW
        assert resolution.can_retry is False

    def test_unknown_status_counts_are_case_insensitive(self):
        handler = BrokerStateHandler()
        handler.UNKNOWN_STATUS_THRESHOLD = 2
        handler.resolve_status("MYSTERY")
        handler.resolve_status("mystery")
        resolution = handler.resolve_status("mystery")
        assert resolution.action == ActionRecommendation.MANUAL_REVIEW

    def test_unknown_status_with_error(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("SOME_ERROR", last_error="Connection reset")
        # Status "SOME_ERROR" doesn't contain NETWORK/CONNECTION/TIMEOUT keywords
        # so it falls to the unknown-status path (not NETWORK_ERROR path)
        assert resolution.category == BrokerStateCategory.UNKNOWN_STATUS


class TestShouldRetry:
    def test_can_retry_and_under_limit(self):
        handler = BrokerStateHandler(max_retries=3)
        resolution = handler.resolve_status(None)  # NO_RESPONSE with can_retry=True
        assert handler.should_retry(None, retry_count=0, resolution=resolution) is True

    def test_cannot_retry(self):
        handler = BrokerStateHandler()
        resolution = handler.resolve_status("FILLED")  # TERMINAL with can_retry=False
        assert handler.should_retry("FILLED", retry_count=0, resolution=resolution) is False

    def test_max_retries_exceeded(self):
        handler = BrokerStateHandler(max_retries=2)
        resolution = handler.resolve_status(None)
        assert handler.should_retry(None, retry_count=2, resolution=resolution) is False

    def test_auto_resolve_when_no_resolution(self):
        handler = BrokerStateHandler(max_retries=3)
        assert handler.should_retry(None, retry_count=0) is True

    def test_auto_resolve_terminal(self):
        handler = BrokerStateHandler()
        assert handler.should_retry("FILLED", retry_count=0) is False


class TestHandleTimeout:
    def test_within_retry_limit(self):
        handler = BrokerStateHandler(max_retries=3)
        resolution = handler.handle_timeout("ORD-001", retry_count=1)
        assert resolution.category == BrokerStateCategory.TIMEOUT
        assert resolution.action == ActionRecommendation.RETRY
        assert resolution.can_retry is True

    def test_exceeds_max_retries(self):
        handler = BrokerStateHandler(max_retries=3)
        resolution = handler.handle_timeout("ORD-001", retry_count=3)
        assert resolution.action == ActionRecommendation.BLOCK_RETRY
        assert resolution.can_retry is False


class TestHandleException:
    def test_timeout_exception(self):
        handler = BrokerStateHandler()
        exc = TimeoutError("timed out after 30s")
        resolution = handler.handle_exception("ORD-001", exc, retry_count=0)
        assert resolution.category == BrokerStateCategory.TIMEOUT
        assert resolution.action == ActionRecommendation.RETRY

    def test_network_exception(self):
        handler = BrokerStateHandler()
        exc = ConnectionError("network unreachable")
        resolution = handler.handle_exception("ORD-001", exc, retry_count=0)
        assert resolution.category == BrokerStateCategory.NETWORK_ERROR
        assert resolution.action == ActionRecommendation.RETRY

    def test_network_exception_max_retries(self):
        handler = BrokerStateHandler(max_retries=2)
        exc = ConnectionError("network unreachable")
        resolution = handler.handle_exception("ORD-001", exc, retry_count=2)
        assert resolution.action == ActionRecommendation.BLOCK_RETRY

    def test_auth_exception(self):
        handler = BrokerStateHandler()
        exc = PermissionError("auth token expired")
        resolution = handler.handle_exception("ORD-001", exc, retry_count=0)
        assert resolution.action == ActionRecommendation.BLOCK_RETRY
        assert resolution.is_terminal is True

    def test_margin_exception(self):
        handler = BrokerStateHandler()
        exc = ValueError("insufficient margin")
        resolution = handler.handle_exception("ORD-001", exc, retry_count=0)
        assert resolution.action == ActionRecommendation.BLOCK_RETRY
        assert resolution.is_terminal is True

    def test_unknown_exception_first_retry(self):
        handler = BrokerStateHandler(max_retries=3)
        exc = RuntimeError("unexpected error")
        resolution = handler.handle_exception("ORD-001", exc, retry_count=0)
        assert resolution.action == ActionRecommendation.RETRY

    def test_unknown_exception_max_retries(self):
        handler = BrokerStateHandler(max_retries=2)
        exc = RuntimeError("unexpected error")
        resolution = handler.handle_exception("ORD-001", exc, retry_count=2)
        assert resolution.action == ActionRecommendation.BLOCK_RETRY

    def test_unauthorized_keyword(self):
        handler = BrokerStateHandler()
        exc = ValueError("unauthorized access")
        resolution = handler.handle_exception("ORD-001", exc, retry_count=0)
        assert resolution.action == ActionRecommendation.BLOCK_RETRY
        assert resolution.is_terminal is True


class TestPendingOrdersAndClear:
    def test_get_pending_orders_count(self):
        handler = BrokerStateHandler()
        handler.UNKNOWN_STATUS_THRESHOLD = 3
        # Unknown statuses below threshold count as pending
        handler.resolve_status("STATUS_A")
        handler.resolve_status("STATUS_B")
        assert handler.get_pending_orders_count() == 2

    def test_get_pending_returns_zero_when_none(self):
        handler = BrokerStateHandler()
        assert handler.get_pending_orders_count() == 0

    def test_get_pending_excludes_threshold_reached(self):
        handler = BrokerStateHandler()
        handler.UNKNOWN_STATUS_THRESHOLD = 2
        handler.resolve_status("STATUS_X")
        handler.resolve_status("STATUS_X")  # hits threshold, no longer pending
        assert handler.get_pending_orders_count() == 0

    def test_clear_unknown_status(self):
        handler = BrokerStateHandler()
        handler.resolve_status("BOGUS")
        assert "BOGUS" in handler._unknown_status_counts
        handler.clear_unknown_status("BOGUS")
        assert "BOGUS" not in handler._unknown_status_counts

    def test_clear_nonexistent_status_does_nothing(self):
        handler = BrokerStateHandler()
        handler.clear_unknown_status("NONEXIST")
        # Should not raise


class TestCreateStateHandler:
    def test_default(self):
        handler = create_state_handler()
        assert isinstance(handler, BrokerStateHandler)
        assert handler._max_retries == 3
        assert handler._timeout_seconds == 30

    def test_custom(self):
        handler = create_state_handler(max_retries=5, timeout_seconds=45)
        assert handler._max_retries == 5
        assert handler._timeout_seconds == 45
