"""Tests for core.execution_wiring — execution safety component integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.execution_wiring import (
    ExecutionSafetyWiring,
    create_safety_wiring,
)


# ── ExecutionSafetyWiring construction ───────────────────────────────────

def test_wiring_defaults() -> None:
    wiring = ExecutionSafetyWiring()
    assert wiring._db_path == "trades.db"
    assert wiring._broker_port is None
    assert wiring._initialized is False


def test_wiring_custom_params() -> None:
    broker = MagicMock()
    wiring = ExecutionSafetyWiring(db_path="custom.db", broker_port=broker)
    assert wiring._db_path == "custom.db"
    assert wiring._broker_port is broker


# ── initialize ───────────────────────────────────────────────────────────

# The imports in execution_wiring are done INSIDE initialize(), so we patch the source modules
@patch("core.execution.durable_state.DurableExecutionStore")
@patch("core.execution.broker_ack_validator.BrokerAckValidator")
@patch("core.execution.broker_state_handler.create_state_handler")
@patch("core.execution_error_classifier.BrokerErrorClassifier")
@patch("core.startup_reconciliation.StartupReconciler")
@patch("core.component_health_monitor.get_health_monitor")
def test_wiring_initialize_all_components(
    mock_health, mock_reconciler, mock_classifier,
    mock_handler, mock_validator, mock_store,
) -> None:
    broker = MagicMock()
    wiring = ExecutionSafetyWiring(db_path=":memory:", broker_port=broker)
    wiring.initialize()

    assert wiring._initialized is True
    assert wiring.durable_store is not None
    assert wiring.ack_validator is not None
    assert wiring.state_handler is not None
    assert wiring.error_classifier is not None
    assert wiring.startup_reconciler is not None
    assert wiring.health_monitor is not None


@patch("core.execution.durable_state.DurableExecutionStore")
@patch("core.execution.broker_ack_validator.BrokerAckValidator")
@patch("core.execution.broker_state_handler.create_state_handler")
@patch("core.execution_error_classifier.BrokerErrorClassifier")
@patch("core.startup_reconciliation.StartupReconciler")
@patch("core.component_health_monitor.get_health_monitor")
def test_wiring_initialize_idempotent(
    mock_health, mock_reconciler, mock_classifier,
    mock_handler, mock_validator, mock_store,
) -> None:
    wiring = ExecutionSafetyWiring()
    wiring.initialize()
    wiring.initialize()  # Second call should be no-op
    assert mock_store.call_count == 1  # Only called once


# ── run_startup_reconciliation ──────────────────────────────────────────

@patch("core.execution.durable_state.DurableExecutionStore")
@patch("core.execution.broker_ack_validator.BrokerAckValidator")
@patch("core.execution.broker_state_handler.create_state_handler")
@patch("core.execution_error_classifier.BrokerErrorClassifier")
@patch("core.startup_reconciliation.StartupReconciler")
@patch("core.component_health_monitor.get_health_monitor")
def test_run_startup_reconciliation(
    mock_health, mock_reconciler, mock_classifier,
    mock_handler, mock_validator, mock_store,
) -> None:
    mock_reconciler.return_value.reconcile.return_value.is_clean = True
    mock_reconciler.return_value.reconcile.return_value.broker_reachable = True
    mock_reconciler.return_value.reconcile.return_value.auth_valid = True
    mock_reconciler.return_value.reconcile.return_value.errors = []

    wiring = ExecutionSafetyWiring()
    result = wiring.run_startup_reconciliation()
    assert result["is_clean"] is True
    assert result["errors"] == []


# ── get_health_status ────────────────────────────────────────────────────

@patch("core.execution.durable_state.DurableExecutionStore")
@patch("core.execution.broker_ack_validator.BrokerAckValidator")
@patch("core.execution.broker_state_handler.create_state_handler")
@patch("core.execution_error_classifier.BrokerErrorClassifier")
@patch("core.startup_reconciliation.StartupReconciler")
@patch("core.component_health_monitor.get_health_monitor")
def test_get_health_status(
    mock_health, mock_reconciler, mock_classifier,
    mock_handler, mock_validator, mock_store,
) -> None:
    mock_health.return_value.format_status.return_value = "All healthy"

    wiring = ExecutionSafetyWiring()
    status = wiring.get_health_status()
    assert status == "All healthy"


# ── check_trading_allowed ────────────────────────────────────────────────

@patch("core.execution.durable_state.DurableExecutionStore")
@patch("core.execution.broker_ack_validator.BrokerAckValidator")
@patch("core.execution.broker_state_handler.create_state_handler")
@patch("core.execution_error_classifier.BrokerErrorClassifier")
@patch("core.startup_reconciliation.StartupReconciler")
@patch("core.component_health_monitor.get_health_monitor")
def test_check_trading_allowed(
    mock_health, mock_reconciler, mock_classifier,
    mock_handler, mock_validator, mock_store,
) -> None:
    mock_store.return_value.get_non_terminal_executions.return_value = []

    wiring = ExecutionSafetyWiring()
    allowed, reason = wiring.check_trading_allowed()
    assert allowed is True
    assert "allowed" in reason


@patch("core.execution.durable_state.DurableExecutionStore")
@patch("core.execution.broker_ack_validator.BrokerAckValidator")
@patch("core.execution.broker_state_handler.create_state_handler")
@patch("core.execution_error_classifier.BrokerErrorClassifier")
@patch("core.startup_reconciliation.StartupReconciler")
@patch("core.component_health_monitor.get_health_monitor")
def test_check_trading_blocked_too_many_pending(
    mock_health, mock_reconciler, mock_classifier,
    mock_handler, mock_validator, mock_store,
) -> None:
    # 15 pending executions > threshold of 10
    mock_store.return_value.get_non_terminal_executions.return_value = list(range(15))

    wiring = ExecutionSafetyWiring()
    allowed, reason = wiring.check_trading_allowed()
    assert allowed is False
    assert "pending" in reason


# ── create_safety_wiring factory ─────────────────────────────────────────

@patch("core.execution.durable_state.DurableExecutionStore")
@patch("core.execution.broker_ack_validator.BrokerAckValidator")
@patch("core.execution.broker_state_handler.create_state_handler")
@patch("core.execution_error_classifier.BrokerErrorClassifier")
@patch("core.startup_reconciliation.StartupReconciler")
@patch("core.component_health_monitor.get_health_monitor")
def test_create_safety_wiring(
    mock_health, mock_reconciler, mock_classifier,
    mock_handler, mock_validator, mock_store,
) -> None:
    wiring = create_safety_wiring(db_path=":memory:", broker_port=MagicMock())
    assert isinstance(wiring, ExecutionSafetyWiring)
    assert wiring._initialized is True
