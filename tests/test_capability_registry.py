"""Tests for Dynamic Capability Registry and Operational Feature Gating.

Validates:
1. Dynamic detection of dependency states (AVAILABLE vs UNAVAILABLE).
2. Sample/demo data alone does NOT qualify as AVAILABLE.
3. Runtime overrides and simulated dependency recovery.
4. Thread-safe evaluation and report generation.
"""

from __future__ import annotations

import pytest
from core.capabilities import CapabilityRegistry, CapabilityState


@pytest.fixture(autouse=True)
def clean_registry():
    CapabilityRegistry.reset_instance()
    reg = CapabilityRegistry.get_instance()
    reg.clear_overrides()
    yield reg
    reg.clear_overrides()
    CapabilityRegistry.reset_instance()


def test_capabilities_baseline_sample_data_is_unavailable(clean_registry):
    """Features with only sample/demo data must be UNAVAILABLE in production."""
    reg = clean_registry
    report = reg.evaluate_all(force_refresh=True)

    # These 5 features only have demo/sample data or require broker routing
    assert reg.get_state("sector_radar") == CapabilityState.UNAVAILABLE.value
    assert reg.get_state("fii_dii_radar") == CapabilityState.UNAVAILABLE.value
    assert reg.get_state("margin_radar") == CapabilityState.UNAVAILABLE.value
    assert reg.get_state("trade_copier") == CapabilityState.UNAVAILABLE.value
    assert reg.get_state("expiry_harvester") == CapabilityState.UNAVAILABLE.value

    # Pure analytical / paper execution engines must be AVAILABLE
    assert reg.get_state("payoff_calculator") == CapabilityState.AVAILABLE.value
    assert reg.get_state("performance_dashboard") == CapabilityState.AVAILABLE.value
    assert reg.get_state("strategy_sandbox") == CapabilityState.AVAILABLE.value
    assert reg.get_state("intelligence_engine") == CapabilityState.AVAILABLE.value


def test_is_available_method(clean_registry):
    reg = clean_registry
    assert reg.is_available("sector_radar") is False
    assert reg.is_available("trade_copier") is False
    assert reg.is_available("payoff_calculator") is True


def test_runtime_override_and_restoration(clean_registry):
    reg = clean_registry
    assert reg.is_available("sector_radar") is False

    # Simulate live feed restoration via override
    reg.set_override("sector_radar", CapabilityState.AVAILABLE, "Restored live feed stream")
    assert reg.is_available("sector_radar") is True
    assert reg.get_state("sector_radar") == CapabilityState.AVAILABLE.value

    # Clear override restores UNAVAILABLE state
    reg.clear_overrides()
    assert reg.is_available("sector_radar") is False


def test_get_states_dictionary(clean_registry):
    reg = clean_registry
    states = reg.get_states()
    assert isinstance(states, dict)
    assert "sector_radar" in states
    assert "trade_copier" in states
    assert "payoff_calculator" in states
    assert states["payoff_calculator"] == CapabilityState.AVAILABLE.value


def test_diagnostic_report_structure(clean_registry):
    reg = clean_registry
    report = reg.evaluate_all(force_refresh=True)
    assert "evaluated_at" in report
    assert "summary" in report
    assert "capabilities" in report

    summary = report["summary"]
    assert summary["AVAILABLE"] >= 4
    assert summary["UNAVAILABLE"] >= 5

    sector = report["capabilities"]["sector_radar"]
    assert sector["route"] == "/sector-radar"
    assert sector["is_demo_only"] is True
    assert "sample data only" in sector["reason"]
