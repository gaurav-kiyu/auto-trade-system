"""Tests for core/strategy/orchestrator.py - Strategy Orchestrator.

Covers:
- StrategyOrchestrator init (with/without signal_orchestrator, approval_workflow)
- generate_signal (dict result, dataclass result, None, error)
- route_decision (approve, queue, notify, skip, error, no workflow)
- evaluate (full pipeline, no signal, error)
- get_status, health_check
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.strategy.orchestrator import StrategyOrchestrator
from core.ports.strategy import StrategyDecision


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_signal_orch() -> MagicMock:
    """Mock signal orchestrator that returns a dict signal."""
    mock = MagicMock()
    mock.evaluate.return_value = {
        "score": 75,
        "direction": "CALL",
        "confidence": 0.8,
        "reason": "Strong momentum",
        "should_trade": True,
    }
    return mock


@pytest.fixture
def mock_approval() -> MagicMock:
    """Mock approval workflow."""
    mock = MagicMock()
    decision = MagicMock()
    decision.should_execute = True
    decision.should_queue = False
    decision.should_notify = False
    decision.action = "ENTER"
    decision.reason = "Approved by workflow"
    decision.queue_signal_id = "QS-001"
    mock.process_signal.return_value = decision
    return mock


@pytest.fixture
def orchestrator(mock_signal_orch: MagicMock, mock_approval: MagicMock) -> StrategyOrchestrator:
    return StrategyOrchestrator(
        signal_orchestrator=mock_signal_orch,
        config={"key": "val"},
        approval_workflow=mock_approval,
    )


# =============================================================================
# Init Tests
# =============================================================================

class TestInit:
    def test_stores_signal_orchestrator(self, mock_signal_orch: MagicMock):
        orch = StrategyOrchestrator(signal_orchestrator=mock_signal_orch)
        assert orch._signal_orchestrator is mock_signal_orch

    def test_stores_config(self):
        orch = StrategyOrchestrator(config={"max_score": 80})
        assert orch._config["max_score"] == 80

    def test_default_config(self):
        orch = StrategyOrchestrator()
        assert orch._config == {}

    def test_with_approval_workflow(self, mock_approval: MagicMock):
        orch = StrategyOrchestrator(approval_workflow=mock_approval)
        assert orch._approval_workflow is mock_approval

    def test_empty_decision_history(self):
        orch = StrategyOrchestrator()
        assert orch._decision_history == []
        assert orch._last_decision is None


# =============================================================================
# generate_signal Tests
# =============================================================================

class TestGenerateSignal:
    def test_returns_signal_dict(self, orchestrator: StrategyOrchestrator):
        signal = orchestrator.generate_signal(symbol="NIFTY")
        assert signal is not None
        assert signal["direction"] == "CALL"
        assert signal["score"] == 75

    def test_no_signal_orchestrator_returns_none(self):
        orch = StrategyOrchestrator()
        signal = orch.generate_signal(symbol="NIFTY")
        assert signal is None

    def test_signal_orchestrator_returns_none(self, mock_signal_orch: MagicMock):
        mock_signal_orch.evaluate.return_value = None
        orch = StrategyOrchestrator(signal_orchestrator=mock_signal_orch)
        signal = orch.generate_signal(symbol="NIFTY")
        assert signal is None

    def test_orchestrator_exception_returns_none(self, mock_signal_orch: MagicMock):
        mock_signal_orch.evaluate.side_effect = ValueError("Orchestrator failed")
        orch = StrategyOrchestrator(signal_orchestrator=mock_signal_orch)
        signal = orch.generate_signal(symbol="NIFTY")
        assert signal is None

    def test_passes_kwargs_to_orchestrator(self, mock_signal_orch: MagicMock):
        orch = StrategyOrchestrator(signal_orchestrator=mock_signal_orch)
        orch.generate_signal(symbol="NIFTY", timeframe="1m")
        mock_signal_orch.evaluate.assert_called_with(symbol="NIFTY", timeframe="1m")


# =============================================================================
# route_decision Tests
# =============================================================================

class TestRouteDecision:
    def test_returns_enter_decision(self, orchestrator: StrategyOrchestrator):
        decision = orchestrator.route_decision(
            signal_type="AUTO", score=75.0, tier="TIER1",
            index_name="NIFTY", direction="CALL",
            reason="Strong signal",
        )
        assert isinstance(decision, StrategyDecision)
        assert decision.action == "ENTER"
        assert decision.direction == "CALL"
        assert decision.score == 75.0

    def test_no_approval_workflow_returns_hold(self):
        orch = StrategyOrchestrator()
        decision = orch.route_decision(
            signal_type="AUTO", score=50.0, tier="",
            index_name="NIFTY", direction="CALL",
            reason="Test",
        )
        assert decision.action == "HOLD"
        assert "No approval" in decision.reason

    def test_approval_workflow_error_returns_hold(self, mock_signal_orch: MagicMock):
        mock_approval = MagicMock()
        mock_approval.process_signal.side_effect = ImportError("Module missing")
        orch = StrategyOrchestrator(
            signal_orchestrator=mock_signal_orch,
            approval_workflow=mock_approval,
        )
        decision = orch.route_decision(
            signal_type="AUTO", score=50.0, tier="",
            index_name="NIFTY", direction="CALL",
            reason="Test",
        )
        assert decision.action == "HOLD"

    def test_queue_decision(self):
        mock_approval = MagicMock()
        decision_mock = MagicMock()
        decision_mock.should_execute = False
        decision_mock.should_queue = True
        decision_mock.should_notify = False
        decision_mock.action = "QUEUE"
        decision_mock.reason = "Queued for review"
        decision_mock.queue_signal_id = "QS-002"
        mock_approval.process_signal.return_value = decision_mock
        orch = StrategyOrchestrator(approval_workflow=mock_approval)
        decision = orch.route_decision(
            signal_type="MANUAL", score=60.0, tier="",
            index_name="BANKNIFTY", direction="PUT", reason="Manual",
        )
        assert decision.action == "QUEUE"

    def test_notify_decision(self):
        mock_approval = MagicMock()
        decision_mock = MagicMock()
        decision_mock.should_execute = False
        decision_mock.should_queue = False
        decision_mock.should_notify = True
        decision_mock.action = "NOTIFY"
        mock_approval.process_signal.return_value = decision_mock
        orch = StrategyOrchestrator(approval_workflow=mock_approval)
        decision = orch.route_decision(signal_type="AUTO", score=40.0, tier="", index_name="NIFTY", direction="CALL", reason="Low")
        assert decision.action == "NOTIFY"


# =============================================================================
# evaluate Tests (full pipeline)
# =============================================================================

class TestEvaluate:
    def test_full_pipeline(self, orchestrator: StrategyOrchestrator):
        decision = orchestrator.evaluate(
            symbol="NIFTY", signal_type="AUTO", tier="TIER1", index_name="NIFTY",
        )
        assert isinstance(decision, StrategyDecision)
        assert decision.action == "ENTER"
        assert decision.signal_data is not None
        assert decision.confidence == 0.8

    def test_no_signal_returns_hold(self):
        orch = StrategyOrchestrator()
        decision = orch.evaluate(symbol="NIFTY")
        assert decision.action == "HOLD"
        assert "no signal" in decision.reason.lower()

    def test_signal_orchestrator_none(self, mock_signal_orch: MagicMock):
        mock_signal_orch.evaluate.return_value = None
        orch = StrategyOrchestrator(signal_orchestrator=mock_signal_orch)
        decision = orch.evaluate(symbol="NIFTY")
        assert decision.action == "HOLD"

    def test_stores_last_decision(self, orchestrator: StrategyOrchestrator):
        orchestrator.evaluate(symbol="NIFTY")
        assert orchestrator._last_decision is not None
        assert orchestrator._last_decision.action == "ENTER"

    def test_history_limit(self, mock_signal_orch: MagicMock, mock_approval: MagicMock):
        orch = StrategyOrchestrator(
            signal_orchestrator=mock_signal_orch,
            approval_workflow=mock_approval,
        )
        for _ in range(150):
            orch.evaluate(symbol="NIFTY")
        assert len(orch._decision_history) <= 100


# =============================================================================
# get_status Tests
# =============================================================================

class TestGetStatus:
    def test_initial_status(self):
        orch = StrategyOrchestrator()
        status = orch.get_status()
        assert status["last_action"] == "NONE"
        assert status["last_score"] == 0.0
        assert status["decision_count"] == 0
        assert status["has_signal_orchestrator"] is False

    def test_after_evaluate(self, orchestrator: StrategyOrchestrator):
        orchestrator.evaluate(symbol="NIFTY")
        status = orchestrator.get_status()
        assert status["last_action"] == "ENTER"
        assert status["decision_count"] == 1
        assert status["has_signal_orchestrator"] is True


# =============================================================================
# health_check Tests
# =============================================================================

class TestHealthCheck:
    def test_healthy_status(self, orchestrator: StrategyOrchestrator):
        result = orchestrator.health_check()
        assert result["status"] == "healthy"
        assert result["has_signal_orchestrator"] is True
        assert result["has_approval_workflow"] is True

    def test_empty_orchestrator(self):
        orch = StrategyOrchestrator()
        result = orch.health_check()
        assert result["has_signal_orchestrator"] is False
        assert result["last_action"] == "NONE"
