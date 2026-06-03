"""
Orchestrator layer: maps normalized ``EXECUTION_MODE`` (manual / paper / auto / signals)
to execution routing while keeping signal generation independent.

Live wiring remains in ``index_app.index_trader``; this module is the small reusable bridge
for tools and future services.

DEPRECATED: Use index_app.orchestrator_facade (build_clean_trading_orchestrator)
with core/services/use_cases/trading_orchestrator.py instead.
"""

from __future__ import annotations

import warnings
from typing import Any

from core.execution_stack import ExecutionRouter, TradingMode, trading_mode_from_cfg

warnings.warn(
    "DEPRECATED: core/trading_orchestrator.py is deprecated. "
    "Use index_app/orchestrator_facade.py (build_clean_trading_orchestrator) with "
    "core/services/use_cases/trading_orchestrator.py instead. "
    "This module will be removed in v2.55.",
    DeprecationWarning,
    stacklevel=2,
)


def resolve_trading_mode(cfg: dict[str, Any], *, cli_paper: bool = False) -> TradingMode:
    return trading_mode_from_cfg(cfg, cli_paper=cli_paper)


def build_execution_router(
    cfg: dict[str, Any],
    *,
    cli_paper: bool = False,
    broker_engine: Any = None,
) -> ExecutionRouter:
    paper_via = bool(cfg.get("EXECUTION_ROUTER_PAPER_USES_ADAPTER", False))
    return ExecutionRouter(
        resolve_trading_mode(cfg, cli_paper=cli_paper),
        broker_engine=broker_engine,
        paper_routes_via_broker=paper_via,
    )
