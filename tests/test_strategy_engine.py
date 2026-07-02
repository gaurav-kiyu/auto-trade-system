"""Tests for StrategyOrchestrator (core.strategy.orchestrator)."""

from __future__ import annotations


# ═════════════════════════════════════════════════════════════════════════
# StrategyOrchestrator Tests (v2.54 — modern replacement)
# ═════════════════════════════════════════════════════════════════════════


class TestStrategyOrchestrator:
    """Tests for StrategyOrchestrator (core.strategy.orchestrator)."""

    def test_init_default(self) -> None:
        """Default constructor creates working instance with no signal source."""
        from core.strategy.orchestrator import StrategyOrchestrator
        orch = StrategyOrchestrator()
        assert orch._signal_orchestrator is None
        assert orch._config == {}
        status = orch.get_status()
        assert status["has_signal_orchestrator"] is False
        assert status["last_action"] == "NONE"

    def test_init_with_config(self) -> None:
        """Constructor accepts config dict."""
        from core.strategy.orchestrator import StrategyOrchestrator
        orch = StrategyOrchestrator(config={"key": "value"})
        assert orch._config == {"key": "value"}

    def test_generate_signal_no_orchestrator_returns_none(self) -> None:
        """Without a signal_orchestrator, generate_signal returns None."""
        from core.strategy.orchestrator import StrategyOrchestrator
        orch = StrategyOrchestrator()
        result = orch.generate_signal(symbol="NIFTY")
        assert result is None

    def test_generate_signal_with_mock_orchestrator(self) -> None:
        """With a mock signal_orchestrator, generate_signal returns a signal dict."""
        from unittest.mock import MagicMock
        from core.strategy.orchestrator import StrategyOrchestrator

        mock_sig = MagicMock()
        mock_sig.evaluate.return_value = type("Intent", (), {
            "score": 85, "direction": "CALL", "confidence": 0.75, "rationale": "Test"
        })

        orch = StrategyOrchestrator(signal_orchestrator=mock_sig)
        result = orch.generate_signal(symbol="NIFTY")
        assert result is not None
        assert result["direction"] == "CALL"
        assert result["score"] == 85.0
        assert result["confidence"] == 0.75
        mock_sig.evaluate.assert_called_once_with(symbol="NIFTY")

    def test_generate_signal_with_mock_returns_dict_directly(self) -> None:
        """If the mock returns a dict directly, generate_signal passes it through."""
        from unittest.mock import MagicMock
        from core.strategy.orchestrator import StrategyOrchestrator

        mock_sig = MagicMock()
        mock_sig.evaluate.return_value = {
            "direction": "PUT", "score": 60, "confidence": 0.5, "reason": "Test direct"
        }

        orch = StrategyOrchestrator(signal_orchestrator=mock_sig)
        result = orch.generate_signal(symbol="BANKNIFTY")
        assert result is not None
        assert result["direction"] == "PUT"
        assert result["score"] == 60

    def test_route_decision_no_workflow_returns_hold(self) -> None:
        """Without an approval workflow, route_decision returns HOLD."""
        from core.strategy.orchestrator import StrategyOrchestrator
        orch = StrategyOrchestrator()
        decision = orch.route_decision(
            signal_type="AUTO", score=80, tier="STRONG",
            index_name="NIFTY", direction="CALL", reason="Test"
        )
        assert decision.action == "HOLD"
        assert "No approval workflow configured" in decision.reason

    def test_evaluate_no_orchestrator_returns_hold(self) -> None:
        """Without a signal orchestrator, evaluate returns HOLD."""
        from core.strategy.orchestrator import StrategyOrchestrator
        orch = StrategyOrchestrator()
        decision = orch.evaluate(symbol="NIFTY")
        assert decision.action == "HOLD"
        assert "No signal generated" in decision.reason

    def test_evaluate_with_mock_full_pipeline(self) -> None:
        """Full evaluate pipeline with mock signal orchestrator generates a decision.

        Note: Without an approval workflow, route_decision returns a fresh
        StrategyDecision(action='HOLD') without propagating score/direction.
        The original signal data is preserved in decision.signal_data and
        decision.confidence is set by evaluate().
        """
        from unittest.mock import MagicMock
        from core.strategy.orchestrator import StrategyOrchestrator

        mock_sig = MagicMock()
        mock_sig.evaluate.return_value = {
            "direction": "CALL", "score": 85, "confidence": 0.8, "reason": "Strong signal"
        }

        orch = StrategyOrchestrator(signal_orchestrator=mock_sig)
        decision = orch.evaluate(symbol="NIFTY")
        # Without approval workflow: route_decision returns HOLD
        assert decision.action == "HOLD"
        # score defaults to 0.0 because route_decision creates fresh decision
        # (score is passed to route_decision but not forwarded on HOLD path)
        assert decision.score == 0.0
        # confidence IS set by evaluate() after route_decision returns
        assert decision.confidence == 0.8
        # signal_data carries the full original signal
        assert decision.signal_data is not None
        assert decision.signal_data["direction"] == "CALL"
        assert decision.signal_data["score"] == 85

    def test_get_status_structure(self) -> None:
        """get_status returns the expected structure."""
        from unittest.mock import MagicMock
        from core.strategy.orchestrator import StrategyOrchestrator

        mock_sig = MagicMock()
        orch = StrategyOrchestrator(signal_orchestrator=mock_sig)
        status = orch.get_status()

        assert "last_action" in status
        assert "last_score" in status
        assert "last_reason" in status
        assert "has_signal_orchestrator" in status
        assert "has_approval_workflow" in status
        assert "decision_count" in status
        assert status["has_signal_orchestrator"] is True
        assert status["last_action"] == "NONE"
        assert status["decision_count"] == 0

    def test_health_check_structure(self) -> None:
        """health_check returns the expected structure."""
        from core.strategy.orchestrator import StrategyOrchestrator
        orch = StrategyOrchestrator()
        health = orch.health_check()

        assert health["status"] == "healthy"
        assert "has_signal_orchestrator" in health
        assert "has_approval_workflow" in health
        assert "last_action" in health
        assert "decision_count" in health

    def test_decision_history_tracking(self) -> None:
        """Multiple evaluate calls accumulate in decision history."""
        from unittest.mock import MagicMock
        from core.strategy.orchestrator import StrategyOrchestrator

        mock_sig = MagicMock()
        mock_sig.evaluate.return_value = {
            "direction": "CALL", "score": 80, "confidence": 0.7, "reason": "Test"
        }

        orch = StrategyOrchestrator(signal_orchestrator=mock_sig)
        orch.evaluate(symbol="NIFTY")
        orch.evaluate(symbol="NIFTY")

        assert len(orch._decision_history) == 2
        status = orch.get_status()
        assert status["decision_count"] == 2
        assert status["last_action"] == "HOLD"
