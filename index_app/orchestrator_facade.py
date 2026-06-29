"""
Build a :class:`core.Orchestrator` wired to the live index bot engines.

The production main loop still uses the legacy path in :mod:`index_app.index_trader`;
this factory supports tests, tooling, and a gradual migration toward cycle-based flow.

Environment:

- ``OPB_ORCHESTRATOR_MARKET_HOURS`` - if ``0``/``false``/``no``/``off``, the orchestrator
  does not gate on NSE cash hours (useful for backtests and CI). Default: enforce IST session.
"""
from __future__ import annotations

import os
from typing import Any

__all__ = [
    "build_clean_trading_orchestrator",
    "build_index_orchestrator",
]

def build_index_orchestrator():
    """Return an :class:`~core.Orchestrator` after engines exist (post-``_init_runtime_engines()``)."""
    from core import Orchestrator, ReconciliationEngine

    import index_app.index_trader as m

    if m.DATA_ENGINE is None or m.STRATEGY_ENGINE is None or m.RISK_ENGINE is None:
        raise RuntimeError("Engines not initialized - call build_index_orchestrator() after _init_runtime_engines().")

    # Wrap RISK_ENGINE (RiskService instance) in backward-compatible adapter
    from core.risk.legacy_adapter import RiskPortAdapter
    risk_adapter = RiskPortAdapter(
        risk_service=m.RISK_ENGINE,
        min_volume_ratio=float(getattr(m, '_CFG', {}).get('MIN_VOLUME_RATIO', 0.0)),
        max_spread_pct=float(getattr(m, '_CFG', {}).get('MAX_SPREAD_PCT', 1.0)),
        max_consecutive_losses=int(getattr(m, '_CFG', {}).get('MAX_CONSECUTIVE_LOSSES', 3)),
    )

    recon = ReconciliationEngine(broker_snapshot_fn=m._broker_positions_snapshot)

    def _names() -> list[str]:
        return list(m.INDEX_PRIORITY)

    def _exec_mode() -> str:
        return m._execution_mode_label()

    def _entry_gate(_name: str, _signal: dict[str, Any]) -> bool:
        # Block entry if hard halt, intraday loss, or kill file detected
        from core.safety_state import check_intraday_pnl_and_halt, check_kill_file_and_halt, is_hard_halted
        check_kill_file_and_halt()
        if is_hard_halted():
            return False
        check_intraday_pnl_and_halt(source="orchestrator_entry_gate")
        return not is_hard_halted()

    def _system_mode() -> str:
        try:
            from core.system_mode import get_system_mode_manager
            mgr = get_system_mode_manager()
            return str(mgr.get_current_mode())
        except (ImportError, KeyError, RuntimeError):
            return "NORMAL"

    def _circuit_breaker_allows() -> bool:
        try:
            from core.circuit_breaker_detector import create_circuit_breaker_detector
            cb = create_circuit_breaker_detector()
            return cb.is_trading_allowed() if hasattr(cb, 'is_trading_allowed') else True
        except (ImportError, KeyError, RuntimeError):
            return True

    _mh = os.environ.get("OPB_ORCHESTRATOR_MARKET_HOURS", "1").strip().lower()
    enforce_ist = _mh not in ("0", "false", "no", "off")

    # Use the new ExecutionService path when the configured engine is an
    # ExecutionService instance (stored as EXECUTION_ENGINE for backward compat).
    # This ensures OrderRequest/OrderResult are used instead of legacy place_order().
    _exec_service = m.EXECUTION_ENGINE

    return Orchestrator(
        data_engine=m.DATA_ENGINE,
        strategy_engine=m.STRATEGY_ENGINE,
        risk_engine=risk_adapter,
        execution_service=_exec_service,
        state_manager=m.STATE_MANAGER,
        reconciliation_engine=recon,
        local_positions_fn=m._local_positions_snapshot,
        enforce_market_hours=enforce_ist,
        names_provider=_names,
        entry_gate_fn=_entry_gate,
        execution_mode_fn=_exec_mode,
        market_vix_fn=m.get_india_vix,
        audit_engine=getattr(m, "_AUDIT_ENGINE", None),
        system_mode_fn=_system_mode,
        circuit_breaker_fn=_circuit_breaker_allows,
    )


def build_clean_trading_orchestrator():
    """
    Build the clean-architecture :class:`~core.services.use_cases.trading_orchestrator.TradingOrchestrator`
    wired to the live index bot engines via DI container.

    Uses ``ExecutionService`` which explicitly implements ``ExecutionPort``,
    along with other domain ports resolved from the DI container.

    Returns:
        TradingOrchestrator instance, or None if DI container is not initialized.
    """
    try:
        from core.common.kernels.correlation_id import CorrelationIdManager
        from core.common.utilities.logging import StructuredLogger
        from core.common.utilities.metrics import MetricsCollector
        from core.di_container import get_container
        from core.ports.config import ConfigPort
        from core.ports.execution import ExecutionPort
        from core.ports.market_data import MarketDataPort
        from core.ports.ml_model import MlModelPort
        from core.ports.notification import NotificationPort
        from core.ports.persistence import PersistencePort
        from core.ports.risk import RiskPort
        from core.services.use_cases.trading_orchestrator import OrchestratorConfig, TradingOrchestrator

        container = get_container()

        # Resolve all required ports from DI container
        execution_port = container.resolve(ExecutionPort)
        config_port = container.resolve(ConfigPort)
        market_data_port = container.resolve(MarketDataPort)
        ml_model_port = container.resolve(MlModelPort)
        notification_port = container.resolve(NotificationPort)
        persistence_port = container.resolve(PersistencePort)
        risk_port = container.resolve(RiskPort)
        corr_id_mgr = container.resolve(CorrelationIdManager)
        metrics = container.resolve(MetricsCollector)
        logger = container.resolve(StructuredLogger)

        return TradingOrchestrator(
            market_data_port=market_data_port,
            ml_model_port=ml_model_port,
            risk_port=risk_port,
            execution_port=execution_port,
            persistence_port=persistence_port,
            notification_port=notification_port,
            config_port=config_port,
            correlation_id_manager=corr_id_mgr,
            metrics_collector=metrics,
            logger=logger,
        )
    except (ImportError, KeyError, Exception) as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Clean TradingOrchestrator not available: %s", exc
        )
        return None
