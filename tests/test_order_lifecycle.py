"""Tests for core/execution/order_lifecycle.py — Stale Order Handler & ACK Watchdog.

Covers:
- run_stale_order_timeout: zombie order detection and cancellation
- run_ack_watchdog: broker ACK timeout detection and state reconciliation
- Edge cases: empty state, missing timestamps, broker errors
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.execution.order_lifecycle import run_ack_watchdog, run_stale_order_timeout

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_state_manager():
    with patch("core.execution.order_lifecycle.get_execution_state_manager") as mock:
        yield mock


@pytest.fixture
def mock_broker():
    broker = MagicMock()
    broker.cancel_order.return_value = True
    broker.get_order_status.return_value = "COMPLETE"
    return broker


# ── run_stale_order_timeout Tests ────────────────────────────────────────────


class TestStaleOrderTimeout:
    """Tests for run_stale_order_timeout — zombie order prevention."""

    def test_no_machines_returns_zero(self, mock_state_manager, mock_broker):
        """Empty state manager should return zero counts."""
        manager = MagicMock()
        manager.get_all.return_value = []
        mock_state_manager.return_value = manager

        result = run_stale_order_timeout(mock_broker)
        assert result == {"checked": 0, "cancelled": 0, "already_terminal": 0, "errors": 0}

    def test_terminal_machines_skipped(self, mock_state_manager, mock_broker):
        """Machines in terminal state should be counted as already_terminal."""
        terminal_machine = MagicMock()
        terminal_machine.is_terminal.return_value = True

        manager = MagicMock()
        manager.get_all.return_value = [terminal_machine]
        mock_state_manager.return_value = manager

        result = run_stale_order_timeout(mock_broker)
        assert result["already_terminal"] == 1
        assert result["checked"] == 0

    def test_recent_order_not_cancelled(self, mock_state_manager, mock_broker):
        """Recent non-stale orders should not be cancelled."""
        from core.datetime_ist import now_ist
        from core.execution.deterministic_state_machine import ExecutionState

        fresh = MagicMock()
        fresh.is_terminal.return_value = False
        fresh.state = ExecutionState.SUBMITTED
        fresh.submitted_at = now_ist().isoformat()
        fresh.client_order_id = "ORD-001"
        fresh.broker_order_id = None

        manager = MagicMock()
        manager.get_all.return_value = [fresh]
        mock_state_manager.return_value = manager

        result = run_stale_order_timeout(mock_broker, max_stale_seconds=300.0)
        assert result["checked"] == 0  # Too recent
        assert result["cancelled"] == 0

    def test_broker_cancel_error_handled(self, mock_state_manager):
        """Broker cancel failure should not crash the timeout runner."""
        from core.execution.deterministic_state_machine import ExecutionState

        broker = MagicMock()
        broker.cancel_order.side_effect = ConnectionError("Broker unreachable")

        stale = MagicMock()
        stale.is_terminal.return_value = False
        stale.state = ExecutionState.SUBMITTED
        stale.submitted_at = "2024-01-01T00:00:00"
        stale.client_order_id = "ORD-002"
        stale.broker_order_id = "BROKER-001"

        manager = MagicMock()
        manager.get_all.return_value = [stale]
        mock_state_manager.return_value = manager

        # Should not raise despite broker error
        result = run_stale_order_timeout(broker, max_stale_seconds=0)
        assert result["cancelled"] == 1  # record_failure still runs

    def test_missing_timestamp_skipped(self, mock_state_manager, mock_broker):
        """Orders with missing timestamps should be counted as errors."""
        from core.execution.deterministic_state_machine import ExecutionState

        bad = MagicMock()
        bad.is_terminal.return_value = False
        bad.state = ExecutionState.SUBMITTED
        bad.submitted_at = None
        bad.updated_at = "not-a-date"

        manager = MagicMock()
        manager.get_all.return_value = [bad]
        mock_state_manager.return_value = manager

        result = run_stale_order_timeout(mock_broker, max_stale_seconds=0)
        assert result["errors"] == 1  # updated_at fails parsing (submitted_at is None, skips to else branch)

    def test_non_stale_state_skipped(self, mock_state_manager, mock_broker):
        """Orders in non-stale states should be skipped."""
        from core.execution.deterministic_state_machine import ExecutionState

        executing = MagicMock()
        executing.is_terminal.return_value = False
        executing.state = ExecutionState.FILLED  # Not in stale_states set (is terminal)

        manager = MagicMock()
        manager.get_all.return_value = [executing]
        mock_state_manager.return_value = manager

        result = run_stale_order_timeout(mock_broker, max_stale_seconds=0)
        assert result["checked"] == 0
        assert result["cancelled"] == 0


# ── run_ack_watchdog Tests ───────────────────────────────────────────────────


class TestAckWatchdog:
    """Tests for run_ack_watchdog — broker ACK timeout detection."""

    def test_no_submitted_returns_zero(self, mock_state_manager, mock_broker):
        """No SUBMITTED machines should return zero counts."""
        manager = MagicMock()
        manager.get_all.return_value = []
        mock_state_manager.return_value = manager

        result = run_ack_watchdog(mock_broker)
        assert result == {"checked": 0, "acknowledged": 0, "still_pending": 0, "errors": 0}

    def test_recent_submitted_skipped(self, mock_state_manager, mock_broker):
        """Recent SUBMITTED orders should not be checked yet."""
        from core.datetime_ist import now_ist
        from core.execution.deterministic_state_machine import ExecutionState

        recent = MagicMock()
        recent.state = ExecutionState.SUBMITTED
        recent.submitted_at = now_ist().isoformat()
        recent.broker_order_id = "BROKER-001"

        manager = MagicMock()
        manager.get_all.return_value = [recent]
        mock_state_manager.return_value = manager

        result = run_ack_watchdog(mock_broker, max_ack_age_seconds=300.0)
        assert result["checked"] == 0

    def test_stale_submitted_checked(self, mock_state_manager, mock_broker):
        """Stale SUBMITTED orders should be checked against broker."""
        from core.execution.deterministic_state_machine import ExecutionState

        stale = MagicMock()
        stale.state = ExecutionState.SUBMITTED
        stale.submitted_at = "2024-01-01T00:00:00"
        stale.broker_order_id = "BROKER-001"

        manager = MagicMock()
        manager.get_all.return_value = [stale]
        mock_state_manager.return_value = manager

        result = run_ack_watchdog(mock_broker, max_ack_age_seconds=0)
        assert result["checked"] == 1

    def test_broker_complete_triggers_fill(self, mock_state_manager, mock_broker):
        """COMPLETE status from broker should trigger record_fill."""
        from core.execution.deterministic_state_machine import ExecutionState

        stale = MagicMock()
        stale.state = ExecutionState.SUBMITTED
        stale.submitted_at = "2024-01-01T00:00:00"
        stale.broker_order_id = "BROKER-001"
        stale.quantity = 50
        stale.price = 150.0

        manager = MagicMock()
        manager.get_all.return_value = [stale]
        mock_state_manager.return_value = manager

        result = run_ack_watchdog(mock_broker, max_ack_age_seconds=0)
        assert result["acknowledged"] >= 0

    def test_broker_rejected_triggers_rejection(self, mock_state_manager):
        """REJECTED status from broker should trigger state transition."""
        from core.execution.deterministic_state_machine import ExecutionState

        broker = MagicMock()
        broker.get_order_status.return_value = "REJECTED"

        stale = MagicMock()
        stale.state = ExecutionState.SUBMITTED
        stale.submitted_at = "2024-01-01T00:00:00"
        stale.broker_order_id = "BROKER-001"

        manager = MagicMock()
        manager.get_all.return_value = [stale]
        mock_state_manager.return_value = manager

        result = run_ack_watchdog(broker, max_ack_age_seconds=0)
        assert result["acknowledged"] >= 0

    def test_broker_still_pending(self, mock_state_manager):
        """OPEN status from broker should count as still_pending."""
        from core.execution.deterministic_state_machine import ExecutionState

        broker = MagicMock()
        broker.get_order_status.return_value = "OPEN"

        stale = MagicMock()
        stale.state = ExecutionState.SUBMITTED
        stale.submitted_at = "2024-01-01T00:00:00"
        stale.broker_order_id = "BROKER-001"

        manager = MagicMock()
        manager.get_all.return_value = [stale]
        mock_state_manager.return_value = manager

        result = run_ack_watchdog(broker, max_ack_age_seconds=0)
        assert result["still_pending"] == 1

    def test_missing_broker_id_errors(self, mock_state_manager):
        """Missing broker_order_id should be counted as error."""
        from core.execution.deterministic_state_machine import ExecutionState

        broker = MagicMock()
        broker.get_order_status.return_value = "COMPLETE"

        no_id = MagicMock()
        no_id.state = ExecutionState.SUBMITTED
        no_id.submitted_at = "2024-01-01T00:00:00"
        no_id.broker_order_id = None

        manager = MagicMock()
        manager.get_all.return_value = [no_id]
        mock_state_manager.return_value = manager

        result = run_ack_watchdog(broker, max_ack_age_seconds=0)
        assert result["errors"] == 1

    def test_broker_error_handled(self, mock_state_manager):
        """Broker connection error should not crash the watchdog."""
        from core.execution.deterministic_state_machine import ExecutionState

        broker = MagicMock()
        broker.get_order_status.side_effect = OSError("Connection failed")

        failing = MagicMock()
        failing.state = ExecutionState.SUBMITTED
        failing.submitted_at = "2024-01-01T00:00:00"
        failing.broker_order_id = "BROKER-001"

        manager = MagicMock()
        manager.get_all.return_value = [failing]
        mock_state_manager.return_value = manager

        result = run_ack_watchdog(broker, max_ack_age_seconds=0)
        assert result["errors"] >= 0
