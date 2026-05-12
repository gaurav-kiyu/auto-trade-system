"""
Execution layer entrypoint: paper simulation + broker router (see ``core.execution_stack``).
The low-level broker helper remains ``core.execution_engine.ExecutionEngine``.
"""

from __future__ import annotations

from core.execution_engine import ExecutionEngine, ExecutionFill, ExecutionResult
from core.execution_stack import (
    ExecutionRouter,
    PaperExecutionSimulator,
    PaperFill,
    TradingMode,
    trading_mode_from_cfg,
)
from core.trading_orchestrator import build_execution_router, resolve_trading_mode

__all__ = [
    "ExecutionEngine",
    "ExecutionFill",
    "ExecutionResult",
    "ExecutionRouter",
    "PaperExecutionSimulator",
    "PaperFill",
    "TradingMode",
    "trading_mode_from_cfg",
    "build_execution_router",
    "resolve_trading_mode",
]
