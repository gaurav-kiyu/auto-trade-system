"""Tests for core.orchestrator — legacy synchronous Orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.orchestrator import (
    Orchestrator,
    OrchestratorCycle,
    OrchestratorSignal,
    _ExecutionFill,
    _ExecutionResult,
)


# ── Execution dataclasses ────────────────────────────────────────────────

def test_execution_fill_default() -> None:
    fill = _ExecutionFill(ok=True)
    assert fill.ok is True
    assert fill.filled_qty == 0
    assert fill.fill_price is None
    assert fill.status_verified is False
    assert fill.reason == ""


def test_execution_fill_custom() -> None:
    fill = _ExecutionFill(ok=True, filled_qty=50, fill_price=23000.0, status_verified=True, reason="filled")
    assert fill.ok is True
    assert fill.filled_qty == 50
    assert fill.fill_price == 23000.0
    assert fill.status_verified is True


def test_execution_fill_frozen() -> None:
    fill = _ExecutionFill(ok=True)
    import pytest
    with pytest.raises(AttributeError):
        fill.ok = False  # type: ignore[misc]


def test_execution_result_default() -> None:
    result = _ExecutionResult(ok=False)
    assert result.ok is False
    assert result.order_id is None
    assert result.broker_latency_ms == 0


def test_execution_result_custom() -> None:
    result = _ExecutionResult(ok=True, order_id="ORD001", broker_latency_ms=150, reason="success")
    assert result.ok is True
    assert result.order_id == "ORD001"


# ── OrchestratorSignal ───────────────────────────────────────────────────

def test_orchestrator_signal_default() -> None:
    signal = OrchestratorSignal(name="NIFTY", signal={"score": 75}, risk=MagicMock())
    assert signal.name == "NIFTY"
    assert signal.signal["score"] == 75
    assert signal.executed is False
    assert signal.execution_result is None
    assert signal.execution_fill is None


# ── OrchestratorCycle ────────────────────────────────────────────────────

def test_orchestrator_cycle_default() -> None:
    cycle = OrchestratorCycle(snapshot=MagicMock(), signals=[], reconciliation=None, saved=True)
    assert cycle.saved is True
    assert cycle.signals == []
    assert cycle.note == ""


# ── Default order builder ───────────────────────────────────────────────

def test_default_order_builder() -> None:
    order = Orchestrator._default_order_builder("NIFTY", {"direction": "PUT", "qty": 2, "strike": 45000})
    assert order["name"] == "NIFTY"
    assert order["direction"] == "PUT"
    assert order["qty"] == 2
    assert order["strike"] == 45000


def test_default_order_builder_fallback() -> None:
    order = Orchestrator._default_order_builder("BANKNIFTY", {})
    assert order["name"] == "BANKNIFTY"
    assert order["direction"] == "CALL"
    assert order["qty"] == 1
    assert order["strike"] == 0


# ── Orchestrator construction ───────────────────────────────────────────

def test_orchestrator_construction() -> None:
    data_engine = MagicMock()
    strategy_engine = MagicMock()
    risk_engine = MagicMock()
    state_manager = MagicMock()
    orch = Orchestrator(
        data_engine=data_engine,
        strategy_engine=strategy_engine,
        risk_engine=risk_engine,
        execution_engine=None,
        state_manager=state_manager,
    )
    assert orch._data_engine is data_engine
    assert orch._execution_engine is None
    assert callable(orch._names_provider)
    assert callable(orch._entry_gate_fn)
    assert callable(orch._execution_mode_fn)
    assert orch._enforce_market_hours is False


# ── run_cycle with empty names ──────────────────────────────────────────

def test_run_cycle_empty_names() -> None:
    data_engine = MagicMock()
    data_engine.fetch_market_snapshot.return_value = MagicMock(healthy=True, note="ok", frames={})

    strategy_engine = MagicMock()
    risk_engine = MagicMock()
    state_manager = MagicMock()

    orch = Orchestrator(
        data_engine=data_engine,
        strategy_engine=strategy_engine,
        risk_engine=risk_engine,
        execution_engine=None,
        state_manager=state_manager,
        names_provider=lambda: [],
    )
    with patch("core.safety_state.check_kill_file_and_halt"):
        cycle = orch.run_cycle()
    assert isinstance(cycle, OrchestratorCycle)
    assert cycle.signals == []
    assert cycle.saved is True


# ── run_cycle with signal but MANUAL mode ───────────────────────────────

def test_run_cycle_manual_mode_no_execution() -> None:
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
        execution_engine=None,
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


# ── run_cycle outside market hours ──────────────────────────────────────

def test_run_cycle_outside_hours() -> None:
    data_engine = MagicMock()
    data_engine.fetch_market_snapshot.return_value = MagicMock(healthy=True, note="ok", frames={})
    strategy_engine = MagicMock()
    risk_engine = MagicMock()
    state_manager = MagicMock()

    orch = Orchestrator(
        data_engine=data_engine,
        strategy_engine=strategy_engine,
        risk_engine=risk_engine,
        execution_engine=None,
        state_manager=state_manager,
        names_provider=lambda: ["NIFTY"],
        enforce_market_hours=True,
        market_hours_fn=lambda: False,
    )
    with patch("core.safety_state.check_kill_file_and_halt"):
        cycle = orch.run_cycle()
    assert cycle.signals == []
    assert "outside NSE" in cycle.note


# ── run_cycle with unhealthy snapshot ───────────────────────────────────

def test_run_cycle_unhealthy_snapshot() -> None:
    data_engine = MagicMock()
    data_engine.fetch_market_snapshot.return_value = MagicMock(healthy=False, note="data_issue", frames={})
    strategy_engine = MagicMock()
    risk_engine = MagicMock()
    state_manager = MagicMock()

    orch = Orchestrator(
        data_engine=data_engine,
        strategy_engine=strategy_engine,
        risk_engine=risk_engine,
        execution_engine=None,
        state_manager=state_manager,
        names_provider=lambda: ["NIFTY"],
    )
    with patch("core.safety_state.check_kill_file_and_halt"):
        cycle = orch.run_cycle()
    assert cycle.note == "data_issue"
    assert cycle.saved is True


# ── run_cycle with safety engine block ──────────────────────────────────

def test_run_cycle_safety_blocked_signal() -> None:
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
        execution_engine=None,
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


# ── run_cycle with system_mode block ────────────────────────────────────

def test_run_cycle_system_mode_blocked() -> None:
    mock_snapshot = MagicMock(healthy=True, note="ok")
    mock_snapshot.frames = {"NIFTY": {"1m": "data"}}

    mock_exec = MagicMock()
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
        execution_engine=mock_exec,
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
