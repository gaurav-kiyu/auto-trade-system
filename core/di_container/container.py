"""Dependency Injection Container
Provides a simple inversion of control container for managing service lifetimes
and resolving interfaces to concrete implementations.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, TypeVar

_log = logging.getLogger(__name__)

T = TypeVar("T")


class DIContainer:
    """A simple dependency injection container supporting:
    - Registering interfaces (or abstract classes) to concrete implementations
    - Singleton and transient lifetimes
    - Factory functions for complex creation logic
    """

    def __init__(self) -> None:
        self._singletons: dict[type, type] = {}
        self._singleton_instances: dict[type, Any] = {}
        self._factories: dict[type, Callable[[], Any]] = {}
        self._transients: dict[type, type] = {}
        self._lock = threading.RLock()

    def register_singleton(self, interface: type[Any], implementation: type[Any]) -> None:
        with self._lock:
            self._singletons[interface] = implementation
            if interface not in self._singleton_instances:
                self._singleton_instances[interface] = None

    def register_transient(self, interface: type[Any], implementation: type[Any]) -> None:
        with self._lock:
            self._transients[interface] = implementation

    def register_instance(self, interface: type[T], instance: T) -> None:
        with self._lock:
            self._singletons[interface] = type(instance)
            self._singleton_instances[interface] = instance

    def register_factory(self, interface: type[T], factory: Callable[[], T]) -> None:
        with self._lock:
            self._factories[interface] = factory

    def resolve(self, interface: type[T]) -> T:
        with self._lock:
            if interface in self._factories:
                return self._factories[interface]()  # type: ignore[no-any-return]
            if interface in self._singletons:
                if interface not in self._singleton_instances or self._singleton_instances[interface] is None:
                    instance = self._singletons[interface]()
                    self._singleton_instances[interface] = instance
                return self._singleton_instances[interface]  # type: ignore[no-any-return]
            if interface in self._transients:
                implementation = self._transients[interface]
                return implementation()  # type: ignore[no-any-return]
            raise KeyError(f"No registration found for interface {interface}")

    def try_resolve(self, interface: type[T]) -> T | None:
        try:
            return self.resolve(interface)
        except KeyError:
            return None

    def is_registered(self, interface: type[T]) -> bool:
        with self._lock:
            return (interface in self._factories or
                    interface in self._singletons or
                    interface in self._transients)

    def clear(self) -> None:
        with self._lock:
            self._singletons.clear()
            self._factories.clear()
            self._transients.clear()


# ── Global container instance management ─────────────────────────────
# This is set by __init__.py after all sub-modules are loaded.
# The lazy pattern avoids circular imports when wire modules reference
# the global fallback container.
_container_instance: DIContainer | None = None


def _get_global_container() -> DIContainer | None:
    """Get the global DI container instance (may be None if not yet initialized)."""
    return _container_instance


def _set_global_container(c: DIContainer) -> None:
    """Set the global DI container instance (called by __init__.py)."""
    global _container_instance
    _container_instance = c



def _get_container(container_instance: DIContainer | None = None) -> DIContainer:
    """Resolve container instance: use passed instance or fall back to global."""
    if container_instance is not None:
        return container_instance
    global_c = _get_global_container()
    if global_c is not None:
        return global_c
    raise RuntimeError("DI container not initialized. Call get_container() first.")


def _register_multi_asset_adapters(container_instance: DIContainer) -> None:
    """Register multi-asset market data adapters."""
    try:
        from index_app.domains.market.adapter_factory import register_multi_asset_adapters as _real_register
        _real_register(container_instance)
    except ImportError:
        pass


def _resolve_config_manager() -> Any:
    """Lazily resolve the global ConfigManager instance from index_trader."""
    try:
        from index_app.index_trader import _cfg_manager
        if _cfg_manager is not None:
            return _cfg_manager
    except ImportError:
        pass
    from index_app.domains.config.manager import ConfigManager
    return ConfigManager(name="di-fallback")


__all__ = [
    "DIContainer",
    "T",
    "_get_global_container",
    "_set_global_container",
    "_register_multi_asset_adapters",
    "_resolve_config_manager",
]
