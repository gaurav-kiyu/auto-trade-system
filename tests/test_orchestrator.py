"""Tests for core.orchestrator - legacy synchronous Orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.orchestrator import (
    Orchestrator,
    OrchestratorCycle,
    OrchestratorSignal,
    _ExecutionFill,
    _ExecutionResult,
)

# ── Shared helper ─────────────────────────────────────────────────────────


def _make_mock_execution_service():
    """Create a mock ExecutionService for orchestrator integration tests."""
    import time as _time_module
    from datetime import datetime
    from unittest.mock import MagicMock

    from core.ports.execution.execution_port import OrderResult, OrderStatus

    def execute_order(order_request, execution_context=None):
        """Simulate order execution, returning a mock OrderResult."""
        return OrderResult(
            order_id=f"exec_{order_request.symbol}_{int(_time_module.time())}",
            status=OrderStatus.FILLED,
            filled_quantity=order_request.lot_size,
            average_price=order_request.strike_price,
            timestamp=datetime.now(),
        )

    service = MagicMock()
    service.execute_order.side_effect = execute_order
    return service


# ═════════════════════════════════════════════════════════════════════════
# Execution Dataclass Tests
# ═════════════════════════════════════════════════════════════════════════


class TestDataclasses:
    """Execution dataclasses: _ExecutionFill, _ExecutionResult, OrchestratorSignal, OrchestratorCycle."""

    def test_fill_default(self) -> None:
        fill = _ExecutionFill(ok=True)
        assert fill.ok is True
        assert fill.filled_qty == 0
        assert fill.fill_price is None
        assert fill.status_verified is False
        assert fill.reason == ""

    def test_fill_custom(self) -> None:
        fill = _ExecutionFill(ok=True, filled_qty=50, fill_price=23000.0, status_verified=True, reason="filled")
        assert fill.ok is True
        assert fill.filled_qty == 50
        assert fill.fill_price == 23000.0
        assert fill.status_verified is True

    def test_fill_frozen(self) -> None:
        fill = _ExecutionFill(ok=True)
        import pytest
        with pytest.raises(AttributeError):
            fill.ok = False  # type: ignore[misc]

    def test_result_default(self) -> None:
        result = _ExecutionResult(ok=False)
        assert result.ok is False
        assert result.order_id is None
        assert result.broker_latency_ms == 0

    def test_result_custom(self) -> None:
        result = _ExecutionResult(ok=True, order_id="ORD001", broker_latency_ms=150, reason="success")
        assert result.ok is True
        assert result.order_id == "ORD001"

    def test_signal_default(self) -> None:
        signal = OrchestratorSignal(name="NIFTY", signal={"score": 75}, risk=MagicMock())
        assert signal.name == "NIFTY"
        assert signal.signal["score"] == 75
        assert signal.executed is False
        assert signal.execution_result is None
        assert signal.execution_fill is None

    def test_cycle_default(self) -> None:
        cycle = OrchestratorCycle(snapshot=MagicMock(), signals=[], reconciliation=None, saved=True)
        assert cycle.saved is True
        assert cycle.signals == []
        assert cycle.note == ""


# ═════════════════════════════════════════════════════════════════════════
# Default Order Builder Tests
# ═════════════════════════════════════════════════════════════════════════


class TestDefaultOrderBuilder:
    """Orchestrator._default_order_builder static method."""

    def test_basic(self) -> None:
        order = Orchestrator._default_order_builder("NIFTY", {"direction": "PUT", "qty": 2, "strike": 45000})
        assert order["name"] == "NIFTY"
        assert order["direction"] == "PUT"
        assert order["qty"] == 2
        assert order["strike"] == 45000

    def test_fallback(self) -> None:
        order = Orchestrator._default_order_builder("BANKNIFTY", {})
        assert order["name"] == "BANKNIFTY"
        assert order["direction"] == "CALL"
        assert order["qty"] == 1
        assert order["strike"] == 0


# ═════════════════════════════════════════════════════════════════════════
# Orchestrator Construction Tests
# ═════════════════════════════════════════════════════════════════════════


class TestOrchestratorConstruction:
    """Orchestrator initialization with various parameters."""

    def test_construction(self) -> None:
        data_engine = MagicMock()
        strategy_engine = MagicMock()
        risk_engine = MagicMock()
        state_manager = MagicMock()
        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=None,
            state_manager=state_manager,
        )
        assert orch._data_engine is data_engine
        assert callable(orch._names_provider)
        assert callable(orch._entry_gate_fn)
        assert callable(orch._execution_mode_fn)
        assert orch._enforce_market_hours is False


# ═════════════════════════════════════════════════════════════════════════
# run_cycle Edge Case Tests
# ═════════════════════════════════════════════════════════════════════════


class TestRunCycle:
    """Orchestrator.run_cycle edge cases and safety gates."""

    def test_empty_names(self) -> None:
        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = MagicMock(healthy=True, note="ok", frames={})

        strategy_engine = MagicMock()
        risk_engine = MagicMock()
        state_manager = MagicMock()

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=None,
            state_manager=state_manager,
            names_provider=lambda: [],
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()
        assert isinstance(cycle, OrchestratorCycle)
        assert cycle.signals == []
        assert cycle.saved is True

    def test_manual_mode_no_execution(self) -> None:
        mock_snapshot = MagicMock(healthy=True, note="ok")
        mock_snapshot.frames = {"NIFTY": {"1m": "data"}}
        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = mock_snapshot

        strategy_engine = MagicMock()
        strategy_engine.generate_signal.return_value = {"score": 75, "direction": "CALL", "vol_ratio": 1.4}

        risk_engine = MagicMock()
        risk_engine.quality_check.return_value = MagicMock(allowed=True)
        risk_engine.loss_streak_check.return_value = MagicMock(allowed=True)
        risk_engine.latency_ok.return_value = True

        state_manager = MagicMock()

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=None,
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
            execution_mode_fn=lambda: "MANUAL",
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()
        assert len(cycle.signals) == 1
        sig = cycle.signals[0]
        assert sig.name == "NIFTY"
        assert sig.risk.allowed is True
        assert sig.executed is False
        assert sig.execution_result is None

    def test_outside_hours(self) -> None:
        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = MagicMock(healthy=True, note="ok", frames={})
        strategy_engine = MagicMock()
        risk_engine = MagicMock()
        state_manager = MagicMock()

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=None,
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
            enforce_market_hours=True,
            market_hours_fn=lambda: False,
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()
        assert cycle.signals == []
        assert "outside NSE" in cycle.note

    def test_unhealthy_snapshot(self) -> None:
        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = MagicMock(healthy=False, note="data_issue", frames={})
        strategy_engine = MagicMock()
        risk_engine = MagicMock()
        state_manager = MagicMock()

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=None,
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()
        assert cycle.note == "data_issue"
        assert cycle.saved is True

    def test_safety_blocked(self) -> None:
        mock_snapshot = MagicMock(healthy=True, note="ok")
        mock_snapshot.frames = {"NIFTY": {"1m": "data"}}
        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = mock_snapshot

        strategy_engine = MagicMock()
        strategy_engine.generate_signal.return_value = {"score": 75, "direction": "CALL", "vol_ratio": 1.4}

        risk_engine = MagicMock()
        risk_engine.quality_check.return_value = MagicMock(allowed=True)
        risk_engine.loss_streak_check.return_value = MagicMock(allowed=True)
        risk_engine.latency_ok.return_value = True

        state_manager = MagicMock()
        safety_engine = MagicMock()
        safety_engine.evaluate.return_value = MagicMock(allowed=False, reason="vix too high")

        from core.safety_engine import SafetyContext
        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=None,
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
            safety_engine=safety_engine,
            safety_context_fn=lambda snapshot: SafetyContext(data_healthy=True),
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()
        assert len(cycle.signals) == 1
        assert cycle.signals[0].risk.allowed is False  # blocked by safety
        assert cycle.signals[0].safety.allowed is False

    def test_system_mode_blocked(self) -> None:
        mock_snapshot = MagicMock(healthy=True, note="ok")
        mock_snapshot.frames = {"NIFTY": {"1m": "data"}}

        risk_allowed = MagicMock(allowed=True)

        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = mock_snapshot

        strategy_engine = MagicMock()
        strategy_engine.generate_signal.return_value = {"score": 80, "vol_ratio": 1.5, "direction": "CALL"}

        risk_engine = MagicMock()
        risk_engine.quality_check.return_value = risk_allowed
        risk_engine.loss_streak_check.return_value = risk_allowed
        risk_engine.latency_ok.return_value = True

        state_manager = MagicMock()

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=MagicMock(),
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
            execution_mode_fn=lambda: "AUTO",
            entry_gate_fn=lambda name, sig: True,
            system_mode_fn=lambda: "BROKER_DOWN",
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()
        assert len(cycle.signals) == 1
        assert cycle.signals[0].risk.allowed is False
        assert "BROKER_DOWN" in cycle.signals[0].risk.reason

    def test_circuit_breaker_blocked(self) -> None:
        """Circuit breaker gate blocks execution when circuit_breaker_fn returns False."""
        mock_snapshot = MagicMock(healthy=True, note="ok")
        mock_snapshot.frames = {"NIFTY": {"1m": "data"}}

        risk_allowed = MagicMock(allowed=True)

        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = mock_snapshot

        strategy_engine = MagicMock()
        strategy_engine.generate_signal.return_value = {"score": 80, "vol_ratio": 1.5, "direction": "CALL"}

        risk_engine = MagicMock()
        risk_engine.quality_check.return_value = risk_allowed
        risk_engine.loss_streak_check.return_value = risk_allowed
        risk_engine.latency_ok.return_value = True

        state_manager = MagicMock()

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=MagicMock(),
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
            execution_mode_fn=lambda: "AUTO",
            entry_gate_fn=lambda name, sig: True,
            circuit_breaker_fn=lambda: False,
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()
        assert len(cycle.signals) == 1
        assert cycle.signals[0].risk.allowed is False
        assert "CIRCUIT_BREAKER_ACTIVE" in cycle.signals[0].risk.reason


# ═════════════════════════════════════════════════════════════════════════
# ExecutionService Integration Tests
# ═════════════════════════════════════════════════════════════════════════


class TestOrchestratorExecutionService:
    """Orchestrator with port-based ExecutionService path."""

    def test_execution_service_constructs(self) -> None:
        """Orchestrator accepts execution_service parameter."""
        from unittest.mock import MagicMock
        exec_svc = _make_mock_execution_service()
        orch = Orchestrator(
            data_engine=MagicMock(),
            strategy_engine=MagicMock(),
            risk_engine=MagicMock(),
            execution_service=exec_svc,
            state_manager=MagicMock(),
            names_provider=lambda: [],
        )
        assert orch._execution_service is exec_svc

    def test_execution_service_accepted(self) -> None:
        """Orchestrator accepts execution_service parameter."""
        from unittest.mock import MagicMock
        exec_svc = _make_mock_execution_service()
        orch = Orchestrator(
            data_engine=MagicMock(),
            strategy_engine=MagicMock(),
            risk_engine=MagicMock(),
            execution_service=exec_svc,
            state_manager=MagicMock(),
            names_provider=lambda: [],
        )
        assert orch._execution_service is exec_svc

    def test_run_cycle_with_execution_service(self) -> None:
        """Full cycle with ExecutionService executes orders via execute_order()."""
        from unittest.mock import MagicMock, patch

        mock_snapshot = MagicMock(healthy=True, note="ok")
        mock_snapshot.frames = {"NIFTY": {"1m": "data"}}
        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = mock_snapshot

        strategy_engine = MagicMock()
        strategy_engine.generate_signal.return_value = {
            "score": 80, "direction": "CALL", "vol_ratio": 1.5, "strategy_id": "test",
        }

        risk_engine = MagicMock()
        risk_allowed = MagicMock(allowed=True)
        risk_engine.quality_check.return_value = risk_allowed
        risk_engine.loss_streak_check.return_value = risk_allowed
        risk_engine.latency_ok.return_value = True

        state_manager = MagicMock()
        exec_svc = _make_mock_execution_service()

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=exec_svc,
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
            execution_mode_fn=lambda: "AUTO",
            entry_gate_fn=lambda name, sig: True,
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()

        assert len(cycle.signals) == 1
        sig = cycle.signals[0]
        assert sig.name == "NIFTY"
        assert sig.executed is True
        assert sig.execution_result is not None
        assert sig.execution_result.ok is True
        assert sig.execution_fill is not None
        assert sig.execution_fill.ok is True

    def test_run_cycle_execution_service_system_mode_block(self) -> None:
        """ExecutionService path respects system mode gate (BROKER_DOWN)."""
        from unittest.mock import MagicMock, patch

        mock_snapshot = MagicMock(healthy=True, note="ok")
        mock_snapshot.frames = {"NIFTY": {"1m": "data"}}
        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = mock_snapshot

        strategy_engine = MagicMock()
        strategy_engine.generate_signal.return_value = {"score": 80, "direction": "CALL", "vol_ratio": 1.5}

        risk_engine = MagicMock()
        risk_allowed = MagicMock(allowed=True)
        risk_engine.quality_check.return_value = risk_allowed
        risk_engine.loss_streak_check.return_value = risk_allowed
        risk_engine.latency_ok.return_value = True

        state_manager = MagicMock()
        exec_svc = _make_mock_execution_service()

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=exec_svc,
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
            execution_mode_fn=lambda: "AUTO",
            entry_gate_fn=lambda name, sig: True,
            system_mode_fn=lambda: "BROKER_DOWN",
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()

        assert len(cycle.signals) == 1
        sig = cycle.signals[0]
        assert sig.risk.allowed is False
        assert "BROKER_DOWN" in sig.risk.reason
        assert sig.executed is False  # ExecutionService not called

    def test_run_cycle_execution_service_circuit_breaker_block(self) -> None:
        """ExecutionService path respects circuit breaker gate."""
        from unittest.mock import MagicMock, patch

        mock_snapshot = MagicMock(healthy=True, note="ok")
        mock_snapshot.frames = {"NIFTY": {"1m": "data"}}
        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = mock_snapshot

        strategy_engine = MagicMock()
        strategy_engine.generate_signal.return_value = {"score": 80, "direction": "CALL", "vol_ratio": 1.5}

        risk_engine = MagicMock()
        risk_allowed = MagicMock(allowed=True)
        risk_engine.quality_check.return_value = risk_allowed
        risk_engine.loss_streak_check.return_value = risk_allowed
        risk_engine.latency_ok.return_value = True

        state_manager = MagicMock()
        exec_svc = _make_mock_execution_service()

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=exec_svc,
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
            execution_mode_fn=lambda: "AUTO",
            entry_gate_fn=lambda name, sig: True,
            circuit_breaker_fn=lambda: False,
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()

        assert len(cycle.signals) == 1
        sig = cycle.signals[0]
        assert sig.risk.allowed is False
        assert "CIRCUIT_BREAKER_ACTIVE" in sig.risk.reason
        assert sig.executed is False  # ExecutionService not called

    def test_execution_service_error_handling(self) -> None:
        """ExecutionService path handles errors gracefully."""
        from unittest.mock import MagicMock, patch

        mock_snapshot = MagicMock(healthy=True, note="ok")
        mock_snapshot.frames = {"NIFTY": {"1m": "data"}}
        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = mock_snapshot

        strategy_engine = MagicMock()
        strategy_engine.generate_signal.return_value = {"score": 80, "direction": "CALL", "vol_ratio": 1.5}

        risk_engine = MagicMock()
        risk_allowed = MagicMock(allowed=True)
        risk_engine.quality_check.return_value = risk_allowed
        risk_engine.loss_streak_check.return_value = risk_allowed
        risk_engine.latency_ok.return_value = True

        state_manager = MagicMock()

        # ExecutionService that raises an error
        exec_svc = MagicMock()
        exec_svc.execute_order.side_effect = ValueError("Broker connection lost")

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=exec_svc,
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
            execution_mode_fn=lambda: "AUTO",
            entry_gate_fn=lambda name, sig: True,
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()

        assert len(cycle.signals) == 1
        sig = cycle.signals[0]
        assert sig.executed is False
        assert sig.execution_result is not None
        assert sig.execution_result.ok is False
        assert "Broker connection lost" in sig.execution_result.reason

    def test_execution_service_no_executor(self) -> None:
        """Orchestrator handles missing execution_service.

        When ``execution_service`` is None,
        the outer execution gate condition fails and ``execution_result``
        remains None (no attempt to execute).
        """
        from unittest.mock import MagicMock, patch

        mock_snapshot = MagicMock(healthy=True, note="ok")
        mock_snapshot.frames = {"NIFTY": {"1m": "data"}}
        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = mock_snapshot

        strategy_engine = MagicMock()
        strategy_engine.generate_signal.return_value = {"score": 80, "direction": "CALL", "vol_ratio": 1.5}

        risk_engine = MagicMock()
        risk_allowed = MagicMock(allowed=True)
        risk_engine.quality_check.return_value = risk_allowed
        risk_engine.loss_streak_check.return_value = risk_allowed
        risk_engine.latency_ok.return_value = True

        state_manager = MagicMock()

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=None,
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
            execution_mode_fn=lambda: "AUTO",
            entry_gate_fn=lambda name, sig: True,
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()

        assert len(cycle.signals) == 1
        sig = cycle.signals[0]
        assert sig.executed is False
        assert sig.execution_result is None  # No executor, no attempt made

    def test_run_cycle_execution_service_rejected_order(self) -> None:
        """ExecutionService path handles rejected orders."""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        from core.ports.execution.execution_port import OrderResult, OrderStatus

        mock_snapshot = MagicMock(healthy=True, note="ok")
        mock_snapshot.frames = {"NIFTY": {"1m": "data"}}
        data_engine = MagicMock()
        data_engine.fetch_market_snapshot.return_value = mock_snapshot

        strategy_engine = MagicMock()
        strategy_engine.generate_signal.return_value = {"score": 80, "direction": "CALL", "vol_ratio": 1.5}

        risk_engine = MagicMock()
        risk_allowed = MagicMock(allowed=True)
        risk_engine.quality_check.return_value = risk_allowed
        risk_engine.loss_streak_check.return_value = risk_allowed
        risk_engine.latency_ok.return_value = True

        state_manager = MagicMock()

        # ExecutionService that returns a rejected order
        exec_svc = MagicMock()
        exec_svc.execute_order.return_value = OrderResult(
            order_id="",
            status=OrderStatus.REJECTED,
            reject_reason="Insufficient margin",
            timestamp=datetime.now(),
        )

        orch = Orchestrator(
            data_engine=data_engine,
            strategy_engine=strategy_engine,
            risk_engine=risk_engine,
            execution_service=exec_svc,
            state_manager=state_manager,
            names_provider=lambda: ["NIFTY"],
            execution_mode_fn=lambda: "AUTO",
            entry_gate_fn=lambda name, sig: True,
        )
        with patch("core.safety_state.check_kill_file_and_halt"):
            cycle = orch.run_cycle()

        assert len(cycle.signals) == 1
        sig = cycle.signals[0]
        assert sig.executed is False
        assert sig.execution_result is not None
        assert sig.execution_result.ok is False
        assert "Insufficient margin" in sig.execution_result.reason
