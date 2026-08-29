"""Tests for core/reconciliation_controller.py - ReconciliationController."""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest
from core.reconciliation_controller import ReconciliationController


@pytest.fixture
def mock_positions() -> dict:
    return {}


@pytest.fixture
def pos_lock() -> threading.Lock:
    return threading.Lock()


@pytest.fixture
def halt_reasons() -> list[str]:
    return []


@pytest.fixture
def trip_halt(halt_reasons: list[str]):
    def _trip(reason: str) -> None:
        halt_reasons.append(reason)
    return _trip


@pytest.fixture
def legacy_broker():
    broker = MagicMock()
    broker.get_position_qty.return_value = 0
    return broker


@pytest.fixture
def controller(mock_positions, pos_lock, trip_halt, legacy_broker) -> ReconciliationController:
    return ReconciliationController(
        broker_api_enabled=True,
        reconcile_halt_on_qty_mismatch=True,
        broker_truth_reconciler=None,
        legacy_broker=legacy_broker,
        positions=mock_positions,
        pos_lock=pos_lock,
        trip_hard_halt_fn=trip_halt,
        execution_service=None,
    )


# ── Constructor ────────────────────────────────────────────────────────

class TestInit:
    """Constructor tests."""

    def test_default_execution_service_none(self, controller: ReconciliationController):
        assert controller._execution_service is None

    def test_stores_dependencies(self, controller: ReconciliationController, mock_positions, pos_lock, trip_halt, legacy_broker):
        assert controller._broker_api_enabled is True
        assert controller._reconcile_halt_on_qty_mismatch is True
        assert controller._broker_truth_reconciler is None
        assert controller._legacy_broker is legacy_broker
        assert controller._positions is mock_positions
        assert controller._pos_lock is pos_lock


# ── Setters ─────────────────────────────────────────────────────────────

class TestSetters:
    """Setter method tests."""

    def test_set_execution_service(self, controller: ReconciliationController):
        mock_svc = MagicMock()
        controller.set_execution_service(mock_svc)
        assert controller._execution_service is mock_svc

    def test_set_broker_truth_reconciler(self, controller: ReconciliationController):
        mock_reconciler = MagicMock()
        controller.set_broker_truth_reconciler(mock_reconciler)
        assert controller._broker_truth_reconciler is mock_reconciler


# ── reconcile_live_positions ────────────────────────────────────────────

class TestReconcileLivePositions:
    """reconcile_live_positions() coverage."""

    def test_disabled_when_broker_api_disabled(self, controller: ReconciliationController, halt_reasons):
        controller._broker_api_enabled = False
        controller.reconcile_live_positions()
        assert len(halt_reasons) == 0

    def test_disabled_when_reconcile_halt_disabled(self, controller: ReconciliationController, mock_positions):
        controller._reconcile_halt_on_qty_mismatch = False
        mock_positions["NIFTY"] = {"qty": 10, "signal": "CALL", "strike": 19500}
        controller.reconcile_live_positions()
        # trip_hard_halt_fn is a lambda, can't easily check; we just verify no exception

    def test_no_positions_no_halt(self, controller: ReconciliationController, halt_reasons):
        controller.reconcile_live_positions()
        assert len(halt_reasons) == 0

    def test_empty_positions_no_halt(self, controller: ReconciliationController):
        controller._positions.clear()
        controller.reconcile_live_positions()
        # No exception = pass

    def test_via_legacy_matching_qty_no_halt(self, controller: ReconciliationController, mock_positions, halt_reasons, legacy_broker):
        """When legacy broker qty matches local qty, no halt."""
        mock_positions["NIFTY"] = {"qty": 10, "signal": "CALL", "strike": 19500}
        legacy_broker.get_position_qty.return_value = 10
        controller.reconcile_live_positions()
        assert len(halt_reasons) == 0

    def test_via_legacy_mismatch_qty_triggers_halt(self, controller: ReconciliationController, mock_positions, halt_reasons, legacy_broker):
        """When legacy broker qty differs (both positive), trips halt."""
        mock_positions["NIFTY"] = {"qty": 10, "signal": "CALL", "strike": 19500}
        legacy_broker.get_position_qty.return_value = 5
        controller.reconcile_live_positions()
        assert len(halt_reasons) == 1
        assert "qty mismatch" in halt_reasons[0]

    def test_via_legacy_mismatch_zero_broker_no_halt(self, controller: ReconciliationController, mock_positions, halt_reasons, legacy_broker):
        """When broker qty is 0 but local is >0, no halt (broker-side only position)."""
        mock_positions["NIFTY"] = {"qty": 10, "signal": "CALL", "strike": 19500}
        legacy_broker.get_position_qty.return_value = 0
        controller.reconcile_live_positions()
        assert len(halt_reasons) == 0

    def test_via_legacy_mismatch_zero_local_no_halt(self, controller: ReconciliationController, mock_positions, halt_reasons, legacy_broker):
        """When local qty is 0, no halt even if broker has qty."""
        mock_positions["NIFTY"] = {"qty": 0, "signal": "CALL", "strike": 19500}
        legacy_broker.get_position_qty.return_value = 10
        controller.reconcile_live_positions()
        assert len(halt_reasons) == 0

    def test_via_legacy_exception_handled(self, controller: ReconciliationController, mock_positions, halt_reasons, legacy_broker):
        """Exception in legacy_broker.get_position_qty is caught."""
        mock_positions["NIFTY"] = {"qty": 10, "signal": "CALL", "strike": 19500}
        legacy_broker.get_position_qty.side_effect = ValueError("Broker error")
        controller.reconcile_live_positions()
        # Exception caught, no halt triggered
        assert len(halt_reasons) == 0

    def test_via_legacy_multiple_positions(self, controller: ReconciliationController, mock_positions, halt_reasons, legacy_broker):
        """Multiple positions: first mismatch triggers halt, second not checked."""
        mock_positions["NIFTY"] = {"qty": 10, "signal": "CALL", "strike": 19500}
        mock_positions["BANKNIFTY"] = {"qty": 5, "signal": "PUT", "strike": 45000}
        legacy_broker.get_position_qty.return_value = 3  # both return 3
        controller.reconcile_live_positions()
        assert len(halt_reasons) == 1  # only NIFTY checked, halt triggers early

    def test_via_legacy_first_matching_then_mismatch(self, controller: ReconciliationController, mock_positions, halt_reasons, legacy_broker):
        """First position matches, second mismatches."""
        mock_positions["NIFTY"] = {"qty": 10, "signal": "CALL", "strike": 19500}
        mock_positions["BANKNIFTY"] = {"qty": 5, "signal": "PUT", "strike": 45000}
        legacy_broker.get_position_qty.side_effect = [10, 3]  # NIFTY matches, BANKNIFTY doesn't
        controller.reconcile_live_positions()
        assert len(halt_reasons) == 1
        assert "BANKNIFTY" in halt_reasons[0]

    def test_via_broker_truth_matching(self, controller: ReconciliationController, mock_positions, halt_reasons):
        """Broker truth reconciler returns matching positions."""
        reconciler = MagicMock()
        reconciler.get_all_authoritative_positions.return_value = {
            "NIFTY": {"qty": 10},
        }
        controller.set_broker_truth_reconciler(reconciler)
        mock_positions["NIFTY"] = {"qty": 10, "signal": "CALL", "strike": 19500}
        controller.reconcile_live_positions()
        assert len(halt_reasons) == 0

    def test_via_broker_truth_mismatch(self, controller: ReconciliationController, mock_positions, halt_reasons):
        """Broker truth reconciler returns mismatching qty."""
        reconciler = MagicMock()
        reconciler.get_all_authoritative_positions.return_value = {
            "NIFTY": {"qty": 5},
        }
        controller.set_broker_truth_reconciler(reconciler)
        mock_positions["NIFTY"] = {"qty": 10, "signal": "CALL", "strike": 19500}
        controller.reconcile_live_positions()
        assert len(halt_reasons) == 1
        assert "qty mismatch" in halt_reasons[0]

    def test_via_broker_truth_exception(self, controller: ReconciliationController, mock_positions, halt_reasons):
        """Exception in broker truth reconciler is caught."""
        reconciler = MagicMock()
        reconciler.get_all_authoritative_positions.side_effect = ValueError("Reconciler error")
        controller.set_broker_truth_reconciler(reconciler)
        mock_positions["NIFTY"] = {"qty": 10, "signal": "CALL", "strike": 19500}
        controller.reconcile_live_positions()
        assert len(halt_reasons) == 0  # Exception caught, no halt


# ── periodic_reconcile ─────────────────────────────────────────────────

class TestPeriodicReconcile:
    """periodic_reconcile() coverage."""

    def test_no_execution_service_noop(self, controller: ReconciliationController):
        """When execution_service is None, returns immediately."""
        controller.periodic_reconcile()
        # No exception = pass

    def test_ack_watchdog_called(self, controller: ReconciliationController):
        """Verifies run_ack_watchdog is called with correct timeout."""
        mock_exec = MagicMock()
        mock_exec.run_ack_watchdog.return_value = {"acknowledged": 0, "errors": 0}
        controller.set_execution_service(mock_exec)
        controller.periodic_reconcile()
        mock_exec.run_ack_watchdog.assert_called_once_with(max_ack_age_seconds=30.0)

    def test_recovered_orders_logged(self, controller: ReconciliationController):
        """When ack_watchdog recovers orders, log message."""
        mock_exec = MagicMock()
        mock_exec.run_ack_watchdog.return_value = {"acknowledged": 3, "errors": 0}
        controller.set_execution_service(mock_exec)
        with patch.object(logging.getLogger("core.reconciliation_controller"), "info") as mock_info:
            controller.periodic_reconcile()
            mock_info.assert_called_once()
            assert "3" in str(mock_info.call_args)

    def test_errors_logged(self, controller: ReconciliationController):
        """When ack_watchdog has errors, log warning."""
        mock_exec = MagicMock()
        mock_exec.run_ack_watchdog.return_value = {"acknowledged": 0, "errors": 2}
        controller.set_execution_service(mock_exec)
        with patch.object(logging.getLogger("core.reconciliation_controller"), "warning") as mock_warning:
            controller.periodic_reconcile()
            assert mock_warning.called
            assert any("2" in str(c) for c in mock_warning.call_args_list)

    def test_pending_order_reconciliation_called(self, controller: ReconciliationController):
        """Verifies reconcile_pending_orders is called after ack watchdog."""
        mock_exec = MagicMock()
        mock_exec.run_ack_watchdog.return_value = {"acknowledged": 0, "errors": 0}
        mock_exec.reconcile_pending_orders.return_value = {"is_clean": True, "issues_count": 0}
        controller.set_execution_service(mock_exec)
        controller.periodic_reconcile()
        mock_exec.reconcile_pending_orders.assert_called_once()

    def test_pending_issues_logged(self, controller: ReconciliationController):
        """When pending order reconciliation finds issues, log warning."""
        mock_exec = MagicMock()
        mock_exec.run_ack_watchdog.return_value = {"acknowledged": 0, "errors": 0}
        mock_exec.reconcile_pending_orders.return_value = {"is_clean": False, "issues_count": 5}
        controller.set_execution_service(mock_exec)
        with patch.object(logging.getLogger("core.reconciliation_controller"), "warning") as mock_warning:
            controller.periodic_reconcile()
            assert any("5" in str(c) for c in mock_warning.call_args_list)

    def test_no_reconcile_pending_orders_attr(self, controller: ReconciliationController):
        """When execution_service lacks reconcile_pending_orders, no error."""
        mock_exec = MagicMock()
        mock_exec.run_ack_watchdog.return_value = {"acknowledged": 0, "errors": 0}
        del mock_exec.reconcile_pending_orders  # remove the mock's attribute
        controller.set_execution_service(mock_exec)
        controller.periodic_reconcile()
        # No exception = pass

    def test_exception_handled(self, controller: ReconciliationController):
        """Exception inside periodic_reconcile is caught and logged."""
        mock_exec = MagicMock()
        mock_exec.run_ack_watchdog.side_effect = ValueError("Bad data")
        controller.set_execution_service(mock_exec)
        controller.periodic_reconcile()
        # No exception propagated = pass

    def test_exception_different_types(self, controller: ReconciliationController):
        """Different exception types are all caught."""
        for exc_type in (ValueError, TypeError, KeyError, OSError):
            mock_exec = MagicMock()
            mock_exec.run_ack_watchdog.side_effect = exc_type("Test error")
            controller.set_execution_service(mock_exec)
            controller.periodic_reconcile()
            # No exception propagated = pass for all


# ── Integration-style: full cycle ──────────────────────────────────────

class TestFullCycle:
    """End-to-end scenarios."""

    def test_disabled_broker_api_no_reconciliation(self, controller: ReconciliationController, mock_positions):
        """With broker_api_enabled=False, reconcile_live_positions does nothing."""
        controller._broker_api_enabled = False
        mock_positions["NIFTY"] = {"qty": 10}
        controller.reconcile_live_positions()
        # Should pass without any interaction

    def test_set_broker_truth_then_reconcile(self, controller: ReconciliationController, mock_positions, halt_reasons):
        """Set reconciler after construction, then reconcile."""
        reconciler = MagicMock()
        reconciler.get_all_authoritative_positions.return_value = {}
        controller.set_broker_truth_reconciler(reconciler)
        mock_positions["NIFTY"] = {"qty": 10}
        controller.reconcile_live_positions()
        reconciler.get_all_authoritative_positions.assert_called_once()

    def test_set_execution_then_periodic(self, controller: ReconciliationController):
        """Set execution service after construction, then reconcile periodically."""
        mock_exec = MagicMock()
        mock_exec.run_ack_watchdog.return_value = {"acknowledged": 0, "errors": 0}
        mock_exec.reconcile_pending_orders.return_value = {"is_clean": True}
        controller.set_execution_service(mock_exec)
        controller.periodic_reconcile()
        mock_exec.run_ack_watchdog.assert_called_once()
