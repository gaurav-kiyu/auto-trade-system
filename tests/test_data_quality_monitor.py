"""
Tests for core/data_quality_monitor.py - DataQualityMonitor.

Covers:
  - DataQualityConfig dataclass defaults
  - DataQualityMonitor init
  - check_price_anomaly (disabled, price spike, volume spike, wide spread)
  - reset
  - create_data_quality_monitor convenience function
"""

from __future__ import annotations


from core.data_quality_monitor import (
    DataQualityConfig,
    DataQualityMonitor,
    create_data_quality_monitor,
)


# ═══════════════════════════════════════════════════════════════════════
#  DataQualityConfig
# ═══════════════════════════════════════════════════════════════════════


class TestDataQualityConfig:
    def test_defaults(self):
        c = DataQualityConfig()
        assert c.enabled is True
        assert c.max_price_change_pct == 0.05
        assert c.volume_spike_mult == 5.0
        assert c.max_spread_pct == 0.03

    def test_custom_values(self):
        c = DataQualityConfig(
            enabled=False,
            max_price_change_pct=0.10,
            volume_spike_mult=10.0,
            max_spread_pct=0.05,
        )
        assert c.enabled is False
        assert c.max_price_change_pct == 0.10
        assert c.volume_spike_mult == 10.0
        assert c.max_spread_pct == 0.05


# ═══════════════════════════════════════════════════════════════════════
#  Initialization
# ═══════════════════════════════════════════════════════════════════════


class TestInitialization:
    def test_default_config(self):
        m = DataQualityMonitor(DataQualityConfig())
        assert m.config.enabled is True
        assert m._last_price is None
        assert m._last_volume is None

    def test_custom_config(self):
        cfg = DataQualityConfig(enabled=False)
        m = DataQualityMonitor(cfg)
        assert m.config.enabled is False


# ═══════════════════════════════════════════════════════════════════════
#  check_price_anomaly - Disabled
# ═══════════════════════════════════════════════════════════════════════


class TestCheckPriceAnomalyDisabled:
    def test_disabled_returns_no_anomaly(self):
        m = DataQualityMonitor(DataQualityConfig(enabled=False))
        is_anomaly, reason = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert is_anomaly is False
        assert reason == ""

    def test_disabled_does_not_update_state(self):
        m = DataQualityMonitor(DataQualityConfig(enabled=False))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert m._last_price is None  # Not updated when disabled


# ═══════════════════════════════════════════════════════════════════════
#  check_price_anomaly - Price spike
# ═══════════════════════════════════════════════════════════════════════


class TestPriceSpike:
    def test_first_call_no_previous_price(self):
        """No previous price to compare against, so no anomaly."""
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        is_anomaly, reason = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert is_anomaly is False
        assert m._last_price == 100.0

    def test_normal_price_change(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # 4.5% change from 100 → 104.5 — within 5% threshold
        is_anomaly, reason = m.check_price_anomaly(104.5, 1000, 104.0, 105.0)
        assert is_anomaly is False

    def test_price_spike_detected(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # 10% change from 100 → 110 — exceeds 5% threshold
        is_anomaly, reason = m.check_price_anomaly(110.0, 1000, 109.5, 110.5)
        assert is_anomaly is True
        assert "PRICE SPIKE" in reason
        assert "10.00%" in reason

    def test_price_drop_detected(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # 10% drop from 100 → 90 — exceeds 5% threshold
        is_anomaly, reason = m.check_price_anomaly(90.0, 1000, 89.5, 90.5)
        assert is_anomaly is True
        assert "PRICE SPIKE" in reason

    def test_previous_price_zero_skips_check(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        m._last_price = 0.0
        # Division by zero guard — last_price is 0, so abs diff / 0 would be inf
        is_anomaly, reason = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert is_anomaly is False

    def test_previous_price_none_skips_check(self):
        # First call with last_price = None
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        is_anomaly, reason = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert is_anomaly is False


# ═══════════════════════════════════════════════════════════════════════
#  check_price_anomaly - Volume spike
# ═══════════════════════════════════════════════════════════════════════


class TestVolumeSpike:
    def test_first_call_no_previous_volume(self):
        m = DataQualityMonitor(DataQualityConfig(volume_spike_mult=5.0))
        is_anomaly, reason = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert is_anomaly is False

    def test_normal_volume(self):
        m = DataQualityMonitor(DataQualityConfig(volume_spike_mult=5.0))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # 2000 is 2x normal — within 5x threshold
        is_anomaly, reason = m.check_price_anomaly(100.0, 2000, 99.5, 100.5)
        assert is_anomaly is False

    def test_volume_spike_detected(self):
        m = DataQualityMonitor(DataQualityConfig(volume_spike_mult=5.0))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # 6000 is 6x normal — exceeds 5x threshold
        is_anomaly, reason = m.check_price_anomaly(100.0, 6000, 99.5, 100.5)
        assert is_anomaly is True
        assert "VOLUME SPIKE" in reason
        assert "6.0x" in reason

    def test_previous_volume_zero_skips_check(self):
        m = DataQualityMonitor(DataQualityConfig(volume_spike_mult=5.0))
        m._last_volume = 0.0
        # Division by zero guard
        is_anomaly, reason = m.check_price_anomaly(100.0, 6000, 99.5, 100.5)
        assert is_anomaly is False


# ═══════════════════════════════════════════════════════════════════════
#  check_price_anomaly - Wide spread
# ═══════════════════════════════════════════════════════════════════════


class TestWideSpread:
    def test_normal_spread(self):
        m = DataQualityMonitor(DataQualityConfig(max_spread_pct=0.03))
        is_anomaly, reason = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # Spread = (100.5 - 99.5) / 99.5 ≈ 1.005% — within 3%
        assert is_anomaly is False

    def test_wide_spread_detected(self):
        m = DataQualityMonitor(DataQualityConfig(max_spread_pct=0.03))
        is_anomaly, reason = m.check_price_anomaly(100.0, 1000, 98.0, 105.0)
        # Spread = (105 - 98) / 98 ≈ 7.14% — exceeds 3%
        assert is_anomaly is True
        assert "WIDE SPREAD" in reason

    def test_bid_zero_or_negative_skips_spread_check(self):
        m = DataQualityMonitor(DataQualityConfig(max_spread_pct=0.03))
        is_anomaly, reason = m.check_price_anomaly(100.0, 1000, 0, 100.5)
        assert is_anomaly is False

    def test_ask_zero_or_negative_skips_spread_check(self):
        m = DataQualityMonitor(DataQualityConfig(max_spread_pct=0.03))
        is_anomaly, reason = m.check_price_anomaly(100.0, 1000, 99.5, 0)
        assert is_anomaly is False

    def test_bid_ask_both_zero_skips_spread_check(self):
        m = DataQualityMonitor(DataQualityConfig(max_spread_pct=0.03))
        is_anomaly, reason = m.check_price_anomaly(100.0, 1000, 0, 0)
        assert is_anomaly is False


# ═══════════════════════════════════════════════════════════════════════
#  Multiple anomalies (annotations checked)
# ═══════════════════════════════════════════════════════════════════════


class TestMultipleAnomalies:
    def test_price_and_volume_checked(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.02, volume_spike_mult=2.0))
        # First call — no baseline
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # Second call — 15% price spike (exceeds 2%) AND 5x volume spike (exceeds 2x)
        is_anomaly, reason = m.check_price_anomaly(115.0, 5000, 98.0, 116.0)
        # Price check happens first, so that's the reported anomaly
        assert is_anomaly is True
        assert "PRICE SPIKE" in reason

    def test_price_and_spread_checked(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.02, max_spread_pct=0.02))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # Normal price (101 = 1% change), wide spread (8%)
        is_anomaly, reason = m.check_price_anomaly(101.0, 1000, 95.0, 103.0)
        # Price OK, volume OK (same), spread anomalous
        assert is_anomaly is True
        assert "WIDE SPREAD" in reason


# ═══════════════════════════════════════════════════════════════════════
#  reset
# ═══════════════════════════════════════════════════════════════════════


class TestReset:
    def test_reset_clears_last_price_and_volume(self):
        m = DataQualityMonitor(DataQualityConfig())
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert m._last_price == 100.0
        assert m._last_volume == 1000.0
        m.reset()
        assert m._last_price is None
        assert m._last_volume is None

    def test_reset_allows_fresh_anomaly_detection(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # Would detect anomaly against previous 100
        is_anomaly, reason = m.check_price_anomaly(120.0, 6000, 119.5, 120.5)
        assert is_anomaly is True
        m.reset()
        # After reset, first call is fresh baseline — no anomaly
        is_anomaly, reason = m.check_price_anomaly(130.0, 8000, 129.5, 130.5)
        assert is_anomaly is False


# ═══════════════════════════════════════════════════════════════════════
#  create_data_quality_monitor convenience function
# ═══════════════════════════════════════════════════════════════════════


class TestCreateDataQualityMonitor:
    def test_default_config_creation(self):
        m = create_data_quality_monitor({})
        assert isinstance(m, DataQualityMonitor)
        assert m.config.enabled is True
        assert m.config.max_price_change_pct == 0.05

    def test_custom_config_creation(self):
        m = create_data_quality_monitor({
            "DATA_ANOMALY_DETECTION_ENABLED": False,
            "DATA_ANOMALY_PRICE_CHANGE_MAX_PCT": 0.10,
        })
        assert m.config.enabled is False
        assert m.config.max_price_change_pct == 0.10

    def test_partial_config_preserves_defaults(self):
        m = create_data_quality_monitor({
            "DATA_ANOMALY_VOLUME_SPIKE_MULT": 10.0,
        })
        assert m.config.volume_spike_mult == 10.0
        assert m.config.max_price_change_pct == 0.05  # default preserved
        assert m.config.max_spread_pct == 0.03  # default preserved
