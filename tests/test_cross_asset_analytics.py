"""Tests for cross_asset_analytics module."""

from __future__ import annotations

import pytest
from core.cross_asset_analytics import (
    CrossAssetAnalytics,
    compute_cross_asset_correlation,
)


class TestCrossAssetAnalyticsBasic:
    """Basic tests for the CrossAssetAnalytics engine."""

    def test_empty_initialization(self):
        """New instance should have no assets."""
        analyzer = CrossAssetAnalytics()
        assert analyzer.n_assets == 0
        assert analyzer.n_observations == 0

    def test_add_returns(self):
        """Adding returns should increase asset count."""
        analyzer = CrossAssetAnalytics()
        analyzer.add_returns("NIFTY", [0.01, -0.005, 0.02])
        assert analyzer.n_assets == 1
        assert analyzer.n_observations == 3

    def test_add_multiple_assets(self):
        """Multiple assets should be tracked."""
        analyzer = CrossAssetAnalytics()
        analyzer.add_returns("NIFTY", [0.01, -0.005, 0.02])
        analyzer.add_returns("BANKNIFTY", [0.005, 0.01, -0.003])
        assert analyzer.n_assets == 2
        assert analyzer.n_observations == 3

    def test_clear(self):
        """Clearing should reset all state."""
        analyzer = CrossAssetAnalytics()
        analyzer.add_returns("NIFTY", [0.01, -0.005, 0.02])
        analyzer.add_returns("BANKNIFTY", [0.005, 0.01, -0.003])
        assert analyzer.n_assets == 2
        analyzer.clear()
        assert analyzer.n_assets == 0

    def test_validation_insufficient_assets(self):
        """Less than 2 assets should return empty correlation matrix."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        analyzer.add_returns("NIFTY", [0.01, -0.005, 0.02])
        result = analyzer.correlation_matrix()
        assert result.n_assets == 0
        assert result.matrix == {}

    def test_validation_insufficient_observations(self):
        """Less than min_observations should fail validation."""
        analyzer = CrossAssetAnalytics(min_observations=10)
        analyzer.add_returns("NIFTY", [0.01, -0.005])
        analyzer.add_returns("BANKNIFTY", [0.005, 0.01])
        result = analyzer.correlation_matrix()
        assert result.n_assets == 0

    def test_mismatched_lengths(self):
        """Assets with different observation counts should fail."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        analyzer.add_returns("NIFTY", [0.01, -0.005, 0.02, 0.01])
        analyzer.add_returns("BANKNIFTY", [0.005, 0.01, -0.003])
        issues = analyzer._validate()
        assert len(issues) > 0


class TestCorrelationMatrix:
    """Tests for the correlation matrix computation."""

    def test_perfect_correlation(self):
        """Identical returns should give 1.0 correlation."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        returns = [0.01, -0.005, 0.02, 0.015, -0.01]
        analyzer.add_returns("A", returns)
        analyzer.add_returns("B", returns)
        result = analyzer.correlation_matrix()
        assert result.n_assets == 2
        assert abs(result.matrix["A"]["B"] - 1.0) < 0.01
        assert abs(result.matrix["B"]["A"] - 1.0) < 0.01
        assert result.matrix["A"]["A"] == 1.0

    def test_inverse_correlation(self):
        """Perfectly inverse returns should give -1.0 correlation."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        returns_a = [0.01, -0.005, 0.02, 0.015, 0.005, -0.01, 0.015]
        returns_b = [-0.01, 0.005, -0.02, -0.015, -0.005, 0.01, -0.015]
        analyzer.add_returns("A", returns_a)
        analyzer.add_returns("B", returns_b)
        result = analyzer.correlation_matrix()
        assert result.n_assets == 2
        assert abs(result.matrix["A"]["B"] - (-1.0)) < 0.01

    def test_zero_correlation(self):
        """Uncorrelated returns should give near-zero correlation."""
        import random
        random.seed(42)
        analyzer = CrossAssetAnalytics(min_observations=20)
        returns_a = [random.gauss(0, 1) for _ in range(50)]
        returns_b = [random.gauss(0, 1) for _ in range(50)]
        analyzer.add_returns("A", returns_a)
        analyzer.add_returns("B", returns_b)
        result = analyzer.correlation_matrix()
        assert abs(result.matrix["A"]["B"]) < 0.3  # noise

    def test_avg_correlation(self):
        """Average correlation should be computed correctly."""
        import random
        random.seed(42)
        analyzer = CrossAssetAnalytics(min_observations=3)
        common = [random.gauss(0, 1) for _ in range(30)]
        analyzer.add_returns("A", common)
        analyzer.add_returns("B", [0.9 * c + 0.1 * random.gauss(0, 1) for c in common])
        analyzer.add_returns("C", [0.8 * c + 0.2 * random.gauss(0, 1) for c in common])
        result = analyzer.correlation_matrix()
        assert result.avg_correlation > 0.5  # all positively correlated
        assert result.max_correlation > result.min_correlation

    def test_to_dict(self):
        """to_dict should produce serializable output."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        analyzer.add_returns("A", [0.01, -0.005, 0.02, 0.015])
        analyzer.add_returns("B", [-0.01, 0.005, -0.02, -0.015])
        result = analyzer.correlation_matrix()
        d = result.to_dict()
        assert "matrix" in d
        assert "avg_correlation" in d
        assert "n_assets" in d

    def test_summary(self):
        """Summary should be a non-empty string."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        analyzer.add_returns("A", [0.01, -0.005, 0.02])
        analyzer.add_returns("B", [-0.01, 0.005, -0.02])
        result = analyzer.correlation_matrix()
        summary = result.summary()
        assert isinstance(summary, str)
        assert len(summary) > 20


class TestRelativeValue:
    """Tests for the relative value (z-score) analysis."""

    def test_identical_assets(self):
        """Identical assets should give z-score of 0."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        returns = [0.01, -0.005, 0.02, 0.015, -0.01]
        analyzer.add_returns("A", returns)
        analyzer.add_returns("B", returns)
        result = analyzer.relative_value("A", "B")
        assert abs(result.z_score) < 0.01
        assert not result.is_extreme

    def test_missing_asset(self):
        """Missing asset should return error interpretation."""
        analyzer = CrossAssetAnalytics()
        analyzer.add_returns("A", [0.01, -0.005, 0.02])
        result = analyzer.relative_value("A", "B")
        assert result.interpretation == "Missing data"
        assert result.z_score == 0.0

    def test_insufficient_data(self):
        """Less than 3 observations should return insufficient data."""
        analyzer = CrossAssetAnalytics()
        analyzer.add_returns("A", [0.01, -0.005])
        analyzer.add_returns("B", [0.005, 0.01])
        result = analyzer.relative_value("A", "B")
        assert result.interpretation == "Insufficient data"

    def test_extreme_z_score(self):
        """A large spread should be detected as extreme."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        analyzer.add_returns("A", [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.10])
        analyzer.add_returns("B", [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        result = analyzer.relative_value("A", "B")
        assert abs(result.z_score) > 2.0 or result.is_extreme

    def test_to_dict(self):
        """to_dict should produce serializable output."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        analyzer.add_returns("A", [0.01, -0.005, 0.02, 0.015])
        analyzer.add_returns("B", [-0.01, 0.005, -0.02, -0.015])
        result = analyzer.relative_value("A", "B")
        d = result.to_dict()
        assert "z_score" in d
        assert "interpretation" in d
        assert "is_extreme" in d

    def test_summary(self):
        """Summary should be a non-empty string."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        analyzer.add_returns("A", [0.01, -0.005, 0.02])
        analyzer.add_returns("B", [-0.01, 0.005, -0.02])
        result = analyzer.relative_value("A", "B")
        summary = result.summary()
        assert isinstance(summary, str)
        assert len(summary) > 20


class TestFlightToSafety:
    """Tests for the flight-to-safety detection."""

    def test_no_flight_normal_market(self):
        """Normal market should not trigger flight-to-safety."""
        import random
        random.seed(42)
        analyzer = CrossAssetAnalytics(min_observations=5)
        nifty = [random.gauss(0.001, 0.01) for _ in range(20)]
        gold = [random.gauss(0.0005, 0.005) for _ in range(20)]
        analyzer.add_returns("NIFTY", nifty)
        analyzer.add_returns("GOLD", gold)
        result = analyzer.detect_flight_to_safety(
            risk_assets=["NIFTY"], safe_assets=["GOLD"]
        )
        assert not result.is_flight_to_safety

    def test_flight_detected(self):
        """Risk-off should be detected when risk falls and safe rises."""
        analyzer = CrossAssetAnalytics(min_observations=5)
        analyzer.add_returns("NIFTY", [0.01, -0.005, 0.02, -0.01, -0.03, -0.05])
        analyzer.add_returns("BANKNIFTY", [0.005, 0.01, -0.003, -0.02, -0.04, -0.06])
        analyzer.add_returns("GOLD", [-0.001, 0.002, -0.001, 0.01, 0.02, 0.03])
        result = analyzer.detect_flight_to_safety(
            risk_assets=["NIFTY", "BANKNIFTY"],
            safe_assets=["GOLD"],
        )
        assert result.is_flight_to_safety
        assert result.risk_asset_performance < 0
        assert result.safe_asset_performance > 0

    def test_no_risk_assets(self):
        """Empty risk assets should return NONE."""
        analyzer = CrossAssetAnalytics(min_observations=5)
        analyzer.add_returns("GOLD", [0.01, -0.005, 0.02, -0.01, -0.03])
        result = analyzer.detect_flight_to_safety(
            risk_assets=[], safe_assets=["GOLD"]
        )
        assert not result.is_flight_to_safety
        assert result.strength == "NONE"

    def test_insufficient_data(self):
        """Less than 5 observations should return NONE."""
        analyzer = CrossAssetAnalytics(min_observations=5)
        analyzer.add_returns("NIFTY", [0.01, -0.005])
        analyzer.add_returns("GOLD", [0.005, 0.01])
        result = analyzer.detect_flight_to_safety(
            risk_assets=["NIFTY"], safe_assets=["GOLD"]
        )
        assert not result.is_flight_to_safety

    def test_to_dict(self):
        """to_dict should produce serializable output."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        analyzer.add_returns("NIFTY", [0.01, -0.005, 0.02])
        analyzer.add_returns("GOLD", [-0.01, 0.005, -0.02])
        result = analyzer.detect_flight_to_safety(
            risk_assets=["NIFTY"], safe_assets=["GOLD"]
        )
        d = result.to_dict()
        assert "is_flight_to_safety" in d
        assert "strength" in d

    def test_summary(self):
        """Summary should be a non-empty string."""
        analyzer = CrossAssetAnalytics(min_observations=3)
        analyzer.add_returns("NIFTY", [0.01, -0.005, 0.02])
        analyzer.add_returns("GOLD", [-0.01, 0.005, -0.02])
        result = analyzer.detect_flight_to_safety(
            risk_assets=["NIFTY"], safe_assets=["GOLD"]
        )
        summary = result.summary()
        assert isinstance(summary, str)
        assert len(summary) > 10


class TestRollingCorrelationStability:
    """Tests for rolling correlation stability."""

    def test_stable_correlation(self):
        """Stable correlation should return STABLE classification."""
        analyzer = CrossAssetAnalytics(min_observations=30)
        analyzer.add_returns("A", [0.01 * (i % 2 - 0.5) for i in range(50)])
        analyzer.add_returns("B", [0.01 * (i % 2 - 0.5) for i in range(50)])
        result = analyzer.rolling_correlation_stability("A", "B", window=10)
        assert result["status"] == "ok"
        assert result["stability"] in ("STABLE", "MODERATE")

    def test_missing_asset(self):
        """Missing asset should return error."""
        analyzer = CrossAssetAnalytics()
        analyzer.add_returns("A", [0.01, -0.005, 0.02])
        result = analyzer.rolling_correlation_stability("A", "B")
        assert result["status"] == "error"

    def test_insufficient_data(self):
        """Insufficient data should return error."""
        analyzer = CrossAssetAnalytics()
        analyzer.add_returns("A", [0.01, -0.005])
        analyzer.add_returns("B", [0.005, 0.01])
        result = analyzer.rolling_correlation_stability("A", "B", window=5)
        assert result["status"] == "error"


class TestComputeCrossAssetCorrelation:
    """Tests for the convenience function."""

    def test_basic_function(self):
        """Convenience function should work with dict input."""
        data = {
            "A": [0.01, -0.005, 0.02, 0.015, 0.005, -0.01, 0.015, 0.02, -0.005, 0.01,
                  0.005, -0.01, 0.015, 0.02, -0.005, 0.01, -0.01, 0.015, -0.005, 0.02,
                  0.01, -0.005, 0.02, 0.015, 0.005],
            "B": [-0.01, 0.005, -0.02, -0.015, -0.005, 0.01, -0.015, -0.02, 0.005, -0.01,
                  -0.005, 0.01, -0.015, -0.02, 0.005, -0.01, 0.01, -0.015, 0.005, -0.02,
                  -0.01, 0.005, -0.02, -0.015, -0.005],
        }
        result = compute_cross_asset_correlation(data)
        assert "matrix" in result
        assert "avg_correlation" in result
        assert result["n_assets"] == 2


class TestPearson:
    """Tests for the Pearson correlation implementation."""

    def test_perfect_positive(self):
        """Perfect positive correlation should return 1.0."""
        analyzer = CrossAssetAnalytics()
        corr = analyzer._pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
        assert abs(corr - 1.0) < 0.01

    def test_perfect_negative(self):
        """Perfect negative correlation should return -1.0."""
        analyzer = CrossAssetAnalytics()
        corr = analyzer._pearson([1, 2, 3, 4, 5], [10, 8, 6, 4, 2])
        assert abs(corr - (-1.0)) < 0.01

    def test_no_correlation(self):
        """Constant data should return 0.0."""
        analyzer = CrossAssetAnalytics()
        corr = analyzer._pearson([1, 1, 1], [1, 2, 3])
        assert abs(corr) < 0.01

    def test_insufficient_data(self):
        """Less than 3 points should return 0.0."""
        analyzer = CrossAssetAnalytics()
        corr = analyzer._pearson([1, 2], [3, 4])
        assert corr == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
