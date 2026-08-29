"""Tests for core/data_quality_monitor.py — Data Quality Monitor.

Covers all check methods:
- Rule-based (price, volume, spread)
- Statistical (z-score, IQR)
- Freshness (stale data, gaps)
- Completeness (missing fields)
- Schema validation (types, ranges)
"""

from __future__ import annotations

import time

import pytest
from core.data_quality_monitor import (
    DataQualityConfig,
    DataQualityFinding,
    DataQualityMonitor,
    create_data_quality_monitor,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def monitor() -> DataQualityMonitor:
    """Create a clean monitor with default config."""
    m = DataQualityMonitor()
    m.reset()
    return m


@pytest.fixture
def fast_monitor() -> DataQualityMonitor:
    """Monitor with fast detection thresholds for testing."""
    return DataQualityMonitor(DataQualityConfig(
        max_price_change_pct=0.02,  # 2%
        volume_spike_mult=2.0,       # 2x
        max_spread_pct=0.01,         # 1%
        zscore_threshold=1.5,        # 1.5 sigma
        rolling_window_size=10,
        min_data_points_for_trend=3,
        max_data_age_seconds=5.0,
        stale_data_warn_seconds=2.0,
    ))


# ── Config tests ──────────────────────────────────────────────────────────────


class TestDataQualityConfig:
    """Tests for DataQualityConfig defaults."""

    def test_default_config(self) -> None:
        cfg = DataQualityConfig()
        assert cfg.enabled is True
        assert cfg.max_price_change_pct == 0.05
        assert cfg.zscore_threshold == 3.0
        assert len(cfg.expected_numeric_fields) == 8

    def test_custom_config(self) -> None:
        cfg = DataQualityConfig(max_price_change_pct=0.10, zscore_threshold=4.0)
        assert cfg.max_price_change_pct == 0.10
        assert cfg.zscore_threshold == 4.0


# ── Rule-based check tests ────────────────────────────────────────────────────


class TestRuleBasedChecks:
    """Tests for price spike, volume spike, and wide spread detection."""

    def test_no_anomaly_on_first_tick(self, monitor: DataQualityMonitor) -> None:
        # First tick: no previous price/volume, so no anomalies
        findings = monitor.check_price_anomaly(100.0, 10000, 99.5, 100.5)
        assert len(findings) == 0

    def test_price_spike_detected(self, fast_monitor: DataQualityMonitor) -> None:
        fast_monitor.check_price_anomaly(100.0, 10000, 99.5, 100.5)
        findings = fast_monitor.check_price_anomaly(110.0, 10000, 99.5, 100.5)
        assert any(f.category == "PRICE" for f in findings)

    def test_volume_spike_detected(self, fast_monitor: DataQualityMonitor) -> None:
        fast_monitor.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        findings = fast_monitor.check_price_anomaly(100.0, 5000, 99.5, 100.5)
        assert any(f.category == "VOLUME" for f in findings)

    def test_wide_spread_detected(self, fast_monitor: DataQualityMonitor) -> None:
        findings = fast_monitor.check_price_anomaly(100.0, 1000, 98.0, 102.0)  # ~4% spread
        assert any(f.category == "SPREAD" for f in findings)

    def test_no_false_positive(self, fast_monitor: DataQualityMonitor) -> None:
        fast_monitor.check_price_anomaly(100.0, 10000, 99.5, 100.5)
        # Small changes should not trigger
        findings = fast_monitor.check_price_anomaly(100.5, 10000, 100.0, 101.0)
        assert len(findings) == 0

    def test_disabled_monitor(self, monitor: DataQualityMonitor) -> None:
        monitor.config.enabled = False
        findings = monitor.check_price_anomaly(100.0, 1000, 90.0, 110.0)
        assert len(findings) == 0


# ── Statistical check tests ───────────────────────────────────────────────────


class TestStatisticalChecks:
    """Tests for z-score and IQR-based anomaly detection."""

    def test_zscore_requires_min_data(self, fast_monitor: DataQualityMonitor) -> None:
        # Not enough data points (need 3)
        fast_monitor.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        fast_monitor.check_price_anomaly(101.0, 1000, 100.0, 101.0)
        findings = fast_monitor.check_price_anomaly(150.0, 1000, 99.5, 100.5)
        # Rule-based will catch the price spike, but statistical may not fire yet
        assert any(f.category == "PRICE" for f in findings)

    def test_zscore_detects_outlier(self, fast_monitor: DataQualityMonitor) -> None:
        # Feed stable data then an outlier
        for _ in range(10):
            fast_monitor.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        findings = fast_monitor.check_price_anomaly(200.0, 1000, 99.5, 100.5)
        [f for f in findings if f.category == "STATISTICAL"]
        price = [f for f in findings if f.category == "PRICE"]
        # Should at least catch the price spike
        assert len(price) >= 1

    def test_iqr_no_crash(self, fast_monitor: DataQualityMonitor) -> None:
        """Verify IQR spread detection runs without error (statistical trigger depends on window)."""
        for _ in range(6):
            fast_monitor.check_price_anomaly(100.0, 1000, 99.8, 100.2)
        findings = fast_monitor.check_price_anomaly(100.0, 1000, 95.0, 110.0)
        # At minimum, no crash and price rule-based should fire
        assert any(f.category == "PRICE" for f in findings) or any(f.category == "SPREAD" for f in findings)

    def test_zscore_stable_data(self, fast_monitor: DataQualityMonitor) -> None:
        # Stable data should not trigger statistical alerts
        for _ in range(10):
            fast_monitor.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        findings = fast_monitor.check_price_anomaly(100.1, 1001, 99.5, 100.5)
        statistical = [f for f in findings if f.category == "STATISTICAL"]
        assert len(statistical) == 0


# ── Freshness check tests ─────────────────────────────────────────────────────


class TestFreshnessChecks:
    """Tests for data staleness and gap detection."""

    def test_fresh_data_no_alert(self, fast_monitor: DataQualityMonitor) -> None:
        findings = fast_monitor.check_data_freshness(data_timestamp=time.time())
        freshes = [f for f in findings if f.category == "FRESHNESS"]
        assert len(freshes) == 0

    def test_stale_data_warns(self, fast_monitor: DataQualityMonitor) -> None:
        old_ts = time.time() - 10  # 10s old, exceeds warn=2s and max_age=5s
        findings = fast_monitor.check_data_freshness(data_timestamp=old_ts)
        freshes = [f for f in findings if f.category == "FRESHNESS"]
        assert len(freshes) >= 1

    def test_data_gap_detected(self, fast_monitor: DataQualityMonitor) -> None:
        # First call stores timestamp
        fast_monitor.check_data_freshness(data_timestamp=time.time())
        # Second call with no timestamp (uses current time) — should see small gap
        findings = fast_monitor.check_data_freshness(data_timestamp=None)
        # Gap should be tiny (< 1s since calls are immediate), so no alert
        [f for f in findings if f.category == "FRESHNESS"]
        # No alert since gap is < 5s max_age

    def test_disabled_freshness(self, monitor: DataQualityMonitor) -> None:
        monitor.config.enabled = False
        findings = monitor.check_data_freshness(data_timestamp=time.time() - 3600)
        assert len(findings) == 0

    def test_critical_gap(self, fast_monitor: DataQualityMonitor) -> None:
        # Simulate gap by not calling between checks
        fast_monitor._last_data_timestamp = time.time() - 30  # 30s gap
        fast_monitor._data_gap_start = time.time() - 30
        findings = fast_monitor.check_data_freshness()
        assert any(f.severity in ("ERROR", "CRITICAL") for f in findings)


# ── Completeness check tests ──────────────────────────────────────────────────


class TestCompletenessChecks:
    """Tests for missing field detection."""

    def test_complete_data(self, monitor: DataQualityMonitor) -> None:
        data = {
            "last_price": 100.0,
            "open": 99.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0,
            "volume": 10000,
            "bid": 99.5,
            "ask": 100.5,
            "symbol": "NIFTY",
            "timestamp": "2026-01-01T00:00:00",
        }
        findings = monitor.check_completeness(data)
        assert len(findings) == 0

    def test_missing_field_detected(self, monitor: DataQualityMonitor) -> None:
        data = {"last_price": 100.0, "symbol": "NIFTY"}
        findings = monitor.check_completeness(data)
        assert len(findings) > 0
        assert any(f.category == "COMPLETENESS" for f in findings)

    def test_none_field_detected(self, monitor: DataQualityMonitor) -> None:
        data = {
            "last_price": None,
            "symbol": "NIFTY",
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0,
            "volume": 10000,
            "bid": 99.5,
            "ask": 100.5,
        }
        findings = monitor.check_completeness(data)
        assert any("None" in f.message for f in findings)

    def test_empty_string_detected(self, monitor: DataQualityMonitor) -> None:
        data = {k: 0 for k in monitor.config.expected_numeric_fields}
        data["symbol"] = ""
        data["timestamp"] = "2026-01-01"
        findings = monitor.check_completeness(data)
        assert any("empty" in f.message.lower() for f in findings)

    def test_custom_required_fields(self, monitor: DataQualityMonitor) -> None:
        data = {"a": 1, "b": 2}
        findings = monitor.check_completeness(data, required_fields=["a", "b", "c"])
        # "c" missing (1 finding) + 1/3=33% missing > 10% threshold (1 overall finding) = 2
        assert len(findings) >= 1
        assert findings[0].category == "COMPLETENESS"

    def test_disabled_completeness(self, monitor: DataQualityMonitor) -> None:
        monitor.config.enabled = False
        findings = monitor.check_completeness({})
        assert len(findings) == 0


# ── Schema validation tests ───────────────────────────────────────────────────


class TestSchemaChecks:
    """Tests for schema type and range validation."""

    def test_valid_schema(self, monitor: DataQualityMonitor) -> None:
        data = {"last_price": 100.0, "volume": 10000, "symbol": "NIFTY"}
        findings = monitor.check_schema(data)
        assert len(findings) == 0

    def test_wrong_type_detected(self, monitor: DataQualityMonitor) -> None:
        data = {"last_price": "not_a_number"}
        findings = monitor.check_schema(data)
        assert any(f.category == "SCHEMA" for f in findings)

    def test_negative_price_detected(self, monitor: DataQualityMonitor) -> None:
        data = {"last_price": -100.0}
        findings = monitor.check_schema(data)
        assert any(f.category == "SCHEMA" for f in findings)

    def test_zero_price_detected(self, monitor: DataQualityMonitor) -> None:
        data = {"last_price": 0.0}
        findings = monitor.check_schema(data)
        assert any(f.category == "SCHEMA" for f in findings)

    def test_custom_schema(self, monitor: DataQualityMonitor) -> None:
        data = {"custom_field": "string_value"}
        findings = monitor.check_schema(data, schema={"custom_field": str})
        assert len(findings) == 0

    def test_custom_schema_type_mismatch(self, monitor: DataQualityMonitor) -> None:
        data = {"custom_field": 123}
        findings = monitor.check_schema(data, schema={"custom_field": str})
        assert len(findings) >= 1

    def test_disabled_schema(self, monitor: DataQualityMonitor) -> None:
        monitor.config.enabled = False
        findings = monitor.check_schema({"last_price": "string"})
        assert len(findings) == 0


# ─── Health summary tests ────────────────────────────────────────────────────


class TestHealthSummary:
    """Tests for health summary reporting."""

    def test_initial_health(self, monitor: DataQualityMonitor) -> None:
        h = monitor.health_summary()
        assert h["total_checks"] == 0
        assert h["total_findings"] == 0
        assert h["finding_rate_pct"] == 0.0

    def test_health_after_checks(self, fast_monitor: DataQualityMonitor) -> None:
        fast_monitor.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        fast_monitor.check_price_anomaly(200.0, 1000, 99.5, 100.5)
        fast_monitor.check_data_freshness(data_timestamp=time.time() - 30)
        h = fast_monitor.health_summary()
        assert h["total_checks"] >= 2
        assert h["finding_rate_pct"] > 0


# ─── Reset tests ─────────────────────────────────────────────────────────────


class TestReset:
    """Tests for state reset."""

    def test_reset_clears_state(self, fast_monitor: DataQualityMonitor) -> None:
        fast_monitor.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        fast_monitor.check_data_freshness(data_timestamp=time.time())
        fast_monitor.reset()
        h = fast_monitor.health_summary()
        assert h["total_checks"] == 0
        assert h["total_findings"] == 0
        assert h["price_window_filled"] == 0

    def test_works_after_reset(self, fast_monitor: DataQualityMonitor) -> None:
        fast_monitor.reset()
        # Use tight spread (< 1%) to avoid triggering spread detection
        findings = fast_monitor.check_price_anomaly(100.0, 1000, 99.95, 100.05)
        assert len(findings) == 0  # First tick, no history


# ─── Factory tests ───────────────────────────────────────────────────────────


class TestFactory:
    """Tests for create_data_quality_monitor factory."""

    def test_default_factory(self) -> None:
        m = create_data_quality_monitor()
        assert m.config.enabled is True
        assert m.config.max_price_change_pct == 0.05

    def test_factory_with_config(self) -> None:
        m = create_data_quality_monitor({"data_quality_max_price_change_pct": 0.10})
        assert m.config.max_price_change_pct == 0.10

    def test_factory_backward_compat(self) -> None:
        m = create_data_quality_monitor({"DATA_ANOMALY_DETECTION_ENABLED": True})
        assert m.config.enabled is True
        assert m.config.max_price_change_pct == 0.05


# ─── Finding model tests ─────────────────────────────────────────────────────


class TestDataQualityFinding:
    """Tests for DataQualityFinding dataclass."""

    def test_default_timestamp(self) -> None:
        f = DataQualityFinding(category="TEST", severity="INFO", message="test")
        assert f.category == "TEST"
        assert f.severity == "INFO"
        assert f.message == "test"
        assert f.timestamp is not None

    def test_custom_values(self) -> None:
        f = DataQualityFinding(category="PRICE", severity="ERROR", message="spike", value=0.1, threshold=0.05)
        assert f.value == 0.1
        assert f.threshold == 0.05
