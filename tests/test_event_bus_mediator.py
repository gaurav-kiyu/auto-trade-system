"""Tests for core/integrations/event_bus_mediator.py.

Verifies the Event Bus -> Mediator wiring bridge.
"""
from __future__ import annotations

from core.integrations.event_bus_mediator import wire_event_bus_to_mediator


def test_wire_event_bus_to_mediator_returns_bool():
    """The wiring bridge must return a success boolean."""
    result = wire_event_bus_to_mediator()
    assert isinstance(result, bool)
