"""Tests for core.anomaly_detector — z-score anomaly detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.anomaly_detector import AnomalyDetector, detect_anomaly


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def detector(tmp_path: Path) -> AnomalyDetector:
    """Create a detector with a temp history file and tight threshold for testing."""
    return AnomalyDetector(
        history_file=str(tmp_path / "anomaly_history.json"),
        window_size=10,
        z_threshold=2.0,  # Lower threshold for easier testing
    )


# ── Construction tests ───────────────────────────────────────────────────────

class TestAnomalyDetectorConstruction:
    """Test detector initialization."""

    def test_default_params(self):
        d = AnomalyDetector()
        assert d.window_size == 100
        assert d.z_threshold == 3.0
        assert d.history_file.name == "anomaly_history.json"

    def test_custom_params(self, tmp_path: Path):
        d = AnomalyDetector(
            history_file=str(tmp_path / "custom.json"),
            window_size=50,
            z_threshold=2.5,
        )
        assert d.window_size == 50
        assert d.z_threshold == 2.5
        assert d.history_file.name == "custom.json"

    def test_init_loads_existing_history(self, tmp_path: Path):
        """Creating a detector should load existing history from file."""
        hist_file = tmp_path / "anomaly_history.json"
        hist_file.write_text(json.dumps({"test_metric": [1.0, 2.0, 3.0]}))
        d = AnomalyDetector(history_file=str(hist_file))
        assert d.history.get("test_metric") == [1.0, 2.0, 3.0]

    def test_init_handles_corrupt_file(self, tmp_path: Path):
        """Corrupt history files should be handled gracefully."""
        hist_file = tmp_path / "anomaly_history.json"
        hist_file.write_text("not valid json")
        d = AnomalyDetector(history_file=str(hist_file))
        assert d.history == {}


# ── update_and_check tests ───────────────────────────────────────────────────

class TestUpdateAndCheck:
    """Test the core anomaly detection logic."""

    def test_first_value_not_anomaly(self, detector: AnomalyDetector):
        """First value with no history should not be an anomaly."""
        is_anom, z = detector.update_and_check("test", 10.0)
        assert is_anom is False
        assert z == 0.0

    def test_two_values_not_anomaly(self, detector: AnomalyDetector):
        """Two close values should not be flagged as anomaly."""
        detector.update_and_check("test", 10.0)
        is_anom, z = detector.update_and_check("test", 10.5)
        assert is_anom is False
        assert z < 2.0  # Below z_threshold

    def test_obvious_anomaly_detected(self, detector: AnomalyDetector):
        """A value far from the mean should be detected as anomaly."""
        # Add 5 normal values
        for v in [10.0, 10.1, 9.9, 10.0, 10.1]:
            detector.update_and_check("test", v)
        # Add extreme value
        is_anom, z = detector.update_and_check("test", 50.0)
        assert is_anom is True
        assert z > 2.0

    def test_normal_value_not_anomaly(self, detector: AnomalyDetector):
        """A value close to the mean should not be an anomaly."""
        for v in [10.0, 10.1, 9.9, 10.0, 10.1]:
            detector.update_and_check("test", v)
        is_anom, z = detector.update_and_check("test", 10.05)
        assert is_anom is False
        assert z < 2.0

    def test_multiple_metrics_independent(self, detector: AnomalyDetector):
        """Different metrics should have independent histories."""
        # Add enough normal values to establish a strong baseline
        for v in [10.0, 10.1, 9.9, 10.0, 10.1, 9.8, 10.2]:
            detector.update_and_check("metric_a", v)
        for v in [100.0, 101.0, 99.0, 100.5, 99.5, 101.5]:
            detector.update_and_check("metric_b", v)
        # Extreme anomaly in metric_a
        is_anom_a, _ = detector.update_and_check("metric_a", 100.0)
        # Normal value in metric_b
        is_anom_b, _ = detector.update_and_check("metric_b", 100.5)
        assert is_anom_a is True, "metric_a should detect anomaly"
        assert is_anom_b is False, "metric_b should not flag normal value"

    def test_uniform_values_no_anomaly(self, detector: AnomalyDetector):
        """All same values should not produce anomalies."""
        for _ in range(5):
            detector.update_and_check("test", 10.0)
        is_anom, z = detector.update_and_check("test", 10.0)
        assert is_anom is False
        assert z == 0.0

    def test_uniform_values_different(self, detector: AnomalyDetector):
        """A value different from uniform history should be anomaly."""
        for _ in range(5):
            detector.update_and_check("test", 10.0)
        is_anom, z = detector.update_and_check("test", 20.0)
        assert is_anom is True

    def test_history_truncated_to_window(self, detector: AnomalyDetector):
        """History should be truncated to window_size."""
        for i in range(15):
            detector.update_and_check("test", float(i))
        assert len(detector.history["test"]) == 10  # window_size=10

    def test_window_truncation_affects_detection(self, detector: AnomalyDetector):
        """After truncation, old values should not affect detection."""
        for i in range(15):
            detector.update_and_check("test", float(i))
        # Now history is [5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
        # Adding 5 should NOT be anomaly (close to recent values)
        is_anom, z = detector.update_and_check("test", 6.0)
        assert is_anom is False

    def test_negative_values(self, detector: AnomalyDetector):
        """Negative values should work correctly."""
        for v in [-10.0, -10.1, -9.9, -10.0, -10.2, -9.8, -10.1]:
            detector.update_and_check("test", v)
        is_anom, z = detector.update_and_check("test", -50.0)
        assert is_anom is True


# ── get_history tests ────────────────────────────────────────────────────────

class TestGetHistory:
    """Test history retrieval."""

    def test_get_nonexistent_metric(self, detector: AnomalyDetector):
        """Getting history for non-existent metric should return []]."""
        assert detector.get_history("nonexistent") == []

    def test_get_existing_metric(self, detector: AnomalyDetector):
        """Getting history for existing metric should return values."""
        for v in [1.0, 2.0, 3.0]:
            detector.update_and_check("test", v)
        hist = detector.get_history("test")
        assert hist == [1.0, 2.0, 3.0]

    def test_history_order(self, detector: AnomalyDetector):
        """History should maintain insertion order."""
        for v in [10.0, 20.0, 30.0]:
            detector.update_and_check("test", v)
        hist = detector.get_history("test")
        assert hist == [10.0, 20.0, 30.0]


# ── detect_anomaly convenience function ──────────────────────────────────────

class TestDetectAnomalyFunction:
    """Test the module-level detect_anomaly convenience function."""

    def test_detects_extreme_value(self, tmp_path: Path):
        hist_file = tmp_path / "anomaly_history.json"
        # Add some normal values first
        for v in [10.0, 10.1, 9.9, 10.0, 10.1]:
            detect_anomaly("test", v, history_file=str(hist_file), window_size=20, z_threshold=2.0)
        is_anom, z = detect_anomaly("test", 50.0, history_file=str(hist_file), window_size=20, z_threshold=2.0)
        assert is_anom is True
        assert z > 2.0

    def test_detect_anomaly_persists(self, tmp_path: Path):
        """detect_anomaly should persist history between calls."""
        hist_file = tmp_path / "anomaly_history.json"
        detect_anomaly("test", 10.0, history_file=str(hist_file))
        detect_anomaly("test", 10.5, history_file=str(hist_file))
        # Load via another detector
        d = AnomalyDetector(history_file=str(hist_file))
        assert len(d.get_history("test")) == 2
