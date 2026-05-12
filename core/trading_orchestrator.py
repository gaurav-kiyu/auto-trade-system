"""
Orchestrator layer: maps normalized ``EXECUTION_MODE`` (manual / paper / auto / signals)
to execution routing while keeping signal generation independent.

Live wiring remains in ``index_app.index_trader``; this module is the small reusable bridge
for tools and future services.
"""

from __future__ import annotations

from typing import Any

from core.execution_engine import ExecutionEngine
from core.execution_stack import ExecutionRouter, TradingMode, trading_mode_from_cfg


def resolve_trading_mode(cfg: dict[str, Any], *, cli_paper: bool = False) -> TradingMode:
    return trading_mode_from_cfg(cfg, cli_paper=cli_paper)


def build_execution_router(
    cfg: dict[str, Any],
    *,
    cli_paper: bool = False,
    broker_engine: ExecutionEngine | None = None,
) -> ExecutionRouter:
    paper_via = bool(cfg.get("EXECUTION_ROUTER_PAPER_USES_ADAPTER", False))
    return ExecutionRouter(
        resolve_trading_mode(cfg, cli_paper=cli_paper),
        broker_engine=broker_engine,
        paper_routes_via_broker=paper_via,
    )
