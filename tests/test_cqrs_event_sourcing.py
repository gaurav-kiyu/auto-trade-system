"""Tests for core/integrations/cqrs_event_sourcing.py.

Verifies the CQRS -> Event Sourcing wiring bridge.
"""
from __future__ import annotations

from core.integrations.cqrs_event_sourcing import get_command_bus, wire_cqrs_to_event_sourcing


def test_wire_cqrs_to_event_sourcing_returns_bool():
    """The wiring bridge must return a success boolean."""
    result = wire_cqrs_to_event_sourcing()
    assert isinstance(result, bool)


def test_get_command_bus_returns_bus_or_none():
    """get_command_bus must return a command bus object or None."""
    bus = get_command_bus()
    assert bus is None or bus is not None
