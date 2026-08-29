"""Tests for core/integrations/feature_flag_guards.py.

Verifies the feature flag guard integration and wiring bridge.
"""
from __future__ import annotations

from core.integrations.feature_flag_guards import (
    FeatureFlagGuard,
    get_feature_flag_guard,
    wire_feature_flag_guards,
)


def test_get_feature_flag_guard_returns_instance():
    """get_feature_flag_guard must return a FeatureFlagGuard."""
    guard = get_feature_flag_guard()
    assert isinstance(guard, FeatureFlagGuard)


def test_wire_feature_flag_guards_returns_bool():
    """The wiring bridge must return a success boolean."""
    result = wire_feature_flag_guards()
    assert isinstance(result, bool)
