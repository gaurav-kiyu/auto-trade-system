"""
Build a :class:`core.Orchestrator` wired to the live index bot engines.

The production main loop still uses the legacy path in :mod:`index_app.index_trader`;
this factory supports tests, tooling, and a gradual migration toward cycle-based flow.

Environment:

- ``OPB_ORCHESTRATOR_MARKET_HOURS`` - if ``0``/``false``/``no``/``off``, the orchestrator
  does not gate on NSE cash hours (useful for backtests and CI). Default: enforce IST session.
"""
from __future__ import annotations

__all__ = [
    "build_clean_trading_orchestrator",
    "build_index_orchestrator",
]

def build_index_orchestrator():
    """Build an orchestrator wired to the live index bot engines.

    Deprecated: Use :func:`build_clean_trading_orchestrator` instead,
    which returns a :class:`~core.services.use_cases.trading_orchestrator.TradingOrchestrator`
    wired via the DI container.

    The old ``core.Orchestrator`` backward-compat wrapper was removed in v2.54.
    This function now delegates to ``build_clean_trading_orchestrator()``.

    Returns:
        TradingOrchestrator instance, or None if DI container is not initialized.
    """
    import logging
    _log = logging.getLogger(__name__)
    _log.warning(
        "build_index_orchestrator() is deprecated (core.Orchestrator removed in v2.54). "
        "Use build_clean_trading_orchestrator() instead."
    )
    return build_clean_trading_orchestrator()


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
        from core.services.use_cases.trading_orchestrator import TradingOrchestrator

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
