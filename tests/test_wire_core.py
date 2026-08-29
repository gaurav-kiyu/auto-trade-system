"""Tests for core/di_container/wire_core.py.

Verifies core DI wiring functions run against a fresh container.
"""
from __future__ import annotations

from core.di_container.container import DIContainer
from core.di_container.wire_core import wire_mediator_services, wire_multi_asset_dispatcher


def test_wire_mediator_services_runs():
    """Mediator services wiring must not raise on a fresh container."""
    container = DIContainer()
    wire_mediator_services(container)


def test_wire_multi_asset_dispatcher_runs():
    """Multi-asset dispatcher wiring must not raise."""
    container = DIContainer()
    wire_multi_asset_dispatcher(container)


def test_wire_core_accepts_default():
    """Both wire functions accept their default container_instance=None."""
    from core.di_container.container import _get_global_container, _set_global_container

    # Save the prior global container and restore it, so this test never
    # leaves the global uninitialized (which would break later tests that
    # call get_container()). Order-independent test isolation.
    prior = _get_global_container()
    _set_global_container(DIContainer())
    try:
        wire_mediator_services()
        wire_multi_asset_dispatcher()
    finally:
        _set_global_container(prior)
