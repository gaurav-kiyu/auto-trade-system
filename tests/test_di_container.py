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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
