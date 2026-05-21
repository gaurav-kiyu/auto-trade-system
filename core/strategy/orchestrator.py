"""
AD-KIYU StrategyOrchestrator v1.0 — Single authoritative strategy orchestration path.

This module is the ONE entry point for signal generation and strategy execution.
All strategy/signal routing must pass through here.

Delegates to:
  - core.services.signal_orchestrator.SignalOrchestrator (production signal pipeline)
  - core.adaptive_signal.AdaptiveSignal (signal scoring pipeline)

DEPRECATED (removed):
  - core/signal_router.py
  - core/signal_approval_workflow.py
  - core/strategy_engine.py
  - core/strategy_engine_v2.py
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)


@dataclass
class StrategyDecision:
    """Result of a strategy evaluation."""
    action: str = "NONE"          # ENTER, EXIT, HOLD, CANCEL
    direction: str = ""           # CALL, PUT, or empty
    score: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    timestamp: datetime = field(default_factory=now_ist)
    signal_data: dict[str, Any] = field(default_factory=dict)


class StrategyOrchestrator:
    """
    Single authoritative strategy orchestrator.

    Routes signal generation through one pipeline:
      1. Receive signal request (from scheduler, manual, or webhook)
      2. Run through signal pipeline (AdaptiveSignal → PureIndexSignal)
      3. Gate through operating mode
      4. Return StrategyDecision

    No other signal routing path should exist.
    """

    def __init__(self, signal_orchestrator: Any = None, config: dict | None = None):
        self._signal_orchestrator = signal_orchestrator
        self._config = config or {}
        self._last_decision: StrategyDecision | None = None
        self._decision_history: list[StrategyDecision] = []
        self._max_history = 100
        _log.info("StrategyOrchestrator initialized (canonical strategy path)")

    def evaluate(self, **kwargs) -> StrategyDecision:
        """
        Evaluate a signal and return a strategy decision.
        This is the single entry point for all strategy evaluations.
        """
        if self._signal_orchestrator is not None:
            try:
                signal_intent = self._signal_orchestrator.evaluate(**kwargs)
                if signal_intent is not None:
                    decision = StrategyDecision(
                        action="ENTER" if signal_intent.get("should_trade") else "HOLD",
                        direction=signal_intent.get("direction", ""),
                        score=signal_intent.get("score", 0.0),
                        confidence=signal_intent.get("confidence", 0.0),
                        reason=signal_intent.get("reason", ""),
                        signal_data=signal_intent,
                    )
                    self._last_decision = decision
                    self._decision_history.append(decision)
                    if len(self._decision_history) > self._max_history:
                        self._decision_history.pop(0)
                    return decision
            except Exception as e:
                _log.error("Signal orchestrator evaluation failed: %s", e)

        return StrategyDecision(action="HOLD", reason="No signal orchestrator available")

    def get_status(self) -> dict:
        return {
            "last_action": self._last_decision.action if self._last_decision else "NONE",
            "last_score": self._last_decision.score if self._last_decision else 0.0,
            "last_reason": self._last_decision.reason if self._last_decision else "",
            "decision_count": len(self._decision_history),
        }
