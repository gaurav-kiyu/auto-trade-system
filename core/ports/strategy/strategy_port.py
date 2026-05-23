"""
Strategy Port Interface

This interface defines the contract that all strategy orchestration implementations
must implement. It provides a unified way to evaluate trading signals, route approval
decisions, and obtain strategy status.

All strategy/signal routing must pass through this port.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.datetime_ist import now_ist


@dataclass
class StrategyDecision:
    """Result of a strategy evaluation, including approval routing."""
    action: str = "NONE"          # ENTER, EXIT, HOLD, CANCEL, QUEUE, NOTIFY_ONLY, SKIP
    direction: str = ""           # CALL, PUT, or empty
    score: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    timestamp: datetime = field(default_factory=now_ist)
    signal_data: dict[str, Any] = field(default_factory=dict)
    approval_action: str = ""      # EXECUTE, QUEUE, NOTIFY_ONLY, SKIP (from approval workflow)
    approval_reason: str = ""
    queue_signal_id: str | None = None  # set when action=QUEUE


class StrategyPort(ABC):
    """
    Abstract base class for strategy orchestration services.

    All strategy implementations must inherit from this class
    and implement the required methods.
    """

    @abstractmethod
    def evaluate(self, **kwargs: Any) -> StrategyDecision:
        """
        Full signal pipeline: generate + approve.
        This is the single entry point for all strategy evaluations.

        Args:
            **kwargs: Signal generation parameters plus:
                signal_type (str): AUTO, MANUAL, etc.
                tier (str): Signal tier
                index_name (str): Target index

        Returns:
            StrategyDecision with combined signal and approval info
        """
        pass

    @abstractmethod
    def generate_signal(self, **kwargs: Any) -> dict[str, Any] | None:
        """
        Generate a signal from the underlying signal orchestrator.

        Args:
            **kwargs: Parameters for signal generation

        Returns:
            Raw signal dict, or None if no signal generated
        """
        pass

    @abstractmethod
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
        Run a signal through the approval workflow for routing.

        Args:
            signal_type: Type of signal (AUTO, MANUAL, etc.)
            score: Signal score
            tier: Signal tier
            index_name: Target index
            direction: Trade direction (CALL/PUT)
            reason: Signal reason/rationale

        Returns:
            StrategyDecision with approval routing result
        """
        pass

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        """
        Get current strategy orchestration status.

        Returns:
            Dictionary with last action, score, reason, decision count, etc.
        """
        pass

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the strategy orchestration service.

        Returns:
            Dictionary containing health check results
        """
        pass
