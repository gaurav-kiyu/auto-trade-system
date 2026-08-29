"""Tests for core/di_container/container.py.

Verifies the DIContainer registration/resolution primitives and the
module-level global-container helpers.
"""
from __future__ import annotations

import pytest
from core.di_container.container import (
    DIContainer,
    _get_container,
    _set_global_container,
)


class _Service:
    def ping(self) -> str:
        return "pong"


class _OtherService:
    pass


def test_register_and_resolve_singleton():
    container = DIContainer()
    container.register_singleton(_Service, _Service)
    a = container.resolve(_Service)
    b = container.resolve(_Service)
    assert a is b
    assert a.ping() == "pong"


def test_register_instance():
    container = DIContainer()
    inst = _Service()
    container.register_instance(_Service, inst)
    assert container.resolve(_Service) is inst


def test_register_transient_returns_new_instances():
    container = DIContainer()
    container.register_transient(_Service, _Service)
    a = container.resolve(_Service)
    b = container.resolve(_Service)
    assert a is not b


def test_register_factory():
    container = DIContainer()
    container.register_factory(_Service, lambda: _Service())
    assert isinstance(container.resolve(_Service), _Service)


def test_try_resolve_unregistered_returns_none():
    container = DIContainer()
    assert container.try_resolve(_OtherService) is None


def test_is_registered():
    container = DIContainer()
    container.register_singleton(_Service, _Service)
    assert container.is_registered(_Service) is True
    assert container.is_registered(_OtherService) is False


def test_resolve_unregistered_raises():
    container = DIContainer()
    with pytest.raises(Exception):
        container.resolve(_OtherService)


def test_clear():
    container = DIContainer()
    container.register_singleton(_Service, _Service)
    container.clear()
    assert container.is_registered(_Service) is False


def test_global_container_helpers():
    # Save the prior global container and restore it, so this test never
    # leaves the global uninitialized (which would break later tests that
    # call get_container()). Order-independent test isolation.
    from core.di_container.container import _get_global_container
    prior = _get_global_container()
    seed = DIContainer()
    _set_global_container(seed)
    try:
        container = _get_container()
        assert container is seed
    finally:
        _set_global_container(prior)
