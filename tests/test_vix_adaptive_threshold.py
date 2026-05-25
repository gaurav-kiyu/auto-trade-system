"""Tests for core/vix_adaptive_threshold.py — VIX-based threshold adjustment & blocking."""

from __future__ import annotations

import pytest
from core.vix_adaptive_threshold import (
    VIXAdaptiveConfig,
    VIXAdaptiveThreshold,
    create_vix_adaptive_threshold,
)


# ── VIXAdaptiveConfig ─────────────────────────────────────────────────────────

class TestVIXAdaptiveConfig:
    def test_defaults(self) -> None:
        c = VIXAdaptiveConfig()
        assert c.enabled is True
        assert c.vix_low_threshold == 15.0
        assert c.vix_low_bonus == -2
        assert c.vix_high_threshold == 25.0
        assert c.vix_high_penalty == 5
        assert c.vix_block_threshold == 30.0

    def test_custom_values(self) -> None:
        c = VIXAdaptiveConfig(enabled=False, vix_low_threshold=12.0, vix_block_threshold=35.0)
        assert c.enabled is False
        assert c.vix_low_threshold == 12.0
        assert c.vix_block_threshold == 35.0


# ── VIXAdaptiveThreshold ──────────────────────────────────────────────────────

class TestVIXAdaptiveThreshold:
    def test_disabled_returns_base(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(enabled=False))
        engine.update_vix(20.0)
        assert engine.get_adjusted_threshold(65) == 65

    def test_no_vix_data_returns_base(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig())
        assert engine.get_adjusted_threshold(65) == 65

    def test_vix_below_low_threshold_relaxes(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(vix_low_threshold=15.0, vix_low_bonus=-3))
        engine.update_vix(12.0)  # below 15
        adjusted = engine.get_adjusted_threshold(65)
        assert adjusted == 62  # 65 + (-3)

    def test_low_threshold_floor_at_50(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(vix_low_threshold=15.0, vix_low_bonus=-20))
        engine.update_vix(12.0)
        adjusted = engine.get_adjusted_threshold(65)
        assert adjusted == 50  # max(50, 45)

    def test_vix_above_high_threshold_tightens(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(vix_high_threshold=25.0, vix_high_penalty=8))
        engine.update_vix(28.0)  # above 25
        adjusted = engine.get_adjusted_threshold(65)
        assert adjusted == 73  # 65 + 8

    def test_high_threshold_ceiling_at_100(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(vix_high_threshold=25.0, vix_high_penalty=50))
        engine.update_vix(28.0)
        adjusted = engine.get_adjusted_threshold(65)
        assert adjusted == 100  # min(100, 115)

    def test_vix_between_thresholds_returns_base(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(vix_low_threshold=15.0, vix_high_threshold=25.0))
        engine.update_vix(20.0)  # between 15 and 25
        assert engine.get_adjusted_threshold(65) == 65

    def test_vix_at_low_threshold_boundary(self) -> None:
        """At exact low threshold — not below, so no adjustment."""
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(vix_low_threshold=15.0, vix_low_bonus=-2))
        engine.update_vix(15.0)  # not below
        assert engine.get_adjusted_threshold(65) == 65

    def test_vix_at_high_threshold_boundary(self) -> None:
        """At exact high threshold — not above, so no adjustment."""
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(vix_high_threshold=25.0, vix_high_penalty=5))
        engine.update_vix(25.0)  # not above
        assert engine.get_adjusted_threshold(65) == 65


# ── Block entry ───────────────────────────────────────────────────────────────

class TestShouldBlockEntry:
    def test_disabled_does_not_block(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(enabled=False))
        blocked, reason = engine.should_block_entry()
        assert blocked is False
        assert reason == ""

    def test_no_vix_does_not_block(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig())
        blocked, reason = engine.should_block_entry()
        assert blocked is False
        assert reason == ""

    def test_blocks_when_vix_exceeds_block_threshold(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(vix_block_threshold=30.0))
        engine.update_vix(35.0)
        blocked, reason = engine.should_block_entry()
        assert blocked is True
        assert "35.0" in reason
        assert "30.0" in reason

    def test_does_not_block_below_threshold(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(vix_block_threshold=30.0))
        engine.update_vix(25.0)
        blocked, _ = engine.should_block_entry()
        assert blocked is False

    def test_blocking_also_affects_threshold(self) -> None:
        """When VIX blocks, get_adjusted_threshold returns base + 100."""
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig(vix_block_threshold=30.0))
        engine.update_vix(35.0)
        assert engine.get_adjusted_threshold(65) == 165  # 65 + 100


# ── update_vix ────────────────────────────────────────────────────────────────

class TestUpdateVIX:
    def test_updates_and_accessible(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig())
        engine.update_vix(18.5)
        blocked, _ = engine.should_block_entry()
        # VIX changed from None → 18.5, so now should_block works
        assert blocked is False
        assert engine._current_vix == 18.5

    def test_replaces_previous_value(self) -> None:
        engine = VIXAdaptiveThreshold(VIXAdaptiveConfig())
        engine.update_vix(10.0)
        engine.update_vix(20.0)
        assert engine._current_vix == 20.0


# ── create_vix_adaptive_threshold factory ─────────────────────────────────────

class TestCreateFactory:
    def test_creates_from_config_dict(self) -> None:
        engine = create_vix_adaptive_threshold({
            "VIX_ADAPTIVE_THRESHOLDS_ENABLED": True,
            "VIX_LOW_THRESHOLD": 12.0,
            "VIX_BLOCK_THRESHOLD": 32.0,
        })
        assert isinstance(engine, VIXAdaptiveThreshold)
        assert engine.config.vix_low_threshold == 12.0
        assert engine.config.vix_block_threshold == 32.0

    def test_uses_defaults_for_missing_keys(self) -> None:
        engine = create_vix_adaptive_threshold({})
        assert engine.config.enabled is True
        assert engine.config.vix_low_threshold == 15.0
        assert engine.config.vix_block_threshold == 30.0

    def test_handles_empty_config(self) -> None:
        engine = create_vix_adaptive_threshold({})
        engine.update_vix(20.0)
        assert engine.get_adjusted_threshold(65) == 65
