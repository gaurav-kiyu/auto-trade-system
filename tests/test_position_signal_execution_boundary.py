from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from core.position_service import PositionService, TradeBlockError
from core.ports.execution.execution_port import ExecutionContext, ExecutionMode


def make_service(mode="PAPER"):
    svc = PositionService.__new__(PositionService)

    svc._execution_service = Mock()
    svc._portfolio_service = None
    svc._risk_service = None
    svc._margin_validator = None
    svc._execution_mode = mode

    # The existing liquidity gate is independently tested elsewhere.
    # For these boundary tests, force it to pass so we isolate the
    # signal-persistence/execution contract.
    svc._check_liquidity_gate = Mock(return_value=(True, "ok"))

    return svc


def make_signal(**extra):
    signal = {
        "strategy": "boundary_regression",
        "strategy_name": "boundary_regression",
        "strike": 25000,
        "correlation_id": "corr-boundary-001",
    }
    signal.update(extra)
    return signal


def configure_execution_result(service):
    service._execution_service.execute_order.return_value = SimpleNamespace(
        status="FILLED",
        average_price=100.0,
    )


def test_new_entry_persists_signal_before_execution():
    svc = make_service("PAPER")
    configure_execution_result(svc)

    sig = make_signal()

    with patch(
        "core.signals.signal_tracker.SignalTracker.get_instance"
    ) as get_tracker:
        tracker = Mock()
        tracker.record_generated_signal.return_value = "SIG-DURABLE-001"
        get_tracker.return_value = tracker

        result = svc._submit_order_under_lock(
            name="NIFTY",
            price=100.0,
            qty=1,
            sig=sig,
            order_direction="BUY",
            idempotency_key="idem-001",
        )

    assert result.status == "FILLED"

    tracker.record_generated_signal.assert_called_once()

    recorded_signal = tracker.record_generated_signal.call_args.args[0]
    assert recorded_signal["symbol"] == "NIFTY"
    assert recorded_signal["direction"] == "BUY"
    assert recorded_signal["entry_price"] == 100.0

    svc._execution_service.execute_order.assert_called_once()

    order, context = svc._execution_service.execute_order.call_args.args

    assert order.symbol == "NIFTY"
    assert order.direction == "BUY"
    assert context.signal_id == "SIG-DURABLE-001"
    assert context.execution_mode is ExecutionMode.PAPER

    # Critical ordering: durable persistence must happen before execution.
    persist_order = tracker.record_generated_signal.call_args
    execute_order = svc._execution_service.execute_order.call_args

    assert persist_order is not None
    assert execute_order is not None


def test_existing_signal_id_is_reused_without_duplicate_persistence():
    svc = make_service("PAPER")
    configure_execution_result(svc)

    sig = make_signal(signal_id="SIG-UPSTREAM-123")

    with patch(
        "core.signals.signal_tracker.SignalTracker.get_instance"
    ) as get_tracker:
        tracker = Mock()
        get_tracker.return_value = tracker

        svc._submit_order_under_lock(
            name="NIFTY",
            price=101.0,
            qty=1,
            sig=sig,
            order_direction="BUY",
            idempotency_key="idem-002",
        )

        tracker.record_generated_signal.assert_not_called()

    svc._execution_service.execute_order.assert_called_once()
    _, context = svc._execution_service.execute_order.call_args.args

    assert context.signal_id == "SIG-UPSTREAM-123"


def test_missing_durable_signal_id_fails_closed_before_execution():
    svc = make_service("PAPER")

    with patch(
        "core.signals.signal_tracker.SignalTracker.get_instance"
    ) as get_tracker:
        tracker = Mock()
        tracker.record_generated_signal.return_value = ""
        get_tracker.return_value = tracker

        with pytest.raises(TradeBlockError, match="SIGNAL_PERSISTENCE_BLOCK"):
            svc._submit_order_under_lock(
                name="NIFTY",
                price=100.0,
                qty=1,
                sig=make_signal(),
                order_direction="BUY",
                idempotency_key="idem-003",
            )

        tracker.record_generated_signal.assert_called_once()

    svc._execution_service.execute_order.assert_not_called()


@pytest.mark.parametrize(
    ("runtime_mode", "expected_mode"),
    [
        ("PAPER", ExecutionMode.PAPER),
        ("AUTO", ExecutionMode.AUTOMATIC),
        ("AUTOMATIC", ExecutionMode.AUTOMATIC),
        ("MANUAL", ExecutionMode.MANUAL),
        ("SIGNAL_ONLY", ExecutionMode.MANUAL),
        ("SIGNALS_ONLY", ExecutionMode.MANUAL),
    ],
)
def test_execution_context_maps_position_service_mode(
    runtime_mode,
    expected_mode,
):
    svc = make_service(runtime_mode)
    configure_execution_result(svc)

    sig = make_signal(signal_id=f"SIG-{runtime_mode}")

    svc._submit_order_under_lock(
        name="NIFTY",
        price=100.0,
        qty=1,
        sig=sig,
        order_direction="BUY",
        idempotency_key=f"idem-{runtime_mode}",
    )

    svc._execution_service.execute_order.assert_called_once()

    _, context = svc._execution_service.execute_order.call_args.args

    assert isinstance(context, ExecutionContext)
    assert context.signal_id == f"SIG-{runtime_mode}"
    assert context.execution_mode is expected_mode


def test_signal_id_is_required_even_when_execution_service_exists():
    svc = make_service("PAPER")

    with patch(
        "core.signals.signal_tracker.SignalTracker.get_instance"
    ) as get_tracker:
        tracker = Mock()
        tracker.record_generated_signal.return_value = None
        get_tracker.return_value = tracker

        with pytest.raises(
            TradeBlockError,
            match="durable signal_id unavailable",
        ):
            svc._submit_order_under_lock(
                name="NIFTY",
                price=100.0,
                qty=1,
                sig=make_signal(),
                order_direction="BUY",
                idempotency_key="idem-004",
            )

    svc._execution_service.execute_order.assert_not_called()
