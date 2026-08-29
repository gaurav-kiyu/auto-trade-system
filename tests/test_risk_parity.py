"""Tests for Risk Parity optimizer."""

from __future__ import annotations

from core.risk_parity import RiskParityOptimizer, compute_risk_parity


class TestRiskParityOptimizer:
    """Test suite for RiskParityOptimizer."""

    def test_single_asset(self):
        """Single asset should get 100% weight."""
        result = RiskParityOptimizer().optimize({"NIFTY": 0.20})
        assert result.weights == {"NIFTY": 1.0}
        assert abs(result.portfolio_volatility - 0.20) < 0.001
        assert result.convergence
        assert result.method == "risk_parity"

    def test_two_assets_equal_vol(self):
        """Two uncorrelated assets with same vol should get equal weight."""
        result = RiskParityOptimizer().optimize(
            {"NIFTY": 0.20, "BANKNIFTY": 0.20},
        )
        assert len(result.weights) == 2
        for w in result.weights.values():
            assert abs(w - 0.50) < 0.10  # Should be near equal
        assert result.convergence

    def test_two_assets_different_vol(self):
        """Lower volatility asset should get higher weight."""
        result = RiskParityOptimizer().optimize(
            {"NIFTY": 0.20, "BANKNIFTY": 0.40},
        )
        assert result.weights["NIFTY"] > result.weights["BANKNIFTY"]
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

    def test_correlated_assets(self):
        """Correlated assets should adjust weights."""
        result = RiskParityOptimizer().optimize(
            {"NIFTY": 0.20, "BANKNIFTY": 0.25},
            correlations={("NIFTY", "BANKNIFTY"): 0.85},
        )
        assert len(result.weights) == 2
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

    def test_three_assets(self):
        """Three assets should all get positive weights."""
        result = RiskParityOptimizer().optimize(
            {"NIFTY": 0.20, "BANKNIFTY": 0.25, "FINNIFTY": 0.22},
        )
        assert len(result.weights) == 3
        assert all(w > 0 for w in result.weights.values())
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

    def test_empty_input(self):
        """Empty volatilities should return empty result."""
        result = RiskParityOptimizer().optimize({})
        assert result.weights == {}

    def test_convenience_function(self):
        """compute_risk_parity convenience function works."""
        result = compute_risk_parity({"NIFTY": 0.20, "BANKNIFTY": 0.25})
        assert len(result.weights) == 2
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

    def test_to_dict(self):
        """to_dict should return serializable output."""
        result = RiskParityOptimizer().optimize({"NIFTY": 0.20, "BANKNIFTY": 0.25})
        d = result.to_dict()
        assert "weights" in d
        assert "portfolio_volatility" in d
        assert "convergence" in d

    def test_summary(self):
        """summary should return non-empty string."""
        result = RiskParityOptimizer().optimize({"NIFTY": 0.20, "BANKNIFTY": 0.25})
        s = result.summary()
        assert isinstance(s, str)
        assert len(s) > 20

    def test_min_max_weights(self):
        """Custom min/max weight constraints should be respected."""
        opt = RiskParityOptimizer({"risk_parity_min_weight": 0.10, "risk_parity_max_weight": 0.90})
        result = opt.optimize({"A": 0.20, "B": 0.25, "C": 0.30})
        for w in result.weights.values():
            assert 0.09 <= w <= 0.91  # Allow small floating point margin

    def test_method_erc(self):
        """ERC method should produce risk parity result."""
        result = RiskParityOptimizer().optimize(
            {"NIFTY": 0.20, "BANKNIFTY": 0.25},
            method="equal_risk_contribution",
        )
        assert result.method == "equal_risk_contribution"
        assert abs(sum(result.risk_contributions.values()) - 1.0) < 0.05
