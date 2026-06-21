"""Tests for core/portfolio/optimizer.py - Portfolio Optimization Engine."""

from __future__ import annotations

import json
import math

import pytest

from core.portfolio.optimizer import (
    EfficientFrontierResult,
    OptimizationResult,
    PortfolioOptimizer,
    optimize_portfolio,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def optimizer() -> PortfolioOptimizer:
    return PortfolioOptimizer(n_grid=500)  # Smaller grid for faster tests


@pytest.fixture
def sample_returns() -> dict[str, float]:
    return {
        "NIFTY": 0.12,
        "BANKNIFTY": 0.15,
        "FINNIFTY": 0.14,
    }


@pytest.fixture
def sample_cov_matrix() -> dict[str, dict[str, float]]:
    return {
        "NIFTY": {"NIFTY": 0.04, "BANKNIFTY": 0.03, "FINNIFTY": 0.025},
        "BANKNIFTY": {"NIFTY": 0.03, "BANKNIFTY": 0.06, "FINNIFTY": 0.035},
        "FINNIFTY": {"NIFTY": 0.025, "BANKNIFTY": 0.035, "FINNIFTY": 0.05},
    }


# ── OptimizationResult Tests ─────────────────────────────────────────────────

class TestOptimizationResult:
    def test_default_values(self):
        r = OptimizationResult(method="test", weights={}, expected_return=0.0,
                               expected_volatility=0.0, sharpe_ratio=0.0,
                               diversification_ratio=1.0, n_assets=0)
        assert r.status == "SUCCESS"
        assert r.message == ""

    def test_summary_format(self):
        r = OptimizationResult(
            method="max_sharpe",
            weights={"NIFTY": 0.5, "BANKNIFTY": 0.5},
            expected_return=0.135, expected_volatility=0.20,
            sharpe_ratio=0.425, diversification_ratio=1.1,
            n_assets=2, status="SUCCESS",
        )
        s = r.summary()
        assert "max_sharpe" in s
        assert "NIFTY" in s
        assert "BANKNIFTY" in s
        assert "0.425" in s

    def test_to_dict_serializable(self):
        r = OptimizationResult(
            method="risk_parity",
            weights={"A": 0.6, "B": 0.4},
            expected_return=0.10, expected_volatility=0.15,
            sharpe_ratio=0.33, diversification_ratio=1.2,
            n_assets=2,
        )
        d = r.to_dict()
        json.dumps(d)  # Must be JSON-serializable
        assert d["method"] == "risk_parity"
        assert d["n_assets"] == 2

    def test_failed_status(self):
        r = OptimizationResult(
            method="max_sharpe", weights={},
            expected_return=0.0, expected_volatility=0.0,
            sharpe_ratio=0.0, diversification_ratio=1.0,
            n_assets=0, status="FAILED", message="Validation failed",
        )
        assert "FAILED" in r.summary()
        assert "Validation failed" in r.summary()


# ── Max Sharpe Portfolio Tests ───────────────────────────────────────────────

class TestMaxSharpe:
    def test_max_sharpe_two_assets(self, optimizer, sample_returns, sample_cov_matrix):
        result = optimizer.max_sharpe(sample_returns, sample_cov_matrix)
        assert result.status == "SUCCESS"
        assert result.n_assets == 3
        assert sum(result.weights.values()) == pytest.approx(1.0, rel=0.01)
        assert result.sharpe_ratio > 0
        assert result.expected_volatility > 0

    def test_max_sharpe_single_asset(self, optimizer):
        returns = {"NIFTY": 0.12}
        cov = {"NIFTY": {"NIFTY": 0.04}}
        result = optimizer.max_sharpe(returns, cov)
        assert result.status == "SUCCESS"
        assert result.n_assets == 1
        assert result.weights == {"NIFTY": 1.0}
        assert result.sharpe_ratio > 0  # Was returning 0.0 before fix

    def test_max_sharpe_empty_inputs(self, optimizer):
        result = optimizer.max_sharpe({}, {})
        assert result.status == "FAILED"

    def test_max_sharpe_weights_sum_to_one(self, optimizer, sample_returns, sample_cov_matrix):
        result = optimizer.max_sharpe(sample_returns, sample_cov_matrix)
        assert abs(sum(result.weights.values()) - 1.0) < 0.01


# ── Minimum Volatility Portfolio Tests ────────────────────────────────────────

class TestMinVolatility:
    def test_min_vol_two_assets(self, optimizer, sample_returns, sample_cov_matrix):
        result = optimizer.min_volatility(sample_returns, sample_cov_matrix)
        assert result.status == "SUCCESS"
        assert result.n_assets == 3
        assert sum(result.weights.values()) == pytest.approx(1.0, rel=0.01)

    def test_min_vol_single_asset(self, optimizer):
        returns = {"NIFTY": 0.12}
        cov = {"NIFTY": {"NIFTY": 0.04}}
        result = optimizer.min_volatility(returns, cov)
        assert result.status == "SUCCESS"
        assert result.weights == {"NIFTY": 1.0}
        assert result.sharpe_ratio > 0  # Was returning 0.0 before fix

    def test_min_vol_lower_vol_than_max_sharpe(self, optimizer, sample_returns, sample_cov_matrix):
        min_vol = optimizer.min_volatility(sample_returns, sample_cov_matrix)
        max_sharpe = optimizer.max_sharpe(sample_returns, sample_cov_matrix)
        assert min_vol.expected_volatility <= max_sharpe.expected_volatility * 1.05  # Allow 5% tolerance


# ── Risk Parity Portfolio Tests ───────────────────────────────────────────────

class TestRiskParity:
    def test_risk_parity_two_assets(self, optimizer, sample_returns, sample_cov_matrix):
        result = optimizer.risk_parity(sample_returns, sample_cov_matrix)
        assert result.status == "SUCCESS"
        assert result.n_assets == 3
        assert sum(result.weights.values()) == pytest.approx(1.0, rel=0.01)

    def test_risk_parity_inverse_vol_weighting(self, optimizer):
        """Higher vol assets should get lower weights."""
        returns = {"LOW_VOL": 0.10, "HIGH_VOL": 0.20}
        cov = {"LOW_VOL": {"LOW_VOL": 0.01, "HIGH_VOL": 0.0},
               "HIGH_VOL": {"LOW_VOL": 0.0, "HIGH_VOL": 0.09}}
        result = optimizer.risk_parity(returns, cov)
        assert result.weights["LOW_VOL"] > result.weights["HIGH_VOL"]

    def test_risk_parity_empty_inputs(self, optimizer):
        result = optimizer.risk_parity({}, {})
        assert result.status == "FAILED"


# ── Maximum Diversification Portfolio Tests ───────────────────────────────────

class TestMaxDiversification:
    def test_max_div_two_assets(self, optimizer, sample_returns, sample_cov_matrix):
        result = optimizer.max_diversification(sample_returns, sample_cov_matrix)
        assert result.status == "SUCCESS"
        assert result.n_assets == 3
        assert result.diversification_ratio >= 1.0

    def test_max_div_single_asset(self, optimizer):
        returns = {"NIFTY": 0.12}
        cov = {"NIFTY": {"NIFTY": 0.04}}
        result = optimizer.max_diversification(returns, cov)
        assert result.status == "SUCCESS"
        assert result.diversification_ratio == 1.0  # Single asset = no diversification


# ── Efficient Frontier Tests ──────────────────────────────────────────────────

class TestEfficientFrontier:
    def test_efficient_frontier_basic(self, optimizer, sample_returns, sample_cov_matrix):
        ef = optimizer.efficient_frontier(sample_returns, sample_cov_matrix, n_points=20)
        assert isinstance(ef, EfficientFrontierResult)
        assert ef.n_points > 0
        assert ef.max_sharpe_portfolio is not None
        assert ef.min_vol_portfolio is not None

    def test_efficient_frontier_pareto_improvement(self, optimizer, sample_returns, sample_cov_matrix):
        """Each frontier point should have higher return than the previous."""
        ef = optimizer.efficient_frontier(sample_returns, sample_cov_matrix, n_points=50)
        returns_list = [p.expected_return for p in ef.portfolios]
        for i in range(1, len(returns_list)):
            assert returns_list[i] >= returns_list[i - 1] - 0.001  # Allow tiny tolerance

    def test_efficient_frontier_single_asset(self, optimizer):
        returns = {"NIFTY": 0.12}
        cov = {"NIFTY": {"NIFTY": 0.04}}
        ef = optimizer.efficient_frontier(returns, cov)
        assert ef.n_points >= 1

    def test_efficient_frontier_empty_inputs(self, optimizer):
        ef = optimizer.efficient_frontier({}, {})
        assert ef.max_sharpe_portfolio is None or ef.max_sharpe_portfolio.status == "FAILED"


# ── Dispatch Method Tests ─────────────────────────────────────────────────────

class TestOptimizeDispatch:
    def test_dispatch_max_sharpe(self, optimizer, sample_returns, sample_cov_matrix):
        result = optimizer.optimize("max_sharpe", sample_returns, sample_cov_matrix)
        assert isinstance(result, OptimizationResult)
        assert result.status == "SUCCESS"

    def test_dispatch_risk_parity(self, optimizer, sample_returns, sample_cov_matrix):
        result = optimizer.optimize("risk_parity", sample_returns, sample_cov_matrix)
        assert isinstance(result, OptimizationResult)
        assert result.status == "SUCCESS"

    def test_dispatch_efficient_frontier(self, optimizer, sample_returns, sample_cov_matrix):
        result = optimizer.optimize("efficient_frontier", sample_returns, sample_cov_matrix)
        assert isinstance(result, EfficientFrontierResult)

    def test_dispatch_unknown_method(self, optimizer, sample_returns, sample_cov_matrix):
        result = optimizer.optimize("unknown_method", sample_returns, sample_cov_matrix)
        assert isinstance(result, OptimizationResult)
        assert result.status == "FAILED"


# ── Convenience Function Tests ────────────────────────────────────────────────

class TestOptimizePortfolio:
    def test_convenience_function(self, sample_returns, sample_cov_matrix):
        result = optimize_portfolio(sample_returns, sample_cov_matrix)
        assert isinstance(result, dict)
        assert "method" in result
        assert "weights" in result

    def test_convenience_function_json(self, sample_returns, sample_cov_matrix):
        result = optimize_portfolio(sample_returns, sample_cov_matrix, method="risk_parity")
        json.dumps(result)  # Must be JSON-serializable

    def test_convenience_function_efficient_frontier(self, sample_returns, sample_cov_matrix):
        result = optimize_portfolio(sample_returns, sample_cov_matrix, method="efficient_frontier")
        assert "n_points" in result
        assert "max_sharpe" in result


# ── Edge Case Tests ───────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_zero_variance_asset(self, optimizer):
        """Asset with zero variance should not crash."""
        returns = {"A": 0.10, "B": 0.12}
        cov = {"A": {"A": 0.0, "B": 0.0}, "B": {"B": 0.0, "A": 0.0}}
        result = optimizer.max_sharpe(returns, cov)
        assert result.status == "SUCCESS"

    def test_highly_correlated_assets(self, optimizer):
        """Perfectly correlated assets should produce valid weights."""
        returns = {"A": 0.10, "B": 0.12}
        cov = {"A": {"A": 0.04, "B": 0.04}, "B": {"B": 0.04, "A": 0.04}}
        result = optimizer.max_sharpe(returns, cov)
        assert result.status == "SUCCESS"
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

    def test_negative_expected_return(self, optimizer):
        """Negative expected return should still be handled."""
        returns = {"A": -0.05, "B": 0.10}
        cov = {"A": {"A": 0.04, "B": 0.01}, "B": {"B": 0.04, "A": 0.01}}
        result = optimizer.min_volatility(returns, cov)
        assert result.status == "SUCCESS"
