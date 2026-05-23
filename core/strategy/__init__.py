"""
AD-KIYU Strategy Package.

Single canonical strategy orchestration path.
All strategy/signal routing must pass through StrategyOrchestrator.

Exports:
    StrategyOrchestrator — single entry point for strategy evaluation
    StrategyDecision    — result dataclass (from core.ports.strategy)

Legacy modules (use StrategyOrchestrator instead):
    - core.signal_approval_workflow — deprecated, use StrategyOrchestrator
    - core.strategy_engine          — deprecated, use StrategyOrchestrator
"""
from __future__ import annotations

from core.ports.strategy import StrategyDecision
from core.strategy.orchestrator import StrategyOrchestrator

__all__ = [
    "StrategyDecision",
    "StrategyOrchestrator",
]
