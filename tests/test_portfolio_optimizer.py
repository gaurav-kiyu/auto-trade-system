"""Tests for portfolio/optimizer module including CVaR and ERC."""

from __future__ import annotations

import pytest
from core.portfolio.optimizer import (
    PortfolioOptimizer,
)


class TestPortfolioOptimizerBasic:
    """Basic tests."""

    def test_initialization(self):
        opt = PortfolioOptimizer()
        assert opt is not None

    def test_empty_inputs(self):
        opt = PortfolioOptimizer()
        result = opt.max_sharpe({}, {})
        assert result.status == "FAILED"

    def test_no_common_assets(self):
        opt = PortfolioOptimizer()
        result = opt.max_sharpe({"A": 0.1}, {"B": {"B": 0.04}})
        assert result.status == "FAILED"


class TestCVaROptimization:
    """Tests for CVaR optimization."""

    def test_basic_cvar(self):
        """CVaR optimization should return valid result."""
        opt = PortfolioOptimizer(n_grid=200)
        rets = {"A": 0.12, "B": 0.15, "C": 0.14}
        cov = {
            "A": {"A": 0.04, "B": 0.02, "C": 0.015},
            "B": {"A": 0.02, "B": 0.06, "C": 0.025},
            "C": {"A": 0.015, "B": 0.025, "C": 0.05},
        }
        result = opt.cvar_optimization(rets, cov)
        assert result.status == "SUCCESS"
        assert result.n_assets == 3
        assert result.method == "cvar"
        assert "cvar" in result.details

    def test_cvar_single_asset(self):
        """Single asset CVaR should return that asset with 100% weight."""
        opt = PortfolioOptimizer()
        result = opt.cvar_optimization({"A": 0.12}, {"A": {"A": 0.04}})
        assert result.status == "SUCCESS"
        assert result.n_assets == 1
        assert abs(result.weights.get("A", 0) - 1.0) < 0.01

    def test_cvar_confidence_level(self):
        """Higher confidence should produce different CVaR values."""
        opt = PortfolioOptimizer()
        rets = {"A": 0.12, "B": 0.15}
        cov = {"A": {"A": 0.04, "B": 0.02}, "B": {"A": 0.02, "B": 0.06}}
        r1 = opt.cvar_optimization(rets, cov, confidence_level=0.95)
        r2 = opt.cvar_optimization(rets, cov, confidence_level=0.99)
        assert r1.status == "SUCCESS"
        assert r2.status == "SUCCESS"
        # 99% CVaR should be larger (more extreme tail)
        cvar1 = r1.details.get("cvar", 0)
        cvar2 = r2.details.get("cvar", 0)
        assert cvar2 >= cvar1  # 99% CVaR >= 95% CVaR

    def test_cvar_empty_inputs(self):
        """Empty inputs should return FAILED."""
        opt = PortfolioOptimizer()
        result = opt.cvar_optimization({}, {})
        assert result.status == "FAILED"

    def test_cvar_no_overlap(self):
        """No overlapping symbols should return FAILED."""
        opt = PortfolioOptimizer()
        result = opt.cvar_optimization({"A": 0.1}, {"B": {"B": 0.04}})
        assert result.status == "FAILED"


class TestEqualRiskContribution:
    """Tests for Equal Risk Contribution optimization."""

    def test_basic_erc(self):
        """ERC should return valid result with diversified weights."""
        opt = PortfolioOptimizer()
        rets = {"A": 0.12, "B": 0.15, "C": 0.14}
        cov = {
            "A": {"A": 0.04, "B": 0.02, "C": 0.015},
            "B": {"A": 0.02, "B": 0.06, "C": 0.025},
            "C": {"A": 0.015, "B": 0.025, "C": 0.05},
        }
        result = opt.equal_risk_contribution(rets, cov)
        assert result.status == "SUCCESS"
        assert result.n_assets == 3
        assert result.method == "erc"
        # All weights should be positive
        for w in result.weights.values():
            assert w > 0

    def test_erc_single_asset(self):
        """Single asset ERC should return 100% weight."""
        opt = PortfolioOptimizer()
        result = opt.equal_risk_contribution({"A": 0.12}, {"A": {"A": 0.04}})
        assert result.status == "SUCCESS"
        assert abs(result.weights.get("A", 0) - 1.0) < 0.01

    def test_erc_empty_inputs(self):
        """Empty inputs should return FAILED."""
        opt = PortfolioOptimizer()
        result = opt.equal_risk_contribution({}, {})
        assert result.status == "FAILED"

    def test_erc_no_overlap(self):
        """No overlapping symbols should return FAILED."""
        opt = PortfolioOptimizer()
        result = opt.equal_risk_contribution({"A": 0.1}, {"B": {"B": 0.04}})
        assert result.status == "FAILED"

    def test_erc_weights_sum_to_one(self):
        """ERC weights should sum to approximately 1.0."""
        opt = PortfolioOptimizer()
        rets = {"A": 0.12, "B": 0.15, "C": 0.14}
        cov = {
            "A": {"A": 0.04, "B": 0.02, "C": 0.015},
            "B": {"A": 0.02, "B": 0.06, "C": 0.025},
            "C": {"A": 0.015, "B": 0.025, "C": 0.05},
        }
        result = opt.equal_risk_contribution(rets, cov)
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 0.01


class TestNormHelpers:
    """Tests for the normal distribution helper methods."""

    def test_norm_pdf_zero(self):
        """PDF at zero should be ~0.3989."""
        opt = PortfolioOptimizer()
        pdf = opt._norm_pdf(0.0)
        assert abs(pdf - 0.39894228) < 0.001

    def test_norm_pdf_symmetric(self):
        """PDF should be symmetric around zero."""
        opt = PortfolioOptimizer()
        assert abs(opt._norm_pdf(1.0) - opt._norm_pdf(-1.0)) < 1e-10

    def test_norm_ppf_95(self):
        """95th percentile should be ~1.645."""
        opt = PortfolioOptimizer()
        ppf = opt._norm_ppf(0.95)
        assert abs(ppf - 1.6448536) < 0.01

    def test_norm_ppf_50(self):
        """50th percentile should be 0."""
        opt = PortfolioOptimizer()
        ppf = opt._norm_ppf(0.5)
        assert abs(ppf) < 0.01

    def test_norm_ppf_99(self):
        """99th percentile should be ~2.326."""
        opt = PortfolioOptimizer()
        ppf = opt._norm_ppf(0.99)
        assert abs(ppf - 2.32634787) < 0.01

    def test_norm_ppf_extremes(self):
        """Extreme percentiles should return capped values."""
        opt = PortfolioOptimizer()
        assert opt._norm_ppf(0.0) == -8.0
        assert opt._norm_ppf(1.0) == 8.0


class TestExistingMethodsStillWork:
    """Verify existing methods still work with new code."""

    def test_max_sharpe(self):
        opt = PortfolioOptimizer(n_grid=200)
        rets = {"A": 0.12, "B": 0.15}
        cov = {"A": {"A": 0.04, "B": 0.02}, "B": {"A": 0.02, "B": 0.06}}
        result = opt.max_sharpe(rets, cov)
        assert result.status == "SUCCESS"

    def test_risk_parity(self):
        opt = PortfolioOptimizer()
        rets = {"A": 0.12, "B": 0.15}
        cov = {"A": {"A": 0.04, "B": 0.02}, "B": {"A": 0.02, "B": 0.06}}
        result = opt.risk_parity(rets, cov)
        assert result.status == "SUCCESS"

    def test_min_volatility(self):
        opt = PortfolioOptimizer(n_grid=200)
        rets = {"A": 0.12, "B": 0.15}
        cov = {"A": {"A": 0.04, "B": 0.02}, "B": {"A": 0.02, "B": 0.06}}
        result = opt.min_volatility(rets, cov)
        assert result.status == "SUCCESS"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
