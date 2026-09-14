from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from core.ports.execution.execution_port import ExecutionContext, ExecutionMode, ExecutionPort
from core.strategy.multi_asset_dispatcher import _build_broker_executor_for_dispatcher


@pytest.fixture
def mock_exec_service():
    service = Mock()
    service.execute_order.return_value = SimpleNamespace(
        status="FILLED",
        average_price=150.0,
        success=True,
    )
    return service


@pytest.fixture
def mock_container(mock_exec_service):
    container = Mock()
    container.resolve.side_effect = lambda port: mock_exec_service if port is ExecutionPort else None
    return container


def test_multi_asset_entry_persists_signal_before_execution(mock_exec_service, mock_container):
    with patch(
        "core.di_container.get_container",
        return_value=mock_container,
    ), patch(
        "core.signals.signal_tracker.SignalTracker.get_instance"
    ) as get_tracker:
        tracker = Mock()
        tracker.record_generated_signal.return_value = "SIG-MULTI-001"
        get_tracker.return_value = tracker

        execute_entry, _ = _build_broker_executor_for_dispatcher(
            {"EXECUTION_MODE": "PAPER"}
        )

        ok = execute_entry(
            symbol="RELIANCE",
            direction="BUY",
            quantity=10,
            entry_price=2500.0,
            strategy_id="equity_breakout",
            idempotency_key="idem-multi-01",
        )

        assert ok is True
        tracker.record_generated_signal.assert_called_once()
        rec = tracker.record_generated_signal.call_args.args[0]
        assert rec["symbol"] == "RELIANCE"
        assert rec["direction"] == "BUY"
        assert rec["entry_price"] == 2500.0
        assert rec["strategy"] == "equity_breakout"

        mock_exec_service.execute_order.assert_called_once()
        order_req, context = mock_exec_service.execute_order.call_args.args
        assert order_req.symbol == "RELIANCE"
        assert order_req.direction == "BUY"
        assert isinstance(context, ExecutionContext)
        assert context.signal_id == "SIG-MULTI-001"
        assert context.execution_mode is ExecutionMode.PAPER


def test_multi_asset_entry_reuses_existing_signal_id(mock_exec_service, mock_container):
    with patch(
        "core.di_container.get_container",
        return_value=mock_container,
    ), patch(
        "core.signals.signal_tracker.SignalTracker.get_instance"
    ) as get_tracker:
        tracker = Mock()
        get_tracker.return_value = tracker

        execute_entry, _ = _build_broker_executor_for_dispatcher(
            {"EXECUTION_MODE": "AUTO"}
        )

        ok = execute_entry(
            symbol="TCS",
            direction="SELL",
            quantity=5,
            entry_price=3800.0,
            signal_id="SIG-EXISTING-999",
            strategy_id="equity_mean_reversion",
            idempotency_key="idem-multi-02",
        )

        assert ok is True
        tracker.record_generated_signal.assert_not_called()

        mock_exec_service.execute_order.assert_called_once()
        _, context = mock_exec_service.execute_order.call_args.args
        assert context.signal_id == "SIG-EXISTING-999"
        assert context.execution_mode is ExecutionMode.AUTOMATIC


def test_multi_asset_entry_fails_closed_when_durable_signal_fails(mock_exec_service, mock_container):
    with patch(
        "core.di_container.get_container",
        return_value=mock_container,
    ), patch(
        "core.signals.signal_tracker.SignalTracker.get_instance"
    ) as get_tracker:
        tracker = Mock()
        tracker.record_generated_signal.return_value = ""  # Persistence failed
        get_tracker.return_value = tracker

        execute_entry, _ = _build_broker_executor_for_dispatcher(
            {"EXECUTION_MODE": "PAPER"}
        )

        ok = execute_entry(
            symbol="INFY",
            direction="BUY",
            quantity=15,
            entry_price=1600.0,
            strategy_id="equity_trend",
            idempotency_key="idem-multi-03",
        )

        assert ok is False
        tracker.record_generated_signal.assert_called_once()
        mock_exec_service.execute_order.assert_not_called()
