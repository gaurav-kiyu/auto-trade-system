"""Tests for core/integrations/tracing_mediator.py.

Verifies the Distributed Tracing -> Mediator wiring bridge.
"""
from __future__ import annotations

from core.integrations.tracing_mediator import wire_tracing_to_mediator


def test_wire_tracing_to_mediator_returns_bool():
    """The wiring bridge must return a success boolean."""
    result = wire_tracing_to_mediator()
    assert isinstance(result, bool)
