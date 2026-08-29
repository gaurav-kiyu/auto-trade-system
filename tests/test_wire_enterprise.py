"""Tests for core/di_container/wire_enterprise.py.

Verifies enterprise service wiring functions run against a fresh container.
"""
from __future__ import annotations

from core.di_container.container import DIContainer
from core.di_container.wire_enterprise import (
    wire_architecture_services,
    wire_chaos_engine_services,
    wire_performance_services,
    wire_sbom_services,
    wire_synthetic_monitor_services,
)


def test_wire_performance_services_runs():
    wire_performance_services(DIContainer())


def test_wire_architecture_services_runs():
    wire_architecture_services(DIContainer())


def test_wire_synthetic_monitor_services_runs():
    wire_synthetic_monitor_services(DIContainer())


def test_wire_sbom_services_runs():
    wire_sbom_services(DIContainer())


def test_wire_chaos_engine_services_runs():
    wire_chaos_engine_services(DIContainer())


def test_wire_enterprise_accepts_default():
    """Functions must tolerate their default container_instance=None."""
    from core.di_container.container import _get_global_container, _set_global_container

    # Save the prior global container and restore it, so this test never
    # leaves the global uninitialized (which would break later tests that
    # call get_container()). Order-independent test isolation.
    prior = _get_global_container()
    _set_global_container(DIContainer())
    try:
        wire_performance_services()
        wire_architecture_services()
    finally:
        _set_global_container(prior)
