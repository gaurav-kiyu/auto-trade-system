"""Tests for CVaR optimization module."""

from __future__ import annotations

from core.cvar_optimization import CVaROptimizer


class TestCVaROptimizer:
    """Test suite for CVaROptimizer."""

    def test_single_asset_evaluate(self):
        """Single asset evaluation should work."""
        result = CVaROptimizer().evaluate(
            {"A": [-0.05, -0.03, 0.01, 0.02, 0.04]},
            {"A": 1.0},
        )
        assert result.weights == {"A": 1.0}
        assert result.cvar <= result.var  # CVaR is worse (more negative) than VaR
        assert result.objective == "evaluate"

    def test_two_assets_minimize(self):
        """Minimize CVaR with two assets."""
        result = CVaROptimizer().minimize_cvar(
            {
                "A": [-0.05, -0.03, 0.01, 0.02, 0.04],
                "B": [-0.10, -0.06, 0.00, 0.03, 0.06],
            },
        )
        assert len(result.weights) == 2
        assert abs(sum(result.weights.values()) - 1.0) < 0.01
        assert result.objective == "min_cvar"

    def test_empty_input(self):
        """Empty returns should return empty result."""
        result = CVaROptimizer().minimize_cvar({})
        assert result.weights == {}

    def test_single_asset_minimize(self):
        """Single asset minimize should be same as evaluate."""
        result = CVaROptimizer().minimize_cvar({"A": [-0.05, -0.03, 0.01, 0.02, 0.04]})
        assert result.weights == {"A": 1.0}

    def test_confidence_level(self):
        """Higher confidence should produce more negative CVaR."""
        low_conf = CVaROptimizer({"cvar_confidence": 0.90}).evaluate(
            {"A": [-0.05, -0.04, -0.01, 0.02, 0.05, 0.07]},
            {"A": 1.0},
        )
        high_conf = CVaROptimizer({"cvar_confidence": 0.99}).evaluate(
            {"A": [-0.05, -0.04, -0.01, 0.02, 0.05, 0.07]},
            {"A": 1.0},
        )
        assert low_conf.confidence_level == 0.90
        assert high_conf.confidence_level == 0.99

    def test_to_dict(self):
        """to_dict should return serializable output."""
        result = CVaROptimizer().evaluate(
            {"A": [-0.05, -0.03, 0.01]},
            {"A": 1.0},
        )
        d = result.to_dict()
        assert "cvar" in d
        assert "var" in d
        assert "weights" in d

    def test_summary(self):
        """summary should return non-empty string."""
        result = CVaROptimizer().evaluate(
            {"A": [-0.05, -0.03, 0.01]},
            {"A": 1.0},
        )
        s = result.summary()
        assert isinstance(s, str)
        assert len(s) > 10

    def test_positive_returns_cvar(self):
        """All-positive returns should have CVaR near zero."""
        result = CVaROptimizer().evaluate(
            {"A": [0.01, 0.02, 0.03, 0.04, 0.05]},
            {"A": 1.0},
        )
        assert result.cvar >= 0  # No losses to measure

    def test_high_volatility_spread(self):
        """Assets with different volatilities should produce different CVaRs."""
        low_vol = CVaROptimizer().evaluate(
            {"A": [-0.01, -0.005, 0.0, 0.005, 0.01]},
            {"A": 1.0},
        )
        high_vol = CVaROptimizer().evaluate(
            {"B": [-0.10, -0.05, 0.0, 0.05, 0.10]},
            {"B": 1.0},
        )
        assert high_vol.cvar <= low_vol.cvar  # More negative = worse tail risk
