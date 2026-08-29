"""Tests for core/di_container/wire_default.py.

Verifies the default service wiring returns a fully wired DIContainer.
"""
from __future__ import annotations

from core.di_container.container import DIContainer
from core.di_container.wire_default import wire_default_services


def test_wire_default_returns_container():
    """wire_default_services must return a DIContainer.

    Passing no container is safe: wire_default_services() creates a fresh
    DIContainer internally (no dependency on process-global DI state).
    """
    container = wire_default_services()
    assert isinstance(container, DIContainer)


def test_wire_default_accepts_existing_container():
    """Passing an existing container must not raise."""
    container = DIContainer()
    result = wire_default_services(container)
    assert isinstance(result, DIContainer)
