"""Tests for ComponentHealthMonitor — health monitoring for trading components."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.component_health_monitor import (
    ComponentHealth,
    ComponentHealthMonitor,
    get_health_monitor,
)


class TestComponentHealth:
    """ComponentHealth dataclass."""

    def test_default_details_is_empty_dict(self):
        health = ComponentHealth(
            component_name="test", is_healthy=True, message="ok",
            last_check=None,  # type: ignore
        )
        assert health.details == {}

    def test_details_preserved(self):
        health = ComponentHealth(
            component_name="test", is_healthy=True, message="ok",
            last_check=None, details={"key": "value"},  # type: ignore
        )
        assert health.details == {"key": "value"}


class TestComponentHealthMonitor:
    """ComponentHealthMonitor — monitors system component health."""

    def test_no_components_returns_empty(self):
        monitor = ComponentHealthMonitor()
        results = monitor.check_all()
        assert results == []

    def test_register_adds_component(self):
        monitor = ComponentHealthMonitor()
        monitor.register("test_component", object())
        assert "test_component" in monitor._components

    def test_unknown_component_type_returns_healthy(self):
        monitor = ComponentHealthMonitor()
        monitor.register("unknown_thing", MagicMock())
        results = monitor.check_all()
        assert results[0].is_healthy is True

    # ── Durable store checks ───────────────────────────────────────

    def test_healthy_durable_store(self):
        store = MagicMock()
        store.get_non_terminal_executions.return_value = []
        monitor = ComponentHealthMonitor()
        monitor.register("durable_store", store)
        results = monitor.check_all()
        assert results[0].is_healthy is True
        assert results[0].message == "Healthy"

    def test_unhealthy_durable_store(self):
        store = MagicMock()
        store.get_non_terminal_executions.side_effect = ValueError("DB error")
        monitor = ComponentHealthMonitor()
        monitor.register("durable_store", store)
        results = monitor.check_all()
        assert results[0].is_healthy is False

    # ── Execution service checks ───────────────────────────────────

    def test_healthy_execution_service(self):
        svc = MagicMock()
        svc.is_trading_frozen.return_value = False
        monitor = ComponentHealthMonitor()
        monitor.register("execution_service", svc)
        results = monitor.check_all()
        assert results[0].is_healthy is True

    def test_frozen_execution_service(self):
        svc = MagicMock()
        svc.is_trading_frozen.return_value = True
        monitor = ComponentHealthMonitor()
        monitor.register("execution_service", svc)
        results = monitor.check_all()
        assert results[0].is_healthy is False
        assert "frozen" in results[0].message.lower()

    def test_execution_service_no_is_trading_frozen(self):
        svc = MagicMock(spec=[])  # no methods
        monitor = ComponentHealthMonitor()
        monitor.register("execution_service", svc)
        results = monitor.check_all()
        # Should handle missing method gracefully
        assert results[0].is_healthy is True

    # ── Circuit breaker checks ─────────────────────────────────────

    def test_healthy_circuit_breaker(self):
        cb = MagicMock()
        cb.get_state.return_value.level.value = "NORMAL"
        cb.get_state.return_value.market_status.value = "OPEN"
        monitor = ComponentHealthMonitor()
        monitor.register("circuit_breaker", cb)
        results = monitor.check_all()
        assert results[0].is_healthy is True
        assert results[0].message == "Level: NORMAL"

    def test_circuit_breaker_no_state_method(self):
        cb = MagicMock(spec=[])
        monitor = ComponentHealthMonitor()
        monitor.register("circuit_breaker", cb)
        results = monitor.check_all()
        assert results[0].is_healthy is True
        assert "no state" in results[0].message.lower()

    # ── Lot size validator checks ──────────────────────────────────

    def test_lot_size_validator_healthy(self):
        validator = MagicMock()
        monitor = ComponentHealthMonitor()
        monitor.register("lot_size_validator", validator)
        results = monitor.check_all()
        assert results[0].is_healthy is True

    # ── Risk engine checks ─────────────────────────────────────────

    def test_healthy_risk_engine(self):
        engine = MagicMock()
        engine._hard_halt = False
        monitor = ComponentHealthMonitor()
        monitor.register("risk_engine", engine)
        results = monitor.check_all()
        assert results[0].is_healthy is True
        assert "healthy" in results[0].message.lower()

    def test_halted_risk_engine(self):
        engine = MagicMock()
        engine._hard_halt = True
        monitor = ComponentHealthMonitor()
        monitor.register("risk_engine", engine)
        results = monitor.check_all()
        assert results[0].is_healthy is False
        assert "halt" in results[0].message.lower()

    def test_risk_engine_missing_hard_halt(self):
        engine = MagicMock(spec=[])
        monitor = ComponentHealthMonitor()
        monitor.register("risk_engine", engine)
        results = monitor.check_all()
        # getattr with default should make it healthy
        assert results[0].is_healthy is True

    # ── get_unhealthy_count ────────────────────────────────────────

    def test_get_unhealthy_count_zero(self):
        store = MagicMock()
        store.get_non_terminal_executions.return_value = []
        monitor = ComponentHealthMonitor()
        monitor.register("durable_store", store)
        assert monitor.get_unhealthy_count() == 0

    def test_get_unhealthy_count_one(self):
        store = MagicMock()
        store.get_non_terminal_executions.side_effect = ValueError("fail")
        monitor = ComponentHealthMonitor()
        monitor.register("durable_store", store)
        assert monitor.get_unhealthy_count() == 1

    # ── format_status ──────────────────────────────────────────────

    def test_format_status_includes_healthy_emoji(self):
        store = MagicMock()
        store.get_non_terminal_executions.return_value = []
        monitor = ComponentHealthMonitor()
        monitor.register("durable_store", store)
        status = monitor.format_status()
        assert "✅" in status
        assert "Healthy" in status

    def test_format_status_includes_unhealthy_emoji(self):
        store = MagicMock()
        store.get_non_terminal_executions.side_effect = ValueError("fail")
        monitor = ComponentHealthMonitor()
        monitor.register("durable_store", store)
        status = monitor.format_status()
        assert "❌" in status or "unhealthy" in status.lower()

    # ── Global monitor singleton ───────────────────────────────────

    def test_get_health_monitor_returns_instance(self):
        monitor = get_health_monitor()
        assert isinstance(monitor, ComponentHealthMonitor)

    def test_get_health_monitor_is_singleton(self):
        m1 = get_health_monitor()
        m2 = get_health_monitor()
        assert m1 is m2

    # ── Error handling for health checks ───────────────────────────

    def test_check_component_catches_unknown_exception(self):
        monitor = ComponentHealthMonitor()

        class FailingComponent:
            def failing_method(self):
                raise ValueError("test error")

        monitor.register("durable_store", FailingComponent())
        # get_non_terminal_executions doesn't exist on FailingComponent
        # This should be caught by the generic exception handler
        results = monitor.check_all()
        assert results[0].is_healthy is False
