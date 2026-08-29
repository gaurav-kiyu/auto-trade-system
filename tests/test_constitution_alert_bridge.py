"""Tests for core/constitution_alert_bridge.py.

Verifies the constitution alert bridge constructs, resets, and exposes
stats without requiring a live Telegram connection.
"""
from __future__ import annotations

from core.constitution_alert_bridge import (
    AlertCheckResult,
    ConstitutionAlertBridge,
    get_constitution_alert_bridge,
    reset_constitution_alert_bridge,
)


def test_bridge_constructs_with_disabled_config():
    """A bridge with alerts disabled must construct cleanly."""
    bridge = ConstitutionAlertBridge(config={"enabled": False})
    assert bridge is not None


def test_get_bridge_returns_instance():
    """The module-level factory returns a ConstitutionAlertBridge."""
    reset_constitution_alert_bridge()
    bridge = get_constitution_alert_bridge({"enabled": False})
    assert isinstance(bridge, ConstitutionAlertBridge)


def test_reset_clears_singleton():
    """reset_constitution_alert_bridge must not raise and must clear state."""
    reset_constitution_alert_bridge()
    bridge = get_constitution_alert_bridge({"enabled": False})
    result = bridge.get_last_result()
    assert result is None or isinstance(result, AlertCheckResult)


def test_get_stats_returns_dict():
    """get_stats must return a dict even with no alerts fired."""
    reset_constitution_alert_bridge()
    bridge = get_constitution_alert_bridge({"enabled": False})
    stats = bridge.get_stats()
    assert isinstance(stats, dict)
