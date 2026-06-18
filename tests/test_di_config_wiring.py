"""Tests for DI container wiring — ConfigManager resolution and fallback."""

from __future__ import annotations

import pytest

from core.di_container import DIContainer, wire_default_services, reset_container, get_container
from index_app.domains.config.manager import ConfigManager


@pytest.fixture(autouse=True)
def _clean_global_container():
    """Ensure clean global container state before each test."""
    reset_container()
    yield


class TestConfigManagerWireDefaultServices:
    """Verify that wire_default_services() registers ConfigManager in the DI container."""

    def test_config_manager_registered_after_wire(self):
        """ConfigManager should be registered as a factory after wire_default_services."""
        container = DIContainer()
        wire_default_services(container)
        assert container.is_registered(ConfigManager), "ConfigManager should be registered"

    def test_config_manager_resolves_via_factory(self):
        """ConfigManager should resolve to a ConfigManager instance."""
        container = DIContainer()
        wire_default_services(container)
        mgr = container.resolve(ConfigManager)
        assert isinstance(mgr, ConfigManager)

    def test_resolve_same_instance_singleton(self):
        """Factory-registered ConfigManager should return same instance on repeated resolve."""
        container = DIContainer()
        wire_default_services(container)
        mgr1 = container.resolve(ConfigManager)
        mgr2 = container.resolve(ConfigManager)
        assert mgr1 is mgr2, "ConfigManager should be singleton (factory returns same ref)"


class TestConfigManagerGlobalContainer:
    """Verify the global container has ConfigManager registered."""

    def test_global_container_has_config_manager(self):
        """The global container instance should have ConfigManager registered."""
        container = get_container()
        assert container.is_registered(ConfigManager), (
            "Global container should have ConfigManager registered"
        )

    def test_global_container_resolves_config_manager(self):
        """The global container should resolve ConfigManager."""
        container = get_container()
        mgr = container.resolve(ConfigManager)
        assert isinstance(mgr, ConfigManager)

    def test_reset_container_preserves_wiring(self):
        """After reset, ConfigManager should still be registered."""
        container = get_container()
        assert container.is_registered(ConfigManager), (
            "ConfigManager should survive container reset"
        )
