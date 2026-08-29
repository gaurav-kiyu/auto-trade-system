"""Tests for Mean-Variance portfolio optimizer."""

from __future__ import annotations

from core.mean_variance import MeanVarianceOptimizer


class TestMeanVarianceOptimizer:
    """Test suite for MeanVarianceOptimizer."""

    def test_single_asset(self):
        """Single asset should get 100% weight."""
        result = MeanVarianceOptimizer().maximize_sharpe({"NIFTY": 0.15})
        assert result.weights == {"NIFTY": 1.0}
        assert abs(result.expected_return - 0.15) < 0.001

    def test_two_assets_sharpe(self):
        """Two assets with different returns should bias to higher return."""
        result = MeanVarianceOptimizer().maximize_sharpe(
            {"NIFTY": 0.15, "BANKNIFTY": 0.18},
            {("NIFTY", "NIFTY"): 0.04, ("BANKNIFTY", "BANKNIFTY"): 0.06},
        )
        assert len(result.weights) == 2
        assert result.sharpe_ratio > 0

    def test_min_volatility(self):
        """Minimum volatility should favor lower variance assets."""
        result = MeanVarianceOptimizer().minimize_volatility(
            {"LOW": 0.10, "HIGH": 0.20},
            {("LOW", "LOW"): 0.01, ("HIGH", "HIGH"): 0.09},
        )
        assert result.weights["LOW"] > result.weights["HIGH"]

    def test_empty_input(self):
        """Empty returns should return empty result."""
        result = MeanVarianceOptimizer().maximize_sharpe({})
        assert result.weights == {}

    def test_single_asset_min_vol(self):
        """Single asset min volatility should work."""
        result = MeanVarianceOptimizer().minimize_volatility({"NIFTY": 0.15})
        assert result.weights == {"NIFTY": 1.0}

    def test_to_dict(self):
        """to_dict should return serializable output."""
        result = MeanVarianceOptimizer().maximize_sharpe({"A": 0.15, "B": 0.12})
        d = result.to_dict()
        assert "weights" in d
        assert "sharpe_ratio" in d
        assert "expected_return" in d

    def test_summary(self):
        """summary should return non-empty string."""
        result = MeanVarianceOptimizer().maximize_sharpe({"A": 0.15, "B": 0.12})
        s = result.summary()
        assert isinstance(s, str)
        assert len(s) > 20

    def test_objective_property(self):
        """Objective property should match method called."""
        sharpe = MeanVarianceOptimizer().maximize_sharpe({"A": 0.15, "B": 0.12})
        assert sharpe.objective == "max_sharpe"
        min_vol = MeanVarianceOptimizer().minimize_volatility({"A": 0.15, "B": 0.12})
        assert min_vol.objective == "min_volatility"

    def test_custom_risk_free_rate(self):
        """Custom risk-free rate should affect Sharpe ratio."""
        low_rfr = MeanVarianceOptimizer().maximize_sharpe(
            {"A": 0.15, "B": 0.12}, risk_free_rate=0.05,
        )
        high_rfr = MeanVarianceOptimizer().maximize_sharpe(
            {"A": 0.15, "B": 0.12}, risk_free_rate=0.10,
        )
        assert low_rfr.sharpe_ratio >= high_rfr.sharpe_ratio

    def test_all_positive_weights(self):
        """All weights should be non-negative."""
        result = MeanVarianceOptimizer().maximize_sharpe(
            {"A": 0.15, "B": 0.12, "C": 0.18},
            {("A", "A"): 0.04, ("B", "B"): 0.03, ("C", "C"): 0.05},
        )
        assert all(w >= 0 for w in result.weights.values())
        assert abs(sum(result.weights.values()) - 1.0) < 0.01
