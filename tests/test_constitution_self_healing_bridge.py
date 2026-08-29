"""Tests for core/constitution_self_healing_bridge.py.

Verifies the constitution failure-pattern registration and the self-healing
wiring entry point.
"""
from __future__ import annotations

from core.constitution_self_healing_bridge import (
    register_constitution_patterns,
    wire_constitution_self_healing,
)


def test_register_constitution_patterns_returns_int():
    """Pattern registration must return the number of patterns registered."""
    count = register_constitution_patterns()
    assert isinstance(count, int)
    assert count >= 0


def test_wire_constitution_self_healing_returns_bool():
    """The wiring entry point must return a success boolean."""
    result = wire_constitution_self_healing()
    assert isinstance(result, bool)
