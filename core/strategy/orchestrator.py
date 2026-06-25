"""
AD-KIYU StrategyOrchestrator v2.0 - Single authoritative strategy orchestration path.

This module is the ONE entry point for signal generation, approval routing,
and strategy execution. All strategy/signal routing must pass through here.

Implements core.ports.strategy.StrategyPort interface.

Delegates to:
  - core.services.signal_orchestrator.SignalOrchestrator (signal generation pipeline)
  - core.signal_approval_workflow.SignalApprovalWorkflow (approval routing) - internal integration

Pipeline:
  1. generate_signal()  - run through signal generation pipeline
  2. route_decision()   - run through SignalApprovalWorkflow for approval routing
  3. evaluate()         - combined pipeline returning StrategyDecision

DEPRECATED (use StrategyOrchestrator instead):
  - core.signal_approval_workflow  - merged into orchestrator
  - core.strategy_engine           - backward compat shim only
  - core.signal_router             - removed
  - core.strategy_engine_v2        - removed
"""
from __future__ import annotations

import logging
from typing import Any

from core.datetime_ist import now_ist
from core.ports.strategy import StrategyDecision, StrategyPort

_log = logging.getLogger(__name__)


__all__ = [
    "StrategyOrchestrator",
]


class StrategyOrchestrator(StrategyPort):
    """
    Single authoritative strategy orchestrator.

    Routes signal generation and approval through one pipeline:
      1. Generate signal (via SignalOrchestrator or AdaptiveSignal)
      2. Run through SignalApprovalWorkflow for approval routing
      3. Return StrategyDecision with both signal and approval info

    No other signal routing path should exist.
    """

    def __init__(
        self,
        signal_orchestrator: Any = None,
        config: dict | None = None,
        approval_workflow: Any = None,
    ):
        self._signal_orchestrator = signal_orchestrator
        self._config = config or {}
        self._last_decision: StrategyDecision | None = None
        self._decision_history: list[StrategyDecision] = []
        self._max_history = 100

        # Internal SignalApprovalWorkflow integration
        if approval_workflow is not None:
            self._approval_workflow = approval_workflow
        else:
            # Lazy import to avoid circular deps
            self._approval_workflow = None
            if config:
                try:
                    from core.signal_approval_workflow import build_workflow
                    self._approval_workflow = build_workflow(config)
                except (ImportError, ValueError, TypeError):
                    self._approval_workflow = None

        _log.info("StrategyOrchestrator initialized (canonical strategy path)")

    def generate_signal(self, **kwargs: Any) -> dict[str, Any] | None:
        """
        Generate a signal from the underlying signal orchestrator.
        Returns raw signal dict, or None if no signal generated.
        """
        if self._signal_orchestrator is not None:
            try:
                signal_intent = self._signal_orchestrator.evaluate(**kwargs)
                if signal_intent is not None:
                    if isinstance(signal_intent, dict):
                        return signal_intent
                    # SignalIntent dataclass → dict
                    return {
                        "should_trade": getattr(signal_intent, "score", 0) > 0,
                        "direction": getattr(signal_intent, "direction", ""),
                        "score": float(getattr(signal_intent, "score", 0)),
                        "confidence": float(getattr(signal_intent, "confidence", 0.0)),
                        "reason": getattr(signal_intent, "rationale", ""),
                    }
            except (ImportError, ValueError, TypeError, AttributeError) as e:
                _log.error("Signal orchestrator evaluation failed: %s", e)
        return None

    def route_decision(
        self,
        signal_type: str = "AUTO",
        score: float = 0.0,
        tier: str = "",
        index_name: str = "",
        direction: str = "",
        reason: str = "",
    ) -> StrategyDecision:
        """
        Run a signal through the SignalApprovalWorkflow for approval routing.
        Returns a StrategyDecision with the approval action.
        """
        if self._approval_workflow is not None:
            try:
                sig_decision = self._approval_workflow.process_signal(
                    signal_type=signal_type,
                    score=int(score),
                    tier=tier,
                    index_name=index_name,
                    direction=direction,
                    reason=reason,
                )
                return StrategyDecision(
                    action="ENTER" if sig_decision.should_execute else (
                        "QUEUE" if sig_decision.should_queue else (
                            "NOTIFY" if sig_decision.should_notify else "SKIP"
                        )
                    ),
                    direction=direction,
                    score=score,
                    reason=sig_decision.reason,
                    approval_action=sig_decision.action,
                    approval_reason=sig_decision.reason,
                    queue_signal_id=sig_decision.queue_signal_id,
                )
            except (ImportError, ValueError, TypeError, AttributeError) as e:
                _log.error("Approval workflow routing failed: %s", e)
                return StrategyDecision(
                    action="HOLD",
                    reason=f"Approval routing error: {e}",
                )

        return StrategyDecision(
            action="HOLD",
            reason="No approval workflow configured",
        )

    def evaluate(self, **kwargs) -> StrategyDecision:
        """
        Full signal pipeline: generate + approve.
        This is the single entry point for all strategy evaluations.

        Accepts kwargs for generation, plus:
          signal_type, tier, index_name - for approval routing
        """
        # 1. Generate signal
        signal_intent = self.generate_signal(**kwargs)

        if signal_intent is None:
            return StrategyDecision(action="HOLD", reason="No signal generated")

        direction = signal_intent.get("direction", "")
        score = float(signal_intent.get("score", 0.0))
        confidence = float(signal_intent.get("confidence", 0.0))
        reason = signal_intent.get("reason", "")

        # 2. Run through approval workflow
        signal_type = kwargs.get("signal_type", "AUTO")
        tier = kwargs.get("tier", "")
        index_name = kwargs.get("index_name", "")

        decision = self.route_decision(
            signal_type=signal_type,
            score=score,
            tier=tier,
            index_name=index_name,
            direction=direction,
            reason=reason,
        )

        # Merge signal data into decision
        decision.signal_data = signal_intent
        decision.confidence = confidence
        decision.timestamp = now_ist()

        self._last_decision = decision
        self._decision_history.append(decision)
        if len(self._decision_history) > self._max_history:
            self._decision_history.pop(0)

        return decision

    def get_status(self) -> dict[str, Any]:
        return {
            "last_action": self._last_decision.action if self._last_decision else "NONE",
            "last_score": self._last_decision.score if self._last_decision else 0.0,
            "last_reason": self._last_decision.reason if self._last_decision else "",
            "last_approval": self._last_decision.approval_action if self._last_decision else "",
            "decision_count": len(self._decision_history),
            "has_signal_orchestrator": self._signal_orchestrator is not None,
            "has_approval_workflow": self._approval_workflow is not None,
        }

    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the strategy orchestration service.

        Returns:
            Dictionary containing health check results
        """
        return {
            "status": "healthy",
            "has_signal_orchestrator": self._signal_orchestrator is not None,
            "has_approval_workflow": self._approval_workflow is not None,
            "last_action": self._last_decision.action if self._last_decision else "NONE",
            "decision_count": len(self._decision_history),
        }
