"""Tests for core/execution/continuous_reconciliation.py - Continuous Reconciliation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.execution.continuous_reconciliation import (
    ContinuousReconciliation,
    ReconciliationIssue,
    ReconciliationReport,
    get_continuous_reconciliation,
    start_continuous_reconciliation,
)


class FakeBrokerPort:
    """Minimal broker port for testing."""

    def is_healthy(self) -> bool:
        return True

    def get_positions(self) -> dict:
        return {"NIFTY": {"symbol": "NIFTY", "qty": 50, "pnl": 100.0}}

    def get_orders(self) -> dict:
        return {"ORD_001": {"status": "FILLED", "qty": 50, "symbol": "NIFTY"}}

    def get_funds(self) -> dict:
        return {"available_cash": 50000, "used_margin": 25000, "total_value": 75000}


class TestReconciliationReport:
    """ReconciliationReport dataclass coverage."""

    def test_defaults(self):
        from datetime import datetime
        r = ReconciliationReport(timestamp=datetime.now())
        assert r.orders_checked == 0
        assert r.positions_checked == 0
        assert r.issues_found == []
        assert r.broker_reachable is True
        assert r.cycle_time_ms == 0.0


class TestReconciliationIssue:
    """ReconciliationIssue dataclass coverage."""

    def test_defaults(self):
        from datetime import datetime
        i = ReconciliationIssue(
            timestamp=datetime.now(),
            issue_type="orphan_order",
            description="Test issue",
        )
        assert i.requires_manual_intervention is False
        assert i.broker_value is None
        assert i.local_value is None


class TestContinuousReconciliation:
    """ContinuousReconciliation coverage."""

    @pytest.fixture
    def service(self):
        broker = FakeBrokerPort()
        s = ContinuousReconciliation(
            broker_port=broker,
            config={
                "CONTINUOUS_RECONCILIATION_ENABLED": True,
                "RECONCILIATION_ACTIVE_INTERVAL_SEC": 3600,  # Long interval for tests
                "RECONCILIATION_IDLE_INTERVAL_SEC": 3600,
            },
        )
        yield s
        if s._running:
            s.stop()

    def test_init(self, service):
        assert service._enabled is True
        assert service._running is False
        assert service._thread is None

    def test_start_stop(self, service):
        service.start()
        assert service._running is True
        assert service._thread is not None
        assert service._thread.is_alive() is True
        service.stop()
        assert service._running is False

    def test_start_already_running(self, service):
        service.start()
        service.start()  # Should log warning, not crash
        assert service._running is True
        service.stop()

    def test_start_disabled(self, service):
        service._enabled = False
        service.start()
        assert service._running is False

    def test_force_cycle(self, service):
        report = service.force_cycle()
        assert isinstance(report, ReconciliationReport)
        assert report.orders_checked >= 0

    def test_force_cycle_with_connectivity(self, service):
        report = service.force_cycle()
        assert report.broker_reachable is True

    def test_handle_issue_appends_to_list(self, service):
        from datetime import datetime
        issue = ReconciliationIssue(
            timestamp=datetime.now(),
            issue_type="orphan_order",
            description="Test orphan",
        )
        service._handle_issue(issue)
        issues = service.get_issues()
        assert len(issues) == 1
        assert issues[0].issue_type == "orphan_order"

    def test_handle_issue_calls_callback(self, service):
        callback = MagicMock()
        service._on_issue_callback = callback
        from datetime import datetime
        issue = ReconciliationIssue(
            timestamp=datetime.now(),
            issue_type="status_drift",
            description="Test drift",
        )
        service._handle_issue(issue)
        callback.assert_called_once_with(issue)

    def test_handle_issue_callback_failure(self, service):
        def failing_callback(issue):
            raise TypeError("Callback error")

        service._on_issue_callback = failing_callback
        from datetime import datetime
        issue = ReconciliationIssue(
            timestamp=datetime.now(),
            issue_type="status_drift",
            description="Test drift",
        )
        # Should not raise
        service._handle_issue(issue)

    def test_get_last_cycle_time_none(self, service):
        assert service.get_last_cycle_time() is None

    def test_health_check(self, service):
        health = service.health_check()
        assert health["running"] is False
        assert health["issues_count"] == 0
        assert health["enabled"] is True

    def test_health_check_after_cycle(self, service):
        # force_cycle calls _run_cycle which doesn't set _last_cycle_time
        # (that's set in _run_loop). So we manually set it for the test.
        service.force_cycle()
        from datetime import datetime
        service._last_cycle_time = datetime.now()
        health = service.health_check()
        assert health["last_cycle"] is not None

    def test_reconcile_order_mismatch(self, service):
        """Test reconciling an order that exists in local but not broker."""
        order = {"order_id": "UNKNOWN_ORD", "status": "PENDING"}
        result = service._reconcile_order(order)
        # Order not found in broker -> orphan_order issue
        assert result is not None
        assert result.issue_type == "orphan_order"

    def test_reconcile_position_no_local(self, service):
        """Reconcile a symbol where broker doesn't have position but local does."""
        from core.datetime_ist import now_ist
        # Set cache to empty with a fresh timestamp so it doesn't re-fetch from broker
        service._reconciler._cached_positions = {}
        service._reconciler._cached_positions_time = now_ist()
        symbol = "NIFTY"
        local_pos = {"qty": 50}
        result = service._reconcile_position(symbol, local_pos)
        assert result is not None
        assert result.issue_type == "missing_position"

    def test_reconcile_position_mismatch(self, service):
        """Reconcile when local and broker disagree."""
        service._reconciler._cached_positions = {"NIFTY": {"quantity": 50}}
        symbol = "NIFTY"
        local_pos = {"qty": 25}
        result = service._reconcile_position(symbol, local_pos)
        assert result is not None
        assert result.issue_type == "position_mismatch"

    def test_get_local_orders_empty(self, service):
        orders = service._get_local_orders()
        assert orders == []

    def test_get_local_positions_empty(self, service):
        positions = service._get_local_positions()
        assert positions == {}


class TestGetContinuousReconciliation:
    """Singleton get_continuous_reconciliation coverage."""

    def test_no_broker_returns_none(self):
        result = get_continuous_reconciliation()
        assert result is None

    def test_with_broker_returns_instance(self):
        broker = FakeBrokerPort()
        result = get_continuous_reconciliation(broker_port=broker)
        assert isinstance(result, ContinuousReconciliation)
        if result and result._running:
            result.stop()


class TestStartContinuousReconciliation:
    """start_continuous_reconciliation coverage."""

    def test_start_function(self):
        broker = FakeBrokerPort()
        svc = start_continuous_reconciliation(broker)
        assert isinstance(svc, ContinuousReconciliation)
        if svc:
            svc.stop()
