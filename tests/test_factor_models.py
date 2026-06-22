"""Tests for factor_models module (Fama-French + Carhart)."""

from __future__ import annotations

import math
import pytest
from core.factor_models import (
    FamaFrench3Factor,
    Carhart4Factor,
    BaseFactorModel,
    FactorReturn,
    compute_factor_attribution,
    _ols_regression,
)


class TestOLSRegression:
    """Tests for the OLS regression engine."""

    def test_perfect_fit(self):
        """OLS should recover exact coefficients with no noise."""
        n = 50
        y = [2.0 + 1.5 * i for i in range(n)]
        X = [[float(i)] for i in range(n)]
        result = _ols_regression(y, X, ["x1"])
        assert abs(result["alpha"] - 2.0) < 0.01
        assert abs(result["coefficients"][0] - 1.5) < 0.01
        assert abs(result["r_squared"] - 1.0) < 0.01

    def test_zero_variance(self):
        """All zero returns should produce zero coefficients."""
        y = [0.0] * 10
        X = [[0.0] for _ in range(10)]
        result = _ols_regression(y, X, ["x1"])
        assert abs(result["alpha"]) < 1e-10
        assert abs(result["coefficients"][0]) < 1e-10

    def test_insufficient_data(self):
        """Less than 3 observations should return defaults."""
        y = [1.0, 2.0]
        X = [[0.5], [1.0]]
        result = _ols_regression(y, X, ["x1"])
        assert result["r_squared"] == 0.0

    def test_multiple_factors(self):
        """Multi-factor regression with known coefficients."""
        import random
        random.seed(42)
        n = 100
        true_alpha = 0.05
        true_beta1 = 1.2
        true_beta2 = -0.8
        x1 = [random.gauss(0, 1) for _ in range(n)]
        x2 = [random.gauss(0, 1) for _ in range(n)]
        y = [true_alpha + true_beta1 * x1[i] + true_beta2 * x2[i] + random.gauss(0, 0.01) for i in range(n)]
        X = [[x1[i], x2[i]] for i in range(n)]
        result = _ols_regression(y, X, ["x1", "x2"])
        assert abs(result["alpha"] - true_alpha) < 0.02
        assert abs(result["coefficients"][0] - true_beta1) < 0.05
        assert abs(result["coefficients"][1] - true_beta2) < 0.05
        assert result["r_squared"] > 0.99


class TestFamaFrench3Factor:
    """Tests for the Fama-French 3-factor model."""

    def test_empty_model(self):
        """A model with no observations should return zero loadings."""
        model = FamaFrench3Factor()
        result = model.fit()
        assert result.loadings["market"] == 0.0
        assert result.loadings["smb"] == 0.0
        assert result.loadings["hml"] == 0.0
        assert result.n_observations == 0

    def test_single_observation(self):
        """A single observation should return defaults."""
        model = FamaFrench3Factor()
        model.add_return(portfolio_return=0.01, market_return=0.005, smb=0.001, hml=0.002)
        result = model.fit()
        assert result.n_observations == 1
        assert result.r_squared == 0.0

    def test_known_structure(self):
        """Recover known factor loadings from generated data."""
        import random
        random.seed(42)
        model = FamaFrench3Factor()
        true_beta_mkt = 1.1
        true_beta_smb = 0.4
        true_beta_hml = -0.2
        true_alpha = 0.0005
        n = 252
        for _ in range(n):
            mkt = random.gauss(0.001, 0.01)
            smb = random.gauss(0.0002, 0.005)
            hml = random.gauss(0.0001, 0.004)
            noise = random.gauss(0, 0.005)
            pf = true_alpha + true_beta_mkt * mkt + true_beta_smb * smb + true_beta_hml * hml + noise
            model.add_return(portfolio_return=pf, market_return=mkt, smb=smb, hml=hml)
        result = model.fit()
        assert abs(result.loadings["market"] - true_beta_mkt) < 0.15
        assert abs(result.loadings["smb"] - true_beta_smb) < 0.15
        assert abs(result.loadings["hml"] - true_beta_hml) < 0.15
        assert result.r_squared > 0.7

    def test_add_observation(self):
        """Test add_observation with FactorReturn object."""
        model = FamaFrench3Factor()
        obs = FactorReturn(portfolio_return=0.01, market_return=0.005, smb=0.001, hml=0.002, date="2026-01-01")
        model.add_observation(obs)
        result = model.fit()
        assert result.n_observations == 1

    def test_clear(self):
        """Clear should reset all observations."""
        model = FamaFrench3Factor()
        model.add_return(portfolio_return=0.01, market_return=0.005, smb=0.001, hml=0.002)
        assert model.n_observations == 1
        model.clear()
        assert model.n_observations == 0

    def test_to_dict(self):
        """FactorResult.to_dict should produce serializable output."""
        import random
        random.seed(42)
        model = FamaFrench3Factor()
        for _ in range(50):
            model.add_return(
                portfolio_return=random.gauss(0.001, 0.01),
                market_return=random.gauss(0.001, 0.01),
                smb=random.gauss(0.0, 0.005),
                hml=random.gauss(0.0, 0.004),
            )
        result = model.fit()
        d = result.to_dict()
        assert "loadings" in d
        assert "alpha" in d
        assert "r_squared" in d
        assert "annualized_alpha" in d
        assert abs(d["r_squared"]) <= 1.0

    def test_summary(self):
        """Summary should be a non-empty string."""
        model = FamaFrench3Factor()
        model.add_return(portfolio_return=0.01, market_return=0.005, smb=0.001, hml=0.002)
        model.add_return(portfolio_return=0.02, market_return=0.01, smb=0.002, hml=-0.001)
        model.add_return(portfolio_return=-0.01, market_return=-0.005, smb=-0.001, hml=0.003)
        result = model.fit()
        summary = result.summary()
        assert isinstance(summary, str)
        assert len(summary) > 50
        assert "Factor Model" in summary


class TestCarhart4Factor:
    """Tests for the Carhart 4-factor model."""

    def test_empty_model(self):
        model = Carhart4Factor()
        result = model.fit()
        assert result.loadings["market"] == 0.0
        assert result.loadings["mom"] == 0.0
        assert result.n_observations == 0

    def test_momentum_loading(self):
        """Verify momentum factor is captured."""
        import random
        random.seed(42)
        model = Carhart4Factor()
        true_mom = 0.5
        n = 252
        for _ in range(n):
            mkt = random.gauss(0.001, 0.01)
            smb = random.gauss(0.0002, 0.005)
            hml = random.gauss(0.0001, 0.004)
            mom = random.gauss(0.0003, 0.003)
            noise = random.gauss(0, 0.005)
            pf = 0.0003 + 0.9 * mkt + 0.3 * smb + 0.1 * hml + true_mom * mom + noise
            model.add_return(portfolio_return=pf, market_return=mkt, smb=smb, hml=hml, mom=mom)
        result = model.fit()
        assert abs(result.loadings["mom"] - true_mom) < 0.2
        assert "mom" in result.factor_names

    def test_4_factors_in_result(self):
        model = Carhart4Factor()
        model.add_return(portfolio_return=0.01, market_return=0.005, smb=0.001, hml=0.002, mom=0.003)
        result = model.fit()
        assert len(result.factor_names) == 4
        assert "market" in result.factor_names
        assert "smb" in result.factor_names
        assert "hml" in result.factor_names
        assert "mom" in result.factor_names


class TestPortfolioAttribution:
    """Tests for the compute_portfolio_attribution function."""

    def test_basic_attribution(self):
        """Basic attribution should decompose return correctly."""
        from core.factor_models import compute_portfolio_attribution
        pa = compute_portfolio_attribution(
            portfolio_return=0.02,
            factor_loadings={"market": 1.0, "smb": 0.3},
            factor_returns={"market": 0.015, "smb": -0.005},
        )
        assert abs(pa.total_return - 0.02) < 1e-10
        expected_explained = 1.0 * 0.015 + 0.3 * (-0.005)  # = 0.0135
        assert abs(pa.explained_return - expected_explained) < 1e-10
        assert abs(pa.unexplained_return - pa.alpha_contribution) < 1e-10
        assert pa.alpha_contribution > 0  # alpha = 0.0065
        assert pa.attribution_error < 1e-10

    def test_exact_attribution(self):
        """When factors explain everything, alpha should be zero."""
        from core.factor_models import compute_portfolio_attribution
        pa = compute_portfolio_attribution(
            portfolio_return=0.015,
            factor_loadings={"market": 1.0},
            factor_returns={"market": 0.015},
        )
        assert abs(pa.alpha_contribution) < 1e-10
        assert abs(pa.unexplained_return) < 1e-10
        assert abs(pa.explained_return - 0.015) < 1e-10

    def test_explicit_alpha(self):
        """Explicit alpha should be used when provided."""
        from core.factor_models import compute_portfolio_attribution
        pa = compute_portfolio_attribution(
            portfolio_return=0.02,
            factor_loadings={"market": 1.0},
            factor_returns={"market": 0.015},
            alpha=0.005,
        )
        assert abs(pa.alpha_contribution - 0.005) < 1e-10
        assert abs(pa.unexplained_return - 0.005) < 1e-10
        # attribution_error = |provided_alpha - (portfolio_return - explained)|
        # = |0.005 - (0.02 - 0.015)| = 0.0
        assert pa.attribution_error < 1e-10

    def test_single_factor(self):
        """Single factor attribution should work."""
        from core.factor_models import compute_portfolio_attribution
        pa = compute_portfolio_attribution(
            portfolio_return=0.01,
            factor_loadings={"market": 1.2},
            factor_returns={"market": 0.008},
        )
        assert abs(pa.factor_contributions["market"] - 0.0096) < 1e-10
        assert len(pa.factor_names) == 1

    def test_no_factors(self):
        """Empty factor loadings should attribute all to alpha."""
        from core.factor_models import compute_portfolio_attribution
        pa = compute_portfolio_attribution(
            portfolio_return=0.01,
            factor_loadings={},
            factor_returns={},
        )
        assert abs(pa.alpha_contribution - 0.01) < 1e-10
        assert pa.explained_return == 0.0
        assert len(pa.factor_names) == 0

    def test_to_dict(self):
        """to_dict should produce serializable output."""
        from core.factor_models import compute_portfolio_attribution
        pa = compute_portfolio_attribution(0.02, {"market": 1.0}, {"market": 0.015})
        d = pa.to_dict()
        assert "factor_contributions" in d
        assert "alpha_contribution" in d
        assert "total_return" in d

    def test_summary(self):
        """Summary should be a non-empty string."""
        from core.factor_models import compute_portfolio_attribution
        pa = compute_portfolio_attribution(0.02, {"market": 1.0}, {"market": 0.015})
        summary = pa.summary()
        assert isinstance(summary, str)
        assert len(summary) > 30
        assert "Attribution" in summary


class TestRiskAttribution:
    """Tests for the compute_risk_attribution function."""

    def test_basic_risk_attribution(self):
        """Basic risk attribution should decompose risk correctly."""
        from core.factor_models import compute_risk_attribution
        ra = compute_risk_attribution(
            factor_loadings={"market": 1.0, "smb": 0.3},
            factor_cov_matrix={
                "market": {"market": 0.04, "smb": 0.01},
                "smb": {"market": 0.01, "smb": 0.02},
            },
        )
        assert ra.total_risk > 0
        assert ra.explained_risk_pct > 90.0  # mostly explained by factors
        assert len(ra.factor_risk_contributions) == 2

    def test_specific_risk(self):
        """Specific risk should be included in total."""
        from core.factor_models import compute_risk_attribution
        ra = compute_risk_attribution(
            factor_loadings={"market": 1.0},
            factor_cov_matrix={"market": {"market": 0.04}},
            specific_variance=0.01,
        )
        expected_systematic = 1.0 * 0.04 * 1.0  # beta * cov * beta = 0.04
        expected_total = expected_systematic + 0.01  # = 0.05
        expected_risk = math.sqrt(expected_total)
        assert abs(ra.total_risk - expected_risk) < 0.001
        assert ra.specific_risk > 0

    def test_single_factor(self):
        """Single factor risk attribution."""
        from core.factor_models import compute_risk_attribution
        ra = compute_risk_attribution(
            factor_loadings={"market": 1.5},
            factor_cov_matrix={"market": {"market": 0.04}},
        )
        expected_variance = 1.5 * 0.04 * 1.5  # = 0.09
        expected_risk = math.sqrt(expected_variance)  # = 0.3
        assert abs(ra.total_risk - expected_risk) < 0.001
        assert ra.explained_risk_pct > 99.0

    def test_mctr_single_factor(self):
        """MCTR for single factor should equal total risk."""
        from core.factor_models import compute_risk_attribution
        ra = compute_risk_attribution(
            factor_loadings={"market": 1.0},
            factor_cov_matrix={"market": {"market": 0.04}},
        )
        # MCTR = (Sigma * beta)_f / sigma_portfolio = cov * 1.0 / sigma = 0.04 / 0.2 = 0.2
        # But actually: sigma_portfolio = sqrt(1.0 * 0.04 * 1.0) = 0.2
        # (Sigma * beta)_market = 0.04 * 1.0 = 0.04
        # MCTR = 0.04 / 0.2 = 0.2
        assert abs(ra.marginal_ctr["market"] - 0.2) < 0.001

    def test_to_dict(self):
        """to_dict should produce serializable output."""
        from core.factor_models import compute_risk_attribution
        ra = compute_risk_attribution(
            factor_loadings={"market": 1.0},
            factor_cov_matrix={"market": {"market": 0.04}},
        )
        d = ra.to_dict()
        assert "total_risk" in d
        assert "specific_risk" in d
        assert "explained_risk_pct" in d

    def test_summary(self):
        """Summary should be a non-empty string."""
        from core.factor_models import compute_risk_attribution
        ra = compute_risk_attribution(
            factor_loadings={"market": 1.0},
            factor_cov_matrix={"market": {"market": 0.04}},
        )
        summary = ra.summary()
        assert isinstance(summary, str)
        assert len(summary) > 30
        assert "Risk" in summary


class TestComputeFactorAttribution:
    """Tests for the convenience function."""

    def test_carhart4_attribution(self):
        """compute_factor_attribution with all factors."""
        import random
        random.seed(42)
        n = 252
        mkt = [random.gauss(0.001, 0.01) for _ in range(n)]
        smb = [random.gauss(0.0002, 0.005) for _ in range(n)]
        hml = [random.gauss(0.0001, 0.004) for _ in range(n)]
        mom = [random.gauss(0.0003, 0.003) for _ in range(n)]
        pf = [0.0005 + 1.0 * mkt[i] + 0.3 * smb[i] + 0.2 * hml[i] + 0.1 * mom[i] + random.gauss(0, 0.005) for i in range(n)]
        result = compute_factor_attribution(pf, mkt, smb, hml, mom, include_momentum=True)
        assert abs(result.loadings["market"] - 1.0) < 0.15
        assert abs(result.loadings["smb"] - 0.3) < 0.15
        assert abs(result.loadings["hml"] - 0.2) < 0.15
        assert abs(result.loadings["mom"] - 0.1) < 0.15
        assert result.r_squared > 0.8

    def test_ff3_attribution(self):
        """compute_factor_attribution without momentum."""
        import random
        random.seed(42)
        n = 252
        mkt = [random.gauss(0.001, 0.01) for _ in range(n)]
        smb = [random.gauss(0.0002, 0.005) for _ in range(n)]
        hml = [random.gauss(0.0001, 0.004) for _ in range(n)]
        pf = [0.0005 + 1.0 * mkt[i] + 0.3 * smb[i] + 0.2 * hml[i] + random.gauss(0, 0.005) for i in range(n)]
        result = compute_factor_attribution(pf, mkt, smb, hml, include_momentum=False)
        assert abs(result.loadings["market"] - 1.0) < 0.2
        assert abs(result.loadings["smb"] - 0.3) < 0.2
        assert abs(result.loadings["hml"] - 0.2) < 0.2
        assert result.r_squared > 0.7

    def test_market_only(self):
        """Single-factor market model."""
        import random
        random.seed(42)
        n = 100
        mkt = [random.gauss(0.001, 0.01) for _ in range(n)]
        pf = [0.0002 + 0.8 * mkt[i] + random.gauss(0, 0.005) for i in range(n)]
        result = compute_factor_attribution(pf, mkt, include_momentum=False)
        assert abs(result.loadings["market"] - 0.8) < 0.15
        assert "market" in result.factor_names
        assert len(result.factor_names) == 1

    def test_mismatched_lengths(self):
        """Mismatched list lengths should not crash and use min length."""
        result = compute_factor_attribution([0.01, 0.02], [0.005], include_momentum=False)
        # Should handle gracefully - truncates to shortest list length (1),
        # but OLS needs 3+ observations so returns empty defaults
        assert result.n_observations == 1
        assert "market" in result.loadings
        assert result.r_squared == 0.0


class TestBaseFactorModel:
    """Tests for the base class."""

    def test_base_model(self):
        model = BaseFactorModel(["market"])
        model.add_return(portfolio_return=0.01, market_return=0.005)
        model.add_return(portfolio_return=0.02, market_return=0.01)
        assert model.n_observations == 2

    def test_base_model_insufficient(self):
        model = BaseFactorModel(["market"])
        result = model.fit() if hasattr(model, 'fit') else None
        # Base model doesn't have fit() - test the OLS directly
        y, X = [], []  # empty
        result = _ols_regression(y, X, ["market"])
        assert result["r_squared"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
