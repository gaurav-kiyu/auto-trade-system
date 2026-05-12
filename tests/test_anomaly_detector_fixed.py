"""
Tests for anomaly_detector module.
"""

from __future__ import annotations

import json
import tempfile
import os
from pathlib import Path

import pytest

from core.anomaly_detector import AnomalyDetector, detect_anomaly


class TestAnomalyDetector:
    """Test AnomalyDetector class."""

    def test_init_default(self):
        """Test initialization with default parameters."""
        detector = AnomalyDetector()
        assert detector.window_size == 100
        assert detector.z_threshold == 3.0
        assert detector.history_file.name == "anomaly_history.json"

    def test_init_custom(self):
        """Test initialization with custom parameters."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            history_file = f.name

        try:
            detector = AnomalyDetector(
                history_file=history_file,
                window_size=50,
                z_threshold=2.0
            )
            assert detector.window_size == 50
            assert detector.z_threshold == 2.0
            assert str(detector.history_file) == history_file
        finally:
            os.unlink(history_file)

    def test_update_and_check_insufficient_data(self):
        """Test behavior with insufficient historical data."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            history_file = f.name

        try:
            detector = AnomalyDetector(history_file=history_file)

            # First value - should not be anomaly
            is_anomaly, z_score = detector.update_and_check("test_metric", 10.0)
            assert is_anomaly is False
            assert z_score == 0.0

            # Second value - now we can calculate statistics
            is_anomaly, z_score = detector.update_and_check("test_metric", 10.0)
            assert is_anomaly is False
            assert z_score == 0.0  # Same values, std = 0

            # Third different value
            is_anomaly, z_score = detector.update_and_check("test_metric", 20.0)
            # temp_history = [10, 10, 20] (includes current value)
            # mean = (10+10+20)/3 = 40/3 ≈ 13.33
            # std = sqrt(((10-13.33)^2 + (10-13.33)^2 + (20-13.33)^2)/3) = sqrt(22.22) ≈ 4.71
            # z = |20-13.33|/4.71 = 6.67/4.71 ≈ 1.42 < 2.0
            # NOT an anomaly because z-score is below 2.0 threshold
            assert is_anomaly is False
        finally:
            os.unlink(history_file)

    def test_update_and_check_detects_anomaly(self):
        """Test that clear anomalies are detected."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            history_file = f.name

        try:
            detector = AnomalyDetector(
                history_file=history_file,
                window_size=5,
                z_threshold=2.0
            )

            # Establish baseline: five values of 10.0
            for i in range(5):
                is_anom, z = detector.update_and_check("test_metric", 10.0)
                assert is_anom is False
                if i > 0:  # After first value, all same
                    assert z == 0.0

            # Now test clear outlier
            is_anomaly, z_score = detector.update_and_check("test_metric", 30.0)
            # temp_history = [10,10,10,10,10,30] (includes current value)
            # mean = (5*10 + 30)/6 = 80/6 ≈ 13.33
            # std = sqrt(((10-13.33)^2*5 + (30-13.33)^2)/6) = sqrt(55.56) ≈ 7.45
            # z = |30-13.33|/7.45 = 16.67/7.45 ≈ 2.24 > 2.0
            # IS an anomaly because z-score exceeds 2.0 threshold
            assert is_anomaly is True
            assert z_score == pytest.approx(2.24, rel=0.05)
        finally:
            os.unlink(history_file)

    def test_update_and_check_no_anomaly_similar_value(self):
        """Test that similar values are not flagged as anomalies."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            history_file = f.name

        try:
            detector = AnomalyDetector(
                history_file=history_file,
                window_size=5,
                z_threshold=2.0
            )

            # Establish baseline: five values of 10.0
            for i in range(5):
                is_anom, z = detector.update_and_check("test_metric", 10.0)
                assert is_anom is False
                if i > 0:
                    assert z == 0.0

            # Test value same as baseline - should not be anomaly
            is_anomaly, z_score = detector.update_and_check("test_metric", 10.0)
            assert is_anomaly is False
            assert z_score == 0.0
        finally:
            os.unlink(history_file)

    def test_get_history(self):
        """Test getting history for a metric."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            history_file = f.name

        try:
            detector = AnomalyDetector(history_file=history_file)
            assert detector.get_history("nonexistent") == []

            detector.update_and_check("test_metric", 1.0)
            detector.update_and_check("test_metric", 2.0)
            assert detector.get_history("test_metric") == [1.0, 2.0]
        finally:
            os.unlink(history_file)

    def test_window_size_limit(self):
        """Test that history is limited to window size."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            history_file = f.name

        try:
            detector = AnomalyDetector(history_file=history_file, window_size=3)

            # Add more values than window size
            for i in range(5):
                detector.update_and_check("test_metric", float(i))

            # Should only keep last 3 values
            history = detector.get_history("test_metric")
            assert len(history) == 3
            assert history == [2.0, 3.0, 4.0]
        finally:
            os.unlink(history_file)

    def test_detect_anomaly_convenience_function(self):
        """Test the convenience detect_anomaly function."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            history_file = f.name

        try:
            # First call - no history, should not be anomaly
            is_anomaly, z_score = detect_anomaly(
                "test_metric", 5.0,
                history_file=history_file,
                window_size=3,
                z_threshold=2.0
            )
            assert is_anomaly is False
            assert z_score == 0.0

            # Second call - now we have one historical value
            is_anomaly, z_score = detect_anomaly(
                "test_metric", 5.0,
                history_file=history_file,
                window_size=3,
                z_threshold=2.0
            )
            assert is_anomaly is False
            assert z_score == 0.0

            # Third call - different value
            is_anomaly, z_score = detect_anomaly(
                "test_metric", 10.0,
                history_file=history_file,
                window_size=3,
                z_threshold=2.0
            )
            # After 2 calls: history = [5,5]
            # temp_history = [5,5,10] for this call
            # mean = (5+5+10)/3 = 20/3 ≈ 6.67
            # std = sqrt(((5-6.67)^2 + (5-6.67)^2 + (10-6.67)^2)/3) = sqrt(5.56) ≈ 2.36
            # z = |10-6.67|/2.36 = 3.33/2.36 ≈ 1.41 < 2.0
            # NOT an anomaly
            assert is_anomaly is False
        finally:
            os.unlink(history_file)

    def test_persistence(self):
        """Test that history is saved to and loaded from file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            history_file = f.name

        try:
            # Create first detector, add some data
            detector1 = AnomalyDetector(history_file=history_file, window_size=5)
            detector1.update_and_check("test_metric", 1.0)
            detector1.update_and_check("test_metric", 2.0)
            detector1.update_and_check("test_metric", 3.0)

            # Create second detector with same file
            detector2 = AnomalyDetector(history_file=history_file, window_size=5)
            history = detector2.get_history("test_metric")
            assert history == [1.0, 2.0, 3.0]

            # Add more data with second detector
            detector2.update_and_check("test_metric", 4.0)

            # Create third detector
            detector3 = AnomalyDetector(history_file=history_file, window_size=5)
            history = detector3.get_history("test_metric")
            assert history == [1.0, 2.0, 3.0, 4.0]
        finally:
            if os.path.exists(history_file):
                os.unlink(history_file)

    def test_different_metrics_isolated(self):
        """Test that different metrics maintain separate histories."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            history_file = f.name

        try:
            detector = AnomalyDetector(history_file=history_file)

            # Add data to metric A
            detector.update_and_check("metric_a", 10.0)
            detector.update_and_check("metric_a", 10.0)
            detector.update_and_check("metric_a", 10.0)

            # Add data to metric B
            detector.update_and_check("metric_b", 1.0)
            detector.update_and_check("metric_b", 1.0)
            detector.update_and_check("metric_b", 1.0)

            # Check histories are separate
            assert detector.get_history("metric_a") == [10.0, 10.0, 10.0]
            assert detector.get_history("metric_b") == [1.0, 1.0, 1.0]

            # Test anomaly detection on each
            # For metric_a: history [10,10,10], testing 20.0
            # temp_history = [10,10,10,20]
            # mean = 50/4 = 12.5, std = sqrt(17.5) ≈ 4.18
            # z = |20-12.5|/4.18 = 7.5/4.18 ≈ 1.79 < 2.0, NOT anomaly
            is_anom_a, z_a = detector.update_and_check("metric_a", 20.0)
            assert is_anom_a is False

            # For metric_b: history [1,1,1], testing 2.0
            # temp_history = [1,1,1,2]
            # mean = 5/4 = 1.25, std = sqrt(0.1875) ≈ 0.43
            # z = |2-1.25|/0.43 = 0.75/0.43 ≈ 1.73 < 2.0, NOT anomaly
            is_anom_b, z_b = detector.update_and_check("metric_b", 2.0)
            assert is_anom_b is False
        finally:
            os.unlink(history_file)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])