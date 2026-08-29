"""
Tests for DI Container.
"""

from __future__ import annotations

import threading

import pytest
from core.di_container import DIContainer, get_container


# Test interfaces and implementations
class IAlertRouter:
    def send_alert(self, subject: str, body: str) -> dict:
        pass

class IAnomalyDetector:
    def update_and_check(self, metric_name: str, value: float) -> tuple:
        pass

class AlertRouter(IAlertRouter):
    def __init__(self, bot_token: str = "test", chat_id: str = "test"):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send_alert(self, subject: str, body: str) -> dict:
        return {"telegram": True, "email": False, "webhook": False}

class AnomalyDetector(IAnomalyDetector):
    def __init__(self, threshold: float = 2.0):
        self.threshold = threshold
        self.history = []

    def update_and_check(self, metric_name: str, value: float) -> tuple:
        self.history.append(value)
        if len(self.history) < 2:
            return False, 0.0
        mean = sum(self.history) / len(self.history)
        variance = sum((x - mean) ** 2 for x in self.history) / len(self.history)
        std = variance ** 0.5 if variance > 0 else 0.0
        if std == 0.0:
            return False, 0.0
        z_score = abs((value - mean) / std)
        return z_score > self.threshold, z_score


def test_di_container_singleton():
    """Test singleton registration and resolution."""
    container = DIContainer()

    # Test singleton registration
    container.register_singleton(IAlertRouter, AlertRouter)
    router1 = container.resolve(IAlertRouter)
    router2 = container.resolve(IAlertRouter)
    assert router1 is router2, "Singleton should return same instance"
    assert isinstance(router1, AlertRouter), "Should resolve to AlertRouter"


def test_di_container_transient():
    """Test transient registration and resolution."""
    container = DIContainer()

    # Test transient registration
    container.register_transient(IAnomalyDetector, AnomalyDetector)
    detector1 = container.resolve(IAnomalyDetector)
    detector2 = container.resolve(IAnomalyDetector)
    assert detector1 is not detector2, "Transient should return different instances"
    assert isinstance(detector1, AnomalyDetector), "Should resolve to AnomalyDetector"


def test_di_container_factory():
    """Test factory registration and resolution."""
    container = DIContainer()

    # Test factory registration
    def alert_factory():
        return AlertRouter("factory_token", "factory_chat")

    container.register_factory(IAlertRouter, alert_factory)
    router = container.resolve(IAlertRouter)
    assert isinstance(router, AlertRouter), "Factory should work"
    assert router.bot_token == "factory_token"
    assert router.chat_id == "factory_chat"


def test_di_container_try_resolve():
    """Test try_resolve method."""
    container = DIContainer()

    # Test with unregistered interface
    class IUnknown:
        pass

    assert container.try_resolve(IUnknown) is None, "Should return None for unregistered interface"

    # Test with registered interface
    container.register_singleton(IAlertRouter, AlertRouter)
    assert container.try_resolve(IAlertRouter) is not None, "Should return instance for registered interface"


def test_di_container_is_registered():
    """Test is_registered method."""
    container = DIContainer()

    class IUnknown:
        pass

    assert not container.is_registered(IUnknown), "Should not be registered initially"

    container.register_singleton(IAlertRouter, AlertRouter)
    assert container.is_registered(IAlertRouter), "Should be registered after registration"


def test_di_container_clear():
    """Test clear method."""
    container = DIContainer()

    container.register_singleton(IAlertRouter, AlertRouter)
    container.register_transient(IAnomalyDetector, AnomalyDetector)
    assert container.is_registered(IAlertRouter)
    assert container.is_registered(IAnomalyDetector)

    container.clear()
    assert not container.is_registered(IAlertRouter)
    assert not container.is_registered(IAnomalyDetector)
    assert container.try_resolve(IAlertRouter) is None
    assert container.try_resolve(IAnomalyDetector) is None


def test_di_container_thread_safety():
    """Test that the container is thread-safe."""
    container = DIContainer()
    container.register_singleton(IAlertRouter, AlertRouter)

    results = []
    def worker():
        router = container.resolve(IAlertRouter)
        results.append(router)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads should get the same instance
    assert all(r is results[0] for r in results)
    assert isinstance(results[0], AlertRouter)


def test_get_container():
    """Test the global container getter."""
    container = get_container()
    assert isinstance(container, DIContainer)
    # Should be the same instance on subsequent calls
    assert get_container() is container


@pytest.mark.xfail(strict=False, reason="Python 3.14 numpy import conflict under full suite")
def test_wire_multi_asset_dispatcher():
    """Test that wire_multi_asset_dispatcher registers the dispatcher."""
    from core.di_container import wire_multi_asset_dispatcher
    from core.strategy.multi_asset_dispatcher import MultiAssetStrategyDispatcher

    container = DIContainer()
    assert not container.is_registered(MultiAssetStrategyDispatcher)

    wire_multi_asset_dispatcher(container)
    assert container.is_registered(MultiAssetStrategyDispatcher)

    dispatcher = container.resolve(MultiAssetStrategyDispatcher)
    assert dispatcher is not None
    status = dispatcher.get_status()
    assert "registered_engines" in status
    assert "INDEX_OPTIONS" in status["registered_engines"]


@pytest.mark.xfail(strict=False, reason="Python 3.14 numpy import conflict under full suite")
def test_wire_multi_asset_dispatcher_idempotent():
    """Test that wire_multi_asset_dispatcher is idempotent."""
    from core.di_container import wire_multi_asset_dispatcher
    from core.strategy.multi_asset_dispatcher import MultiAssetStrategyDispatcher

    container = DIContainer()
    wire_multi_asset_dispatcher(container)
    dispatcher1 = container.resolve(MultiAssetStrategyDispatcher)
    wire_multi_asset_dispatcher(container)
    dispatcher2 = container.resolve(MultiAssetStrategyDispatcher)
    assert dispatcher1 is dispatcher2

    status = dispatcher2.get_status()
    assert "INDEX_OPTIONS" in status["registered_engines"]


# ── Edge case tests for DI container ─────────────────────────────────────────


def test_di_container_resolve_unregistered_raises_keyerror():
    """resolve() raises KeyError for unregistered interfaces."""
    container = DIContainer()

    class IUnregistered:
        pass

    with pytest.raises(KeyError, match="No registration found"):
        container.resolve(IUnregistered)


def test_di_container_register_instance_returns_same_reference():
    """register_instance always returns the exact same instance on resolve."""
    container = DIContainer()
    router = AlertRouter("prebuilt_token", "prebuilt_chat")
    container.register_instance(IAlertRouter, router)
    resolved = container.resolve(IAlertRouter)
    assert resolved is router
    assert resolved.bot_token == "prebuilt_token"


def test_di_container_factory_called_each_resolve():
    """Factory is called on every resolve (not cached like singletons)."""
    container = DIContainer()
    call_count = [0]
    def counting_factory():
        call_count[0] += 1
        return AlertRouter(f"token_{call_count[0]}", f"chat_{call_count[0]}")
    container.register_factory(IAlertRouter, counting_factory)
    r1 = container.resolve(IAlertRouter)
    r2 = container.resolve(IAlertRouter)
    assert call_count[0] == 2
    assert r1 is not r2
    assert r1.bot_token == "token_1"
    assert r2.bot_token == "token_2"


def test_di_container_is_registered_factory():
    """is_registered returns True for factory-registered interfaces."""
    container = DIContainer()
    container.register_factory(IAlertRouter, lambda: AlertRouter())
    assert container.is_registered(IAlertRouter)


def test_di_container_singleton_lazy_initialization():
    """Singleton is lazily initialized on first resolve, not at register time."""
    container = DIContainer()
    init_count = [0]
    class TrackedAlertRouter(AlertRouter):
        def __init__(self):
            init_count[0] += 1
            super().__init__()
    container.register_singleton(IAlertRouter, TrackedAlertRouter)
    assert init_count[0] == 0  # Not initialized yet (lazy)
    container.resolve(IAlertRouter)
    assert init_count[0] == 1  # Initialized on first resolve
    container.resolve(IAlertRouter)
    assert init_count[0] == 1  # Not re-initialized (singleton)


@pytest.mark.xfail(strict=False, reason="Python 3.14 numpy import conflict under full suite")
def test_wire_multi_asset_dispatcher_without_configmanager():
    """wire_multi_asset_dispatcher works when ConfigManager is not available."""
    from core.di_container import wire_multi_asset_dispatcher
    from core.strategy.multi_asset_dispatcher import MultiAssetStrategyDispatcher

    container = DIContainer()
    # Don't register a ConfigManager — the function should fall back gracefully
    wire_multi_asset_dispatcher(container)
    assert container.is_registered(MultiAssetStrategyDispatcher)
    dispatcher = container.resolve(MultiAssetStrategyDispatcher)
    status = dispatcher.get_status()
    assert "INDEX_OPTIONS" in status["registered_engines"]


def test_di_container_register_transient_thread_safe():
    """Multiple threads can register and resolve transients concurrently."""
    container = DIContainer()
    results: list = []
    errors: list = []

    def worker():
        try:
            container.register_transient(IAnomalyDetector, AnomalyDetector)
            d = container.resolve(IAnomalyDetector)
            results.append(d)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(results) == 5
    # Each worker gets a unique transient instance
    unique_instances = set(id(r) for r in results)
    assert len(unique_instances) == 5


# ── Wire service registration tests ──────────────────────────────────────────


def test_wire_security_services():
    """wire_security_services registers SecurityAuditor in the container."""
    from core.di_container import wire_security_services
    container = DIContainer()
    wire_security_services(container)
    from core.security_auditor import SecurityAuditor
    assert container.is_registered(SecurityAuditor)
    auditor = container.resolve(SecurityAuditor)
    assert auditor is not None


def test_wire_security_services_idempotent():
    """wire_security_services can be called multiple times (same instance)."""
    from core.di_container import wire_security_services
    from core.security_auditor import SecurityAuditor
    container = DIContainer()
    wire_security_services(container)
    a1 = container.resolve(SecurityAuditor)
    wire_security_services(container)
    a2 = container.resolve(SecurityAuditor)
    assert a1 is a2


def test_wire_performance_services():
    """wire_performance_services registers PerformanceOptimizer in the container."""
    from core.di_container import wire_performance_services
    container = DIContainer()
    wire_performance_services(container)
    from core.performance_optimizer import PerformanceOptimizer
    assert container.is_registered(PerformanceOptimizer)
    optimizer = container.resolve(PerformanceOptimizer)
    assert optimizer is not None


def test_wire_performance_services_idempotent():
    """wire_performance_services can be called multiple times (same instance)."""
    from core.di_container import wire_performance_services
    from core.performance_optimizer import PerformanceOptimizer
    container = DIContainer()
    wire_performance_services(container)
    p1 = container.resolve(PerformanceOptimizer)
    wire_performance_services(container)
    p2 = container.resolve(PerformanceOptimizer)
    assert p1 is p2


def test_wire_architecture_services():
    """wire_architecture_services registers ArchitectureAnalyzer in the container."""
    from core.di_container import wire_architecture_services
    container = DIContainer()
    wire_architecture_services(container)
    from core.architecture_analyzer import ArchitectureAnalyzer
    assert container.is_registered(ArchitectureAnalyzer)
    analyzer = container.resolve(ArchitectureAnalyzer)
    assert analyzer is not None


def test_wire_architecture_services_idempotent():
    """wire_architecture_services can be called multiple times (same instance)."""
    from core.architecture_analyzer import ArchitectureAnalyzer
    from core.di_container import wire_architecture_services
    container = DIContainer()
    wire_architecture_services(container)
    a1 = container.resolve(ArchitectureAnalyzer)
    wire_architecture_services(container)
    a2 = container.resolve(ArchitectureAnalyzer)
    assert a1 is a2


def test_wire_mediator_services():
    """wire_mediator_services registers Mediator in the container."""
    from core.di_container import wire_mediator_services
    container = DIContainer()
    wire_mediator_services(container)
    from core.patterns.mediator import Mediator
    assert container.is_registered(Mediator)
    mediator = container.resolve(Mediator)
    assert mediator is not None


def test_reset_container_clears_and_rewires():
    """reset_container clears all registrations and re-wires defaults.

    Save/restores the global container to avoid test pollution.
    """
    from core.di_container import container as global_container
    from core.di_container import reset_container
    original_container = global_container
    original_singletons = dict(global_container._singletons)
    original_instances = dict(global_container._singleton_instances)
    original_factories = dict(global_container._factories)
    original_transients = dict(global_container._transients)
    try:
        # Reset clears and re-wires the global container
        reset_container()
        from core.di_container import get_container as gc
        new_c = gc()
        # Should have at least some services registered after rewire
        assert new_c is not None
        assert new_c is not original_container  # New instance
    finally:
        # Restore original state to avoid test pollution
        original_container._singletons.clear()
        original_container._singletons.update(original_singletons)
        original_container._singleton_instances.clear()
        original_container._singleton_instances.update(original_instances)
        original_container._factories.clear()
        original_container._factories.update(original_factories)
        original_container._transients.clear()
        original_container._transients.update(original_transients)


# ── Wire Presentation Services ────────────────────────────────────────────


def test_wire_presentation_services():
    """wire_presentation_services registers PresentationGenerator."""
    from core.di_container import wire_presentation_services
    container = DIContainer()
    wire_presentation_services(container)
    from core.presentation_generator import PresentationGenerator
    assert container.is_registered(PresentationGenerator)
    gen = container.resolve(PresentationGenerator)
    assert gen is not None


def test_wire_presentation_services_idempotent():
    """wire_presentation_services is idempotent."""
    from core.di_container import wire_presentation_services
    from core.presentation_generator import PresentationGenerator
    container = DIContainer()
    wire_presentation_services(container)
    g1 = container.resolve(PresentationGenerator)
    wire_presentation_services(container)
    g2 = container.resolve(PresentationGenerator)
    assert g1 is g2


# ── Wire Recommendation Services ──────────────────────────────────────────


def test_wire_recommendation_services():
    """wire_recommendation_services registers RecommendationEngine."""
    from core.di_container import wire_recommendation_services
    container = DIContainer()
    wire_recommendation_services(container)
    from core.recommendation_engine import RecommendationEngine
    assert container.is_registered(RecommendationEngine)
    engine = container.resolve(RecommendationEngine)
    assert engine is not None


def test_wire_recommendation_services_idempotent():
    """wire_recommendation_services is idempotent."""
    from core.di_container import wire_recommendation_services
    from core.recommendation_engine import RecommendationEngine
    container = DIContainer()
    wire_recommendation_services(container)
    e1 = container.resolve(RecommendationEngine)
    wire_recommendation_services(container)
    e2 = container.resolve(RecommendationEngine)
    assert e1 is e2


# ── Wire Default Services Error Resilience ─────────────────────────────────


def test_wire_default_services_registers_key_services():
    """wire_default_services registers all key services."""
    from core.architecture_analyzer import ArchitectureAnalyzer
    from core.di_container import wire_default_services
    from core.patterns.mediator import Mediator
    from core.performance_optimizer import PerformanceOptimizer
    from core.security_auditor import SecurityAuditor

    container = DIContainer()
    result = wire_default_services(container)
    assert result is container
    assert container.is_registered(Mediator)
    assert container.is_registered(SecurityAuditor)
    assert container.is_registered(PerformanceOptimizer)
    assert container.is_registered(ArchitectureAnalyzer)


def test_wire_default_services_returns_container():
    """wire_default_services returns the container it was passed."""
    from core.di_container import wire_default_services
    container = DIContainer()
    result = wire_default_services(container)
    assert result is container


def test_wire_default_services_no_args():
    """wire_default_services works without arguments (uses global container)."""
    from core.di_container import wire_default_services
    result = wire_default_services()
    assert result is not None
    assert isinstance(result, DIContainer)


def test_wire_mediator_services_registers_mediator():
    """wire_mediator_services registers Mediator with default config."""
    from core.di_container import wire_mediator_services
    from core.patterns.mediator import Mediator
    container = DIContainer()
    wire_mediator_services(container)
    assert container.is_registered(Mediator)
    mediator = container.resolve(Mediator)
    assert mediator is not None
    stats = mediator.get_stats()
    assert "registered_commands" in stats


def test_wire_mediator_services_idempotent():
    """wire_mediator_services can be called multiple times."""
    from core.di_container import wire_mediator_services
    from core.patterns.mediator import Mediator
    container = DIContainer()
    wire_mediator_services(container)
    m1 = container.resolve(Mediator)
    wire_mediator_services(container)
    m2 = container.resolve(Mediator)
    assert m1 is m2


# ── resolve/missing registration paths ───────────────────────────────────


def test_di_container_resolve_singleton_not_cached_is_created():
    """Singleton that hasn't been cached yet is created on resolve."""
    container = DIContainer()
    container._singletons[IAlertRouter] = AlertRouter
    # Don't add to _singleton_instances - should be created
    router = container.resolve(IAlertRouter)
    assert isinstance(router, AlertRouter)


def test_di_container_resolve_factory_takes_priority():
    """Factory takes priority over singleton when both registered."""
    container = DIContainer()
    container.register_singleton(IAlertRouter, AlertRouter)
    container.register_factory(IAlertRouter, lambda: AlertRouter("factory", "factory"))
    router = container.resolve(IAlertRouter)
    assert router.bot_token == "factory"  # Factory took priority


@pytest.mark.xfail(strict=False, reason="Python 3.14 numpy import conflict under full suite")
def test_wire_default_services_full_registration():
    """wire_default_services registers ALL expected services on a fresh container."""
    from core.architecture_analyzer import ArchitectureAnalyzer
    from core.di_container import wire_default_services
    from core.patterns.mediator import Mediator
    from core.performance_optimizer import PerformanceOptimizer
    from core.presentation_generator import PresentationGenerator
    from core.security_auditor import SecurityAuditor
    from core.strategy.multi_asset_dispatcher import MultiAssetStrategyDispatcher

    container = DIContainer()
    wire_default_services(container)
    assert container.is_registered(Mediator)
    assert container.is_registered(SecurityAuditor)
    assert container.is_registered(PerformanceOptimizer)
    assert container.is_registered(ArchitectureAnalyzer)
    assert container.is_registered(PresentationGenerator)
    assert container.is_registered(MultiAssetStrategyDispatcher)


def test_wire_default_services_idempotent_full():
    """wire_default_services is idempotent when called twice."""
    from core.di_container import wire_default_services
    from core.patterns.mediator import Mediator

    container = DIContainer()
    wire_default_services(container)
    mediator1 = container.resolve(Mediator)
    wire_default_services(container)
    mediator2 = container.resolve(Mediator)
    assert mediator1 is mediator2


@pytest.mark.xfail(strict=False, reason="Python 3.14 numpy import conflict under full suite")
def test_wire_multi_asset_dispatcher_idempotent_with_config():
    """wire_multi_asset_dispatcher can be called twice with same result."""
    from core.di_container import wire_multi_asset_dispatcher
    from core.strategy.multi_asset_dispatcher import MultiAssetStrategyDispatcher

    container = DIContainer()
    wire_multi_asset_dispatcher(container)
    d1 = container.resolve(MultiAssetStrategyDispatcher)
    wire_multi_asset_dispatcher(container)
    d2 = container.resolve(MultiAssetStrategyDispatcher)
    assert d1 is d2


# ── Import Error Paths ────────────────────────────────────────────────────


def test_wire_default_services_handles_import_errors_gracefully():
    """Cover try/except ImportError paths by blocking optional dependency imports.

    This uses sys.modules manipulation + __import__ mocking to simulate
    missing optional dependencies, covering the otherwise-inaccessible
    ImportError exception handlers.
    """
    import builtins
    import sys
    from unittest.mock import patch

    # These modules are imported inside wire_default_services try/except blocks
    # We block them to trigger the ImportError handlers
    blocked_modules = {
        'core.portfolio.adapters.multi_asset_aggregator',
        'core.ports.capital_allocation',
        'core.services.market_data_service',
        'core.portfolio.optimizer',
        'core.self_healing.orchestrator',
        'core.health_checker',
        'core.capacity_planning',
        'core.finops',
        'core.version_compatibility',
        'core.slo_governance',
        'core.risk_dashboard',
        'core.change_management',
        'index_app.domains.market.adapter_factory',
        'core.strategy.multi_asset_dispatcher',
        'index_app.domains.config.manager',
    }

    # Save and remove modules from sys.modules to force re-import
    saved = {}
    for mod_name in list(blocked_modules):
        if mod_name in sys.modules:
            saved[mod_name] = sys.modules.pop(mod_name)

    real_import = builtins.__import__

    def selective_import(name, *args, **kwargs):
        if name in blocked_modules:
            raise ImportError(f"Mocked ImportError for {name}")
        return real_import(name, *args, **kwargs)

    try:
        with patch("builtins.__import__", side_effect=selective_import):
            from core.di_container import DIContainer, wire_default_services
            container = DIContainer()
            result = wire_default_services(container)
            assert result is container
            # Core services should still be registered
            from core.patterns.mediator import Mediator
            assert container.is_registered(Mediator)
    finally:
        # Restore sys.modules
        sys.modules.update(saved)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
