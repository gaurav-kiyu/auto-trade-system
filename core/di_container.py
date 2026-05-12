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


# Global container instance
container = DIContainer()


def get_container() -> DIContainer:
    """Get the global DI container instance."""
    return container
