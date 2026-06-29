"""
Tests for core/data_quality_monitor.py - Enhanced DataQualityMonitor.

Covers:
  - DataQualityConfig dataclass defaults (existing + new fields)
  - DataQualityMonitor init
  - check_price_anomaly (disabled, price spike, volume spike, wide spread)
  - check_data_freshness (staleness, gaps)
  - check_completeness (missing fields, None values)
  - check_schema (type validation, range validation)
  - health_summary
  - reset
  - create_data_quality_monitor convenience function
"""

from __future__ import annotations

import time

from core.data_quality_monitor import (
    DataQualityConfig,
    DataQualityFinding,
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
        assert c.zscore_threshold == 3.0
        assert c.rolling_window_size == 20
        assert c.max_data_age_seconds == 60.0

    def test_custom_values(self):
        c = DataQualityConfig(
            enabled=False,
            max_price_change_pct=0.10,
            volume_spike_mult=10.0,
            max_spread_pct=0.05,
            zscore_threshold=2.5,
        )
        assert c.enabled is False
        assert c.max_price_change_pct == 0.10
        assert c.volume_spike_mult == 10.0
        assert c.max_spread_pct == 0.05
        assert c.zscore_threshold == 2.5


# ═══════════════════════════════════════════════════════════════════════
#  Initialization
# ═══════════════════════════════════════════════════════════════════════


class TestInitialization:
    def test_default_config(self):
        m = DataQualityMonitor(DataQualityConfig())
        assert m.config.enabled is True
        assert m._last_price is None
        assert m._last_volume is None
        assert len(m._price_window) == 0

    def test_custom_config(self):
        cfg = DataQualityConfig(enabled=False)
        m = DataQualityMonitor(cfg)
        assert m.config.enabled is False

    def test_rolling_window_size_respected(self):
        m = DataQualityMonitor(DataQualityConfig(rolling_window_size=5))
        for i in range(10):
            m.check_price_anomaly(100.0 + i, 1000, 99.5, 100.5)
        assert len(m._price_window) == 5  # Max size respected


# ═══════════════════════════════════════════════════════════════════════
#  check_price_anomaly - Disabled
# ═══════════════════════════════════════════════════════════════════════


class TestCheckPriceAnomalyDisabled:
    def test_disabled_returns_empty(self):
        m = DataQualityMonitor(DataQualityConfig(enabled=False))
        findings = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert findings == []

    def test_disabled_does_not_update_state(self):
        m = DataQualityMonitor(DataQualityConfig(enabled=False))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert m._last_price is None  # Not updated when disabled

    def test_disabled_returns_data_quality_finding_list(self):
        m = DataQualityMonitor(DataQualityConfig(enabled=False))
        findings = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert isinstance(findings, list)


# ═══════════════════════════════════════════════════════════════════════
#  check_price_anomaly - Price spike
# ═══════════════════════════════════════════════════════════════════════


class TestPriceSpike:
    def test_first_call_no_previous_price(self):
        """No previous price to compare against, so no anomaly."""
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        findings = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert len(findings) == 0
        assert m._last_price == 100.0

    def test_normal_price_change(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # 4.5% change from 100 -> 104.5 -- within 5% threshold
        findings = m.check_price_anomaly(104.5, 1000, 104.0, 105.0)
        # Should have no PRICE findings
        price_findings = [f for f in findings if f.category == "PRICE"]
        assert len(price_findings) == 0

    def test_price_spike_detected(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # 10% change from 100 -> 110 -- exceeds 5% threshold
        findings = m.check_price_anomaly(110.0, 1000, 109.5, 110.5)
        price_findings = [f for f in findings if f.category == "PRICE"]
        assert len(price_findings) >= 1
        assert "PRICE" in price_findings[0].category
        assert "10.00%" in price_findings[0].message

    def test_price_drop_detected(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # 10% drop from 100 -> 90 -- exceeds 5% threshold
        findings = m.check_price_anomaly(90.0, 1000, 89.5, 90.5)
        price_findings = [f for f in findings if f.category == "PRICE"]
        assert len(price_findings) >= 1

    def test_previous_price_zero_skips_check(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        m._last_price = 0.0
        findings = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        price_findings = [f for f in findings if f.category == "PRICE"]
        assert len(price_findings) == 0

    def test_finding_has_correct_attributes(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        findings = m.check_price_anomaly(110.0, 1000, 109.5, 110.5)
        price_findings = [f for f in findings if f.category == "PRICE"]
        assert len(price_findings) >= 1
        f = price_findings[0]
        assert f.category == "PRICE"
        assert f.severity in ("INFO", "WARN", "ERROR", "CRITICAL")
        assert f.value is not None
        assert f.threshold is not None
        assert f.timestamp is not None


# ═══════════════════════════════════════════════════════════════════════
#  check_price_anomaly - Volume spike
# ═══════════════════════════════════════════════════════════════════════


class TestVolumeSpike:
    def test_first_call_no_previous_volume(self):
        m = DataQualityMonitor(DataQualityConfig(volume_spike_mult=5.0))
        findings = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert len([f for f in findings if f.category == "VOLUME"]) == 0

    def test_normal_volume(self):
        m = DataQualityMonitor(DataQualityConfig(volume_spike_mult=5.0))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # 2000 is 2x normal -- within 5x threshold
        findings = m.check_price_anomaly(100.0, 2000, 99.5, 100.5)
        vol_findings = [f for f in findings if f.category == "VOLUME"]
        assert len(vol_findings) == 0

    def test_volume_spike_detected(self):
        m = DataQualityMonitor(DataQualityConfig(volume_spike_mult=5.0))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # 6000 is 6x normal -- exceeds 5x threshold
        findings = m.check_price_anomaly(100.0, 6000, 99.5, 100.5)
        vol_findings = [f for f in findings if f.category == "VOLUME"]
        assert len(vol_findings) >= 1
        assert "spike" in vol_findings[0].message.lower()

    def test_previous_volume_zero_skips_check(self):
        m = DataQualityMonitor(DataQualityConfig(volume_spike_mult=5.0))
        m._last_volume = 0.0
        findings = m.check_price_anomaly(100.0, 6000, 99.5, 100.5)
        vol_findings = [f for f in findings if f.category == "VOLUME"]
        assert len(vol_findings) == 0


# ═══════════════════════════════════════════════════════════════════════
#  check_price_anomaly - Wide spread
# ═══════════════════════════════════════════════════════════════════════


class TestWideSpread:
    def test_normal_spread(self):
        m = DataQualityMonitor(DataQualityConfig(max_spread_pct=0.03))
        findings = m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        spread_findings = [f for f in findings if f.category == "SPREAD"]
        # Spread = (100.5 - 99.5) / 99.5 ~= 1.005% -- within 3%
        assert len(spread_findings) == 0

    def test_wide_spread_detected(self):
        m = DataQualityMonitor(DataQualityConfig(max_spread_pct=0.03))
        findings = m.check_price_anomaly(100.0, 1000, 98.0, 105.0)
        spread_findings = [f for f in findings if f.category == "SPREAD"]
        # Spread = (105 - 98) / 98 ~= 7.14% -- exceeds 3%
        assert len(spread_findings) >= 1
        assert "spread" in spread_findings[0].message.lower()

    def test_bid_zero_or_negative_skips_spread_check(self):
        m = DataQualityMonitor(DataQualityConfig(max_spread_pct=0.03))
        findings = m.check_price_anomaly(100.0, 1000, 0, 100.5)
        spread_findings = [f for f in findings if f.category == "SPREAD"]
        assert len(spread_findings) == 0

    def test_ask_zero_or_negative_skips_spread_check(self):
        m = DataQualityMonitor(DataQualityConfig(max_spread_pct=0.03))
        findings = m.check_price_anomaly(100.0, 1000, 99.5, 0)
        spread_findings = [f for f in findings if f.category == "SPREAD"]
        assert len(spread_findings) == 0


# ═══════════════════════════════════════════════════════════════════════
#  check_data_freshness
# ═══════════════════════════════════════════════════════════════════════


class TestDataFreshness:
    def test_fresh_data_no_findings(self):
        m = DataQualityMonitor(DataQualityConfig(max_data_age_seconds=60.0))
        findings = m.check_data_freshness(time.time() - 5)
        freshness_findings = [f for f in findings if f.category == "FRESHNESS"]
        assert len(freshness_findings) == 0

    def test_stale_data_detected(self):
        m = DataQualityMonitor(DataQualityConfig(max_data_age_seconds=10.0))
        findings = m.check_data_freshness(time.time() - 20)
        freshness_findings = [f for f in findings if f.category == "FRESHNESS"]
        assert len(freshness_findings) >= 1

    def test_disabled_returns_empty(self):
        m = DataQualityMonitor(DataQualityConfig(enabled=False))
        findings = m.check_data_freshness(time.time() - 100)
        assert findings == []


# ═══════════════════════════════════════════════════════════════════════
#  check_completeness
# ═══════════════════════════════════════════════════════════════════════


class TestCompleteness:
    def test_complete_data_no_findings(self):
        m = DataQualityMonitor(DataQualityConfig())
        # Pass only the subset of fields we provide to avoid completeness hits
        findings = m.check_completeness({
            "last_price": 100.0,
            "symbol": "NIFTY",
            "volume": 1000,
        }, required_fields=["last_price", "symbol", "volume"])
        assert len(findings) == 0

    def test_missing_field_detected(self):
        m = DataQualityMonitor(DataQualityConfig())
        findings = m.check_completeness({"last_price": 100.0})
        missing_fields = [f for f in findings if f.category == "COMPLETENESS"]
        assert len(missing_fields) >= 1
        assert "symbol" in findings[0].message or "missing" in findings[0].message.lower()

    def test_none_value_detected(self):
        m = DataQualityMonitor(DataQualityConfig())
        findings = m.check_completeness({
            "last_price": 100.0,
            "symbol": None,
        })
        none_findings = [f for f in findings if f.category == "COMPLETENESS"]
        assert len(none_findings) >= 1


# ═══════════════════════════════════════════════════════════════════════
#  check_schema
# ═══════════════════════════════════════════════════════════════════════


class TestSchema:
    def test_valid_schema_no_findings(self):
        m = DataQualityMonitor(DataQualityConfig())
        findings = m.check_schema({
            "last_price": 100.0,
            "symbol": "NIFTY",
        })
        assert len(findings) == 0

    def test_type_mismatch_detected(self):
        m = DataQualityMonitor(DataQualityConfig())
        findings = m.check_schema({
            "last_price": "not_a_number",
            "symbol": "NIFTY",
        }, schema={"last_price": (int, float), "symbol": str})
        schema_findings = [f for f in findings if f.category == "SCHEMA"]
        assert len(schema_findings) >= 1

    def test_negative_price_detected(self):
        m = DataQualityMonitor(DataQualityConfig())
        findings = m.check_schema({"last_price": -1.0, "symbol": "NIFTY"})
        schema_findings = [f for f in findings if f.category == "SCHEMA"]
        assert len(schema_findings) >= 1


# ═══════════════════════════════════════════════════════════════════════
#  Multiple findings
# ═══════════════════════════════════════════════════════════════════════


class TestMultipleFindings:
    def test_price_and_volume_checked(self):
        m = DataQualityMonitor(DataQualityConfig(
            max_price_change_pct=0.02, volume_spike_mult=2.0
        ))
        # First call -- no baseline
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        # Second call -- 15% price spike AND 5x volume spike
        findings = m.check_price_anomaly(115.0, 5000, 98.0, 116.0)
        categories = {f.category for f in findings}
        assert "PRICE" in categories or "STATISTICAL" in categories

    def test_multiple_categories_can_be_returned(self):
        m = DataQualityMonitor(DataQualityConfig(
            max_price_change_pct=0.02, volume_spike_mult=2.0, max_spread_pct=0.02
        ))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        findings = m.check_price_anomaly(115.0, 5000, 95.0, 118.0)
        # At minimum, PRICE should be flagged
        price_findings = [f for f in findings if f.category == "PRICE"]
        assert len(price_findings) >= 1


# ═══════════════════════════════════════════════════════════════════════
#  health_summary
# ═══════════════════════════════════════════════════════════════════════


class TestHealthSummary:
    def test_health_summary_returns_dict(self):
        m = DataQualityMonitor(DataQualityConfig())
        summary = m.health_summary()
        assert isinstance(summary, dict)
        assert "total_checks" in summary
        assert "total_findings" in summary
        assert "finding_rate_pct" in summary
        assert "rolling_window_size" in summary

    def test_health_summary_tracks_checks(self):
        m = DataQualityMonitor(DataQualityConfig(enabled=True))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        m.check_data_freshness(time.time() - 5)
        # check_price_anomaly increments total_checks by 1
        # check_data_freshness does NOT increment total_checks
        summary = m.health_summary()
        assert summary["total_checks"] >= 1


# ═══════════════════════════════════════════════════════════════════════
#  reset
# ═══════════════════════════════════════════════════════════════════════


class TestReset:
    def test_reset_clears_all_state(self):
        m = DataQualityMonitor(DataQualityConfig())
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        assert m._last_price == 100.0
        assert m._last_volume == 1000.0
        m.reset()
        assert m._last_price is None
        assert m._last_volume is None
        assert len(m._price_window) == 0

    def test_reset_allows_fresh_detection(self):
        m = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.05))
        m.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        findings = m.check_price_anomaly(120.0, 6000, 119.5, 120.5)
        assert len([f for f in findings if f.category == "PRICE"]) >= 1
        m.reset()
        # After reset, first call is fresh baseline -- no anomaly
        findings = m.check_price_anomaly(130.0, 8000, 129.5, 130.5)
        assert len([f for f in findings if f.category == "PRICE"]) == 0

    def test_reset_clears_pending_gap_detection(self):
        m = DataQualityMonitor(DataQualityConfig(max_data_age_seconds=5.0))
        # Trigger a gap detection by passing very old timestamp
        m.check_data_freshness(time.time() - 10)  # first call - stale
        original_findings = m.check_data_freshness(time.time() - 10)  # second call - gap detected
        assert len([f for f in original_findings if f.category == "FRESHNESS"]) >= 1
        m.reset()
        # After reset, gap detection resets too
        # First call after reset should establish baseline with fresh data
        m.check_data_freshness(time.time() - 2)  # fresh
        findings = m.check_data_freshness(time.time() - 2)  # still fresh
        assert len([f for f in findings if f.category == "FRESHNESS"]) == 0


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

    def test_new_config_keys_supported(self):
        m = create_data_quality_monitor({
            "data_quality_zscore_threshold": 2.5,
            "data_quality_rolling_window": 50,
        })
        assert m.config.zscore_threshold == 2.5
        assert m.config.rolling_window_size == 50


# ═══════════════════════════════════════════════════════════════════════
#  DataQualityFinding dataclass
# ═══════════════════════════════════════════════════════════════════════


class TestDataQualityFinding:
    def test_default_timestamp(self):
        f = DataQualityFinding(category="TEST", severity="INFO", message="test")
        assert f.timestamp is not None
        assert "T" in f.timestamp  # ISO format

    def test_finding_fields(self):
        f = DataQualityFinding(
            category="PRICE",
            severity="WARN",
            message="Price spike detected",
            value=0.10,
            threshold=0.05,
        )
        assert f.category == "PRICE"
        assert f.severity == "WARN"
        assert f.value == 0.10
        assert f.threshold == 0.05
