"""
Dependency Injection Container
Provides a simple inversion of control container for managing service lifetimes
and resolving interfaces to concrete implementations.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar('T')


class DIContainer:
    """
    A simple dependency injection container supporting:
    - Registering interfaces (or abstract classes) to concrete implementations
    - Singleton and transient lifetimes
    - Factory functions for complex creation logic
    """

    def __init__(self):
        self._singletons: dict[type, type] = {}  # Maps interface to implementation class
        self._singleton_instances: dict[type, Any] = {}  # Maps interface to singleton instance
        self._factories: dict[type, Callable[[], Any]] = {}
        self._transients: dict[type, type] = {}
        self._lock = threading.RLock()

    def register_singleton(self, interface: type[T], implementation: type[T]) -> None:
        """
        Register a implementation as a singleton for the given interface.
        The same instance will be returned for every resolution.
        """
        with self._lock:
            self._singletons[interface] = implementation
            # Initialize singleton instance as None (will be created on first resolve)
            if interface not in self._singleton_instances:
                self._singleton_instances[interface] = None

    def register_transient(self, interface: type[T], implementation: type[T]) -> None:
        """
        Register a implementation as transient for the given interface.
        A new instance will be created for every resolution.
        """
        with self._lock:
            self._transients[interface] = implementation

    def register_instance(self, interface: type[T], instance: T) -> None:
        """
        Register an already-created instance as a singleton for the given interface.
        The same instance will be returned for every resolution.
        This is useful when the instance requires complex construction logic.
        """
        with self._lock:
            self._singletons[interface] = type(instance)
            self._singleton_instances[interface] = instance

    def register_factory(self, interface: type[T], factory: Callable[[], T]) -> None:
        """
        Register a factory function for the given interface.
        The factory will be called every time the interface is resolved.
        """
        with self._lock:
            self._factories[interface] = factory

    def resolve(self, interface: type[T]) -> T:
        """
        Resolve an instance of the given interface.
        Raises KeyError if no registration is found.
        """
        with self._lock:
            # Check for factory first
            if interface in self._factories:
                return self._factories[interface]()

            # Check for singleton
            if interface in self._singletons:
                if interface not in self._singleton_instances or self._singleton_instances[interface] is None:
                    # Create and cache the singleton instance
                    instance = self._singletons[interface]()
                    self._singleton_instances[interface] = instance
                return self._singleton_instances[interface]

            # Check for transient
            if interface in self._transients:
                implementation = self._transients[interface]
                return implementation()

            raise KeyError(f"No registration found for interface {interface}")

    def try_resolve(self, interface: type[T]) -> T | None:
        """
        Try to resolve an instance of the given interface.
        Returns None if no registration is found.
        """
        try:
            return self.resolve(interface)
        except KeyError:
            return None

    def is_registered(self, interface: type[T]) -> bool:
        """Check if the interface is registered in the container."""
        with self._lock:
            return (interface in self._factories or
                    interface in self._singletons or
                    interface in self._transients)

    def clear(self) -> None:
        """Clear all registrations. Primarily useful for testing."""
        with self._lock:
            self._singletons.clear()
            self._factories.clear()
            self._transients.clear()



# ── Convenience factory for default wiring ────────────────────────────────


def _register_multi_asset_adapters(container_instance: DIContainer) -> None:
    """Register multi-asset market data adapters.

    Delegates to the app-layer factory to maintain ADR-0010 compliance
    (no core/ -> infrastructure/ imports).
    """
    try:
        from index_app.domains.market.adapter_factory import register_multi_asset_adapters as _real_register
        _real_register(container_instance)
    except ImportError:
        pass  # App layer not available - adapters will not be registered


def wire_default_services(container_instance: DIContainer | None = None) -> DIContainer:
    """Register default service implementations into the container.

    This wires the standard port-to-implementation mappings so callers
    can resolve interfaces without manual setup.  Safe to call multiple
    times (idempotent via is_registered checks).
    """
    c = container_instance or container

    # Capital Allocation (multi-asset)
    try:
        from core.portfolio.adapters.multi_asset_aggregator import CapitalAllocationService
        from core.ports.capital_allocation import CapitalAllocationPort
        if not c.is_registered(CapitalAllocationPort):
            c.register_singleton(CapitalAllocationPort, CapitalAllocationService)
    except ImportError:
        pass  # Optional dependency - container works without it

    # Multi-Asset Portfolio Aggregator (wired with CapitalAllocationPort from container if available)
    try:
        from core.portfolio.adapters.multi_asset_aggregator import MultiAssetPortfolioAggregator
        if not c.is_registered(MultiAssetPortfolioAggregator):
            # Use factory to resolve CapitalAllocationPort from container
            def _make_aggregator():
                cap_alloc = c.try_resolve(CapitalAllocationPort) if hasattr(c, 'try_resolve') else None
                return MultiAssetPortfolioAggregator(capital_allocation=cap_alloc)
            c.register_factory(MultiAssetPortfolioAggregator, _make_aggregator)
    except ImportError:
        pass

    # Market Data Adapters (multi-asset) - deferred registration
    # These are registered in index_app/domains/trading/container.py (app layer)
    # to avoid core/ -> infrastructure/ import violations (ADR-0010)
    _register_multi_asset_adapters(c)

    # Market Data Service - multi-adapter aggregator
    try:
        from core.services.market_data_service import MarketDataService
        if not c.is_registered(MarketDataService):
            c.register_singleton(MarketDataService, MarketDataService)
    except ImportError:
        pass

    # ConfigManager — register via factory so it's lazily resolved from
    # the module-level _cfg_manager set by index_trader._load_config()
    try:
        from index_app.domains.config.manager import ConfigManager as _ConfigManager
        if not c.is_registered(_ConfigManager):
            c.register_factory(_ConfigManager, _resolve_config_manager)
    except ImportError:
        pass

    # Portfolio Optimizer
    try:
        from core.portfolio.optimizer import PortfolioOptimizer
        if not c.is_registered(PortfolioOptimizer):
            c.register_singleton(PortfolioOptimizer, PortfolioOptimizer)
    except ImportError:
        pass

    # Self-Healing Orchestrator — uses factory to resolve CircuitBreakerService from container
    try:
        from core.self_healing.orchestrator import SelfHealingOrchestrator
        if not c.is_registered(SelfHealingOrchestrator):
            from core.health_checker import run_full_health_check
            def _make_healing():
                from core.services.circuit_breaker_service import CircuitBreakerService
                cb = c.try_resolve(CircuitBreakerService)
                if cb is None:
                    cb = CircuitBreakerService()
                return SelfHealingOrchestrator(
                    cfg={},
                    health_check_fn=run_full_health_check,
                    circuit_breaker_service=cb,
                )
            c.register_factory(SelfHealingOrchestrator, _make_healing)
    except ImportError:
        pass

    # Capacity Planner
    try:
        from core.capacity_planning import CapacityPlanner
        if not c.is_registered(CapacityPlanner):
            c.register_singleton(CapacityPlanner, CapacityPlanner)
    except ImportError:
        pass

    # Cost Governance (FinOps)
    try:
        from core.finops import CostGovernance
        if not c.is_registered(CostGovernance):
            c.register_singleton(CostGovernance, CostGovernance)
    except ImportError:
        pass

    # Version Compatibility Matrix
    try:
        from core.version_compatibility import VersionCompatibilityMatrix
        if not c.is_registered(VersionCompatibilityMatrix):
            c.register_singleton(VersionCompatibilityMatrix, VersionCompatibilityMatrix)
    except ImportError:
        pass

    # SLO / SLA Governance
    try:
        from core.slo_governance import SLOGovernance
        if not c.is_registered(SLOGovernance):
            c.register_singleton(SLOGovernance, SLOGovernance)
    except ImportError:
        pass

    # Global Risk Dashboard
    try:
        from core.risk_dashboard import RiskDashboard
        if not c.is_registered(RiskDashboard):
            c.register_singleton(RiskDashboard, RiskDashboard)
    except ImportError:
        pass

    # Change Management & Approval Workflow
    try:
        from core.change_management import ChangeManager
        if not c.is_registered(ChangeManager):
            c.register_singleton(ChangeManager, ChangeManager)
    except ImportError:
        pass

    return c


def _resolve_config_manager() -> Any:
    """Lazily resolve the global ConfigManager instance from index_trader."""
    try:
        from index_app.index_trader import _cfg_manager
        if _cfg_manager is not None:
            return _cfg_manager
    except ImportError:
        pass
    # Fallback: return an empty ConfigManager (fail-safe defaults will apply)
    from index_app.domains.config.manager import ConfigManager
    return ConfigManager(name="di-fallback")


# Global container instance with default services wired
container = wire_default_services(DIContainer())


def get_container() -> DIContainer:
    """Get the global DI container instance."""
    return container


def reset_container() -> None:
    """Clear the global container and re-wire default services.

    Primarily useful for testing isolation.
    """
    global container
    container.clear()
    container = wire_default_services(DIContainer())
