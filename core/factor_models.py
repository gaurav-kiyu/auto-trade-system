"""
Factor Models — Fama-French 3-Factor & Carhart 4-Factor Models.

Implements factor-based return attribution for portfolio performance analysis.
Supports the canonical Fama-French 3-factor model (Market, Size, Value) and
the Carhart 4-factor extension (+ Momentum).

These models decompose portfolio returns into factor exposures, enabling:
  - Performance attribution (alpha generation vs factor returns)
  - Risk decomposition (which factors drive portfolio volatility)
  - Style analysis (value/growth/size/momentum tilts)
  - Benchmark-relative performance evaluation

Usage
-----
    from core.factor_models import (
        FamaFrench3Factor,
        Carhart4Factor,
        compute_factor_attribution,
        FactorResult,
    )

    model = FamaFrench3Factor()
    model.add_return(portfolio_return=0.02, market_return=0.015,
                     smb=-0.005, hml=0.01, date="2026-01-01")
    model.add_return(portfolio_return=-0.01, market_return=-0.008,
                     smb=0.003, hml=-0.007, date="2026-01-02")
    result = model.fit()
    print(f"Alpha (annualized): {result.annualized_alpha:.4f}")
    print(f"Beta (Market): {result.loadings['market']:.4f}")
"""

from __future__ import annotations

import json
import logging
import math
import statistics
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)


# ── Data structures ────────────────────────────────────────────────────────────


@dataclass
class FactorReturn:
    """A single observation of factor returns and portfolio return.

    Args:
        portfolio_return: Portfolio excess return for the period.
        market_return: Market excess return (Rm - Rf).
        smb: Small Minus Big factor return (size).
        hml: High Minus Low factor return (value).
        mom: Momentum factor return (Carhart 4-factor only).
        date: Optional date string for the observation.
    """
    portfolio_return: float
    market_return: float
    smb: float = 0.0
    hml: float = 0.0
    mom: float = 0.0
    date: str = ""


@dataclass
class FactorResult:
    """Result of fitting a factor model to observed returns.

    Attributes:
        loadings: Factor loading coefficients (betas).
        alpha: Intercept (excess return not explained by factors).
        annualized_alpha: Alpha annualized (sqrt(252) multiple).
        r_squared: Model fit (proportion of variance explained).
        adj_r_squared: Adjusted R-squared (penalizes for # of factors).
        residual_std: Standard deviation of residuals.
        t_values: T-statistics for each factor loading.
        p_values: P-values for each factor loading.
        n_observations: Number of observations used.
        factor_names: Names of the factors in the model.
        timestamp: When the analysis was computed.
    """
    loadings: dict[str, float]
    alpha: float
    annualized_alpha: float
    r_squared: float
    adj_r_squared: float
    residual_std: float
    t_values: dict[str, float]
    p_values: dict[str, float]
    n_observations: int
    factor_names: list[str]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "loadings": {k: round(v, 4) for k, v in self.loadings.items()},
            "alpha": round(self.alpha, 6),
            "annualized_alpha": round(self.annualized_alpha, 4),
            "r_squared": round(self.r_squared, 4),
            "adj_r_squared": round(self.adj_r_squared, 4),
            "residual_std": round(self.residual_std, 6),
            "t_values": {k: round(v, 4) for k, v in self.t_values.items()},
            "p_values": {k: round(v, 4) for k, v in self.p_values.items()},
            "n_observations": self.n_observations,
            "factor_names": self.factor_names,
            "timestamp": self.timestamp,
        }

    def summary(self) -> str:
        """Generate a human-readable summary of the factor model results."""
        lines = [
            "=" * 60,
            "  Factor Model Attribution",
            "=" * 60,
            f"  Observations:  {self.n_observations}",
            f"  R-squared:     {self.r_squared:.4f}",
            f"  Adj R-squared: {self.adj_r_squared:.4f}",
            f"  Residual σ:    {self.residual_std:.6f}",
            "",
            "  Factor Loadings:",
        ]
        for name in self.factor_names:
            loading = self.loadings.get(name, 0.0)
            t_val = self.t_values.get(name, 0.0)
            p_val = self.p_values.get(name, 1.0)
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
            lines.append(f"    {name:<12s} {loading:>8.4f}  (t={t_val:>6.2f}, p={p_val:.4f}) {sig}")
        lines.extend([
            "",
            f"  Alpha (intercept): {self.alpha:.6f}  (t={self.t_values.get('alpha', 0.0):.2f})",
            f"  Annualized Alpha:  {self.annualized_alpha:.4f}",
            "=" * 60,
        ])
        return "\n".join(lines)


# ── OLSEngine (Ordinary Least Squares) ────────────────────────────────────────


def _ols_regression(
    y: list[float],
    x_matrix: list[list[float]],
    factor_names: list[str],
) -> dict[str, Any]:
    """Compute OLS regression coefficients and statistics.

    Uses the normal equation: β = (X'X)^(-1) X'y
    For small-to-medium datasets (< 10,000 observations, < 20 factors).

    Args:
        y: Dependent variable (portfolio excess returns).
        x_matrix: Independent variables (factor returns), shape (n, k).
        factor_names: Names of each factor (length k).

    Returns:
        Dict with 'coefficients', 'alpha', 'r_squared', 'adj_r_squared',
        'residual_std', 't_values', 'p_values'.
    """
    n = len(y)
    if n < 3:
        return {
            "coefficients": [0.0] * len(factor_names),
            "alpha": 0.0,
            "r_squared": 0.0,
            "adj_r_squared": 0.0,
            "residual_std": 0.0,
            "t_values": [0.0] * len(factor_names),
            "p_values": [1.0] * len(factor_names),
        }

    k = len(factor_names) if x_matrix else 0
    # Build X matrix with intercept column
    X: list[list[float]] = [[1.0] + row for row in x_matrix]  # (n, k+1)

    # Compute X'X and X'y using basic matrix operations
    def _mat_mul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
        """Matrix multiplication."""
        m, n_a = len(A), len(A[0]) if A else 0
        n_b = len(B[0]) if B else 0
        result = [[0.0] * n_b for _ in range(m)]
        for i in range(m):
            for j in range(n_b):
                s = 0.0
                for t in range(n_a):
                    s += A[i][t] * B[t][j]
                result[i][j] = s
        return result

    def _mat_transpose(A: list[list[float]]) -> list[list[float]]:
        """Matrix transpose."""
        m, n_a = len(A), len(A[0]) if A else 0
        return [[A[i][j] for i in range(m)] for j in range(n_a)]

    # X'X
    Xt = _mat_transpose(X)
    XtX = _mat_mul(Xt, X)  # (k+1, k+1)

    # X'y
    y_col = [[v] for v in y]
    Xty = _mat_mul(Xt, y_col)  # (k+1, 1)

    # Solve (X'X) β = X'y using Gaussian elimination
    aug = [XtX[i] + [Xty[i][0]] for i in range(len(XtX))]
    n_eq = len(aug)

    # Forward elimination
    for i in range(n_eq):
        # Find pivot
        max_row = max(range(i, n_eq), key=lambda r: abs(aug[r][i]))
        aug[i], aug[max_row] = aug[max_row], aug[i]

        pivot = aug[i][i]
        if abs(pivot) < 1e-12:
            continue

        for j in range(i + 1, n_eq):
            factor = aug[j][i] / pivot
            for c in range(i, n_eq + 1):
                aug[j][c] -= factor * aug[i][c]

    # Back substitution
    beta = [0.0] * n_eq
    for i in range(n_eq - 1, -1, -1):
        s = aug[i][n_eq]
        for j in range(i + 1, n_eq):
            s -= aug[i][j] * beta[j]
        beta[i] = s / aug[i][i] if abs(aug[i][i]) > 1e-12 else 0.0

    alpha_coef = beta[0]
    factor_coefs = beta[1:]

    # Compute residuals, R-squared
    y_mean = statistics.mean(y) if y else 0.0
    ss_res = 0.0
    ss_tot = 0.0
    residuals: list[float] = []
    for i in range(n):
        y_pred = alpha_coef + sum(factor_coefs[j] * x_matrix[i][j] for j in range(k))
        res = y[i] - y_pred
        residuals.append(res)
        ss_res += res ** 2
        ss_tot += (y[i] - y_mean) ** 2

    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 0.0
    adj_r_squared = 1.0 - (1.0 - r_squared) * (n - 1) / max(n - k - 1, 1)
    residual_std = math.sqrt(ss_res / max(n - k - 1, 1))

    # T-statistics: β_i / SE(β_i)
    # SE(β) = sqrt(σ² * diag(X'X)^(-1))
    try:
        # Compute inverse of X'X
        inv_XtX = _mat_inverse(XtX, n_eq)
        se_beta = [math.sqrt(abs(inv_XtX[i][i]) * residual_std ** 2) for i in range(n_eq)]
    except (ZeroDivisionError, ValueError):
        se_beta = [1.0] * n_eq

    t_values = [beta[i] / se_beta[i] if se_beta[i] > 1e-12 else 0.0 for i in range(n_eq)]
    # Approximate p-values from t-distribution (using normal approximation for n > 30)
    p_values = [2.0 * (1.0 - _norm_cdf(abs(tv))) for tv in t_values]

    return {
        "coefficients": factor_coefs,
        "alpha": alpha_coef,
        "r_squared": r_squared,
        "adj_r_squared": adj_r_squared,
        "residual_std": residual_std,
        "t_values": [t_values[0]] + t_values[1:],
        "p_values": [p_values[0]] + p_values[1:],
    }


def _mat_inverse(A: list[list[float]], n: int) -> list[list[float]]:
    """Compute matrix inverse using Gauss-Jordan elimination."""
    # Augment A with identity
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(A)]

    for i in range(n):
        # Find pivot
        max_row = max(range(i, n), key=lambda r: abs(aug[r][i]))
        aug[i], aug[max_row] = aug[max_row], aug[i]

        pivot = aug[i][i]
        if abs(pivot) < 1e-12:
            raise ZeroDivisionError("Singular matrix")

        # Normalize pivot row
        for j in range(2 * n):
            aug[i][j] /= pivot

        # Eliminate column
        for r in range(n):
            if r != i:
                factor = aug[r][i]
                for j in range(2 * n):
                    aug[r][j] -= factor * aug[i][j]

    return [row[n:] for row in aug]


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation (Abramowitz and Stegun)."""
    if x < -6:
        return 0.0
    if x > 6:
        return 1.0
    b1, b2, b3, b4, b5 = 0.31938153, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    p = 0.2316419
    cdf = 0.5
    if x > 0:
        t = 1.0 / (1.0 + p * x)
        cdf = 1.0 - (math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)) * (
            b1 * t + b2 * t ** 2 + b3 * t ** 3 + b4 * t ** 4 + b5 * t ** 5
        )
    else:
        t = 1.0 / (1.0 + p * (-x))
        cdf = (math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)) * (
            b1 * t + b2 * t ** 2 + b3 * t ** 3 + b4 * t ** 4 + b5 * t ** 5
        )
    return cdf


# ── Base Factor Model ─────────────────────────────────────────────────────────


class BaseFactorModel:
    """Base class for linear factor models.

    Collects return observations and fits an OLS regression to estimate
    factor loadings, alpha, and goodness-of-fit metrics.

    Subclasses define their own factor names and implement `fit()`.
    """

    def __init__(self, factor_names: list[str]):
        self._factor_names = list(factor_names)
        self._observations: list[FactorReturn] = []
        self._lock = threading.RLock()  # type: ignore[name-defined]

    def add_return(self, portfolio_return: float, **factor_returns: Any) -> None:
        """Add a single period return observation.

        Args:
            portfolio_return: Portfolio excess return for the period.
            **factor_returns: Factor returns keyed by name.
                              Must include at least the factor names
                              defined by the model.
        """
        with self._lock:
            fr = FactorReturn(
                portfolio_return=portfolio_return,
                market_return=factor_returns.get("market_return", 0.0),
                smb=factor_returns.get("smb", 0.0),
                hml=factor_returns.get("hml", 0.0),
                mom=factor_returns.get("mom", 0.0),
                date=str(factor_returns.get("date", "")),
            )
            self._observations.append(fr)

    def add_observation(self, obs: FactorReturn) -> None:
        """Add a FactorReturn observation directly."""
        with self._lock:
            self._observations.append(obs)

    @property
    def n_observations(self) -> int:
        return len(self._observations)

    def clear(self) -> None:
        """Clear all observations."""
        with self._lock:
            self._observations.clear()

    def _prepare_regression(self) -> tuple[list[float], list[list[float]]]:
        """Prepare regression data from observations.

        Returns:
            (y, X) where y is portfolio returns and X is factor return matrix.
        """
        y: list[float] = []
        X: list[list[float]] = []
        for obs in self._observations:
            y.append(obs.portfolio_return)
            row = [
                obs.market_return,
                obs.smb if "smb" in self._factor_names else 0.0,
                obs.hml if "hml" in self._factor_names else 0.0,
                obs.mom if "mom" in self._factor_names else 0.0,
            ]
            X.append(row[:len(self._factor_names)])
        return y, X


# ── Fama-French 3-Factor Model ────────────────────────────────────────────────


class FamaFrench3Factor(BaseFactorModel):
    """Fama-French 3-Factor Model.

    Factors:
      - Market (Rm - Rf): Market excess return
      - SMB (Small Minus Big): Size effect
      - HML (High Minus Low): Value effect

    R_squared measures how much of portfolio return variation is explained
    by these three factors. The intercept (alpha) measures manager skill
    not attributable to factor exposures.
    """

    def __init__(self):
        super().__init__(factor_names=["market", "smb", "hml"])

    def fit(self) -> FactorResult:
        """Fit the Fama-French 3-factor model using OLS regression.

        Returns:
            FactorResult with loadings, alpha, R-squared, t-statistics.
        """
        y, X = self._prepare_regression()
        n = len(y)

        if n < 3:
            return FactorResult(
                loadings={"market": 0.0, "smb": 0.0, "hml": 0.0},
                alpha=0.0,
                annualized_alpha=0.0,
                r_squared=0.0,
                adj_r_squared=0.0,
                residual_std=0.0,
                t_values={"alpha": 0.0, "market": 0.0, "smb": 0.0, "hml": 0.0},
                p_values={"alpha": 1.0, "market": 1.0, "smb": 1.0, "hml": 1.0},
                n_observations=n,
                factor_names=["market", "smb", "hml"],
            )

        result = _ols_regression(y, X, ["market", "smb", "hml"])
        coefs = result["coefficients"]
        alpha = result["alpha"]
        # Annualized alpha = daily_alpha * sqrt(252) for trading days
        annualized_alpha = alpha * math.sqrt(252)

        return FactorResult(
            loadings={
                "market": coefs[0] if len(coefs) > 0 else 0.0,
                "smb": coefs[1] if len(coefs) > 1 else 0.0,
                "hml": coefs[2] if len(coefs) > 2 else 0.0,
            },
            alpha=alpha,
            annualized_alpha=annualized_alpha,
            r_squared=result["r_squared"],
            adj_r_squared=result["adj_r_squared"],
            residual_std=result["residual_std"],
            t_values={
                "alpha": result["t_values"][0] if result["t_values"] else 0.0,
                "market": result["t_values"][1] if len(result["t_values"]) > 1 else 0.0,
                "smb": result["t_values"][2] if len(result["t_values"]) > 2 else 0.0,
                "hml": result["t_values"][3] if len(result["t_values"]) > 3 else 0.0,
            },
            p_values={
                "alpha": result["p_values"][0] if result["p_values"] else 1.0,
                "market": result["p_values"][1] if len(result["p_values"]) > 1 else 1.0,
                "smb": result["p_values"][2] if len(result["p_values"]) > 2 else 1.0,
                "hml": result["p_values"][3] if len(result["p_values"]) > 3 else 1.0,
            },
            n_observations=n,
            factor_names=["market", "smb", "hml"],
        )


# ── Carhart 4-Factor Model ────────────────────────────────────────────────────


class Carhart4Factor(BaseFactorModel):
    """Carhart 4-Factor Model (Fama-French + Momentum).

    Factors:
      - Market (Rm - Rf): Market excess return
      - SMB (Small Minus Big): Size effect
      - HML (High Minus Low): Value effect
      - MOM (Momentum): Prior 12-month return momentum

    The momentum factor captures the tendency for stocks with high past
    returns to continue outperforming (and vice versa for losers).
    """

    def __init__(self):
        super().__init__(factor_names=["market", "smb", "hml", "mom"])

    def fit(self) -> FactorResult:
        """Fit the Carhart 4-factor model using OLS regression."""
        y, X = self._prepare_regression()
        n = len(y)

        if n < 4:
            return FactorResult(
                loadings={"market": 0.0, "smb": 0.0, "hml": 0.0, "mom": 0.0},
                alpha=0.0,
                annualized_alpha=0.0,
                r_squared=0.0,
                adj_r_squared=0.0,
                residual_std=0.0,
                t_values={"alpha": 0.0, "market": 0.0, "smb": 0.0, "hml": 0.0, "mom": 0.0},
                p_values={"alpha": 1.0, "market": 1.0, "smb": 1.0, "hml": 1.0, "mom": 1.0},
                n_observations=n,
                factor_names=["market", "smb", "hml", "mom"],
            )

        result = _ols_regression(y, X, ["market", "smb", "hml", "mom"])
        coefs = result["coefficients"]
        alpha = result["alpha"]
        annualized_alpha = alpha * math.sqrt(252)

        return FactorResult(
            loadings={
                "market": coefs[0] if len(coefs) > 0 else 0.0,
                "smb": coefs[1] if len(coefs) > 1 else 0.0,
                "hml": coefs[2] if len(coefs) > 2 else 0.0,
                "mom": coefs[3] if len(coefs) > 3 else 0.0,
            },
            alpha=alpha,
            annualized_alpha=annualized_alpha,
            r_squared=result["r_squared"],
            adj_r_squared=result["adj_r_squared"],
            residual_std=result["residual_std"],
            t_values={
                "alpha": result["t_values"][0] if result["t_values"] else 0.0,
                "market": result["t_values"][1] if len(result["t_values"]) > 1 else 0.0,
                "smb": result["t_values"][2] if len(result["t_values"]) > 2 else 0.0,
                "hml": result["t_values"][3] if len(result["t_values"]) > 3 else 0.0,
                "mom": result["t_values"][4] if len(result["t_values"]) > 4 else 0.0,
            },
            p_values={
                "alpha": result["p_values"][0] if result["p_values"] else 1.0,
                "market": result["p_values"][1] if len(result["p_values"]) > 1 else 1.0,
                "smb": result["p_values"][2] if len(result["p_values"]) > 2 else 1.0,
                "hml": result["p_values"][3] if len(result["p_values"]) > 3 else 1.0,
                "mom": result["p_values"][4] if len(result["p_values"]) > 4 else 1.0,
            },
            n_observations=n,
            factor_names=["market", "smb", "hml", "mom"],
        )


# ── Convenience: compute factor attribution from a list of returns ────────────


def compute_factor_attribution(
    portfolio_returns: list[float],
    market_returns: list[float],
    smb_returns: list[float] | None = None,
    hml_returns: list[float] | None = None,
    mom_returns: list[float] | None = None,
    include_momentum: bool = True,
) -> FactorResult:
    """Compute factor attribution for a sequence of returns.

    A convenience wrapper that creates the appropriate model, adds all
    observations, and fits.

    Args:
        portfolio_returns: List of portfolio excess returns.
        market_returns: List of market excess returns (same length).
        smb_returns: Optional SMB factor returns (Fama-French).
        hml_returns: Optional HML factor returns (Fama-French).
        mom_returns: Optional Momentum factor returns (Carhart).
        include_momentum: If True, use Carhart 4-factor. If False,
                          use Fama-French 3-factor (requires smb/hml).

    Returns:
        FactorResult with loadings, alpha, and fit metrics.
    """
    # Use minimum length across all provided lists to handle mismatched lengths
    n = min(
        len(portfolio_returns),
        len(market_returns),
        len(smb_returns) if smb_returns is not None else len(portfolio_returns),
        len(hml_returns) if hml_returns is not None else len(portfolio_returns),
        len(mom_returns) if mom_returns is not None else len(portfolio_returns),
    )
    # Truncate all lists to safe length
    portfolio_returns = portfolio_returns[:n]
    market_returns = market_returns[:n]
    use_smb = smb_returns is not None and len(smb_returns) >= n
    use_hml = hml_returns is not None and len(hml_returns) >= n
    use_mom = mom_returns is not None and len(mom_returns) >= n and include_momentum
    if use_smb and smb_returns:
        smb_returns = smb_returns[:n]
    if use_hml and hml_returns:
        hml_returns = hml_returns[:n]
    if use_mom and mom_returns:
        mom_returns = mom_returns[:n]

    if use_mom and use_smb and use_hml:
        model = Carhart4Factor()
        smb = smb_returns or [0.0] * n
        hml = hml_returns or [0.0] * n
        mom = mom_returns or [0.0] * n
        for i in range(n):
            model.add_return(
                portfolio_return=portfolio_returns[i],
                market_return=market_returns[i],
                smb=smb[i],
                hml=hml[i],
                mom=mom[i],
            )
    elif use_smb and use_hml:
        model = FamaFrench3Factor()
        smb = smb_returns or [0.0] * n
        hml = hml_returns or [0.0] * n
        for i in range(n):
            model.add_return(
                portfolio_return=portfolio_returns[i],
                market_return=market_returns[i],
                smb=smb[i],
                hml=hml[i],
            )
    else:
        # Single-factor market model
        model = BaseFactorModel(["market"])
        for i in range(n):
            model.add_return(
                portfolio_return=portfolio_returns[i],
                market_return=market_returns[i],
            )
        # Fit manually as a 1-factor model
        result = _ols_regression(portfolio_returns, [[m] for m in market_returns], ["market"])
        return FactorResult(
            loadings={"market": result["coefficients"][0] if result["coefficients"] else 0.0},
            alpha=result["alpha"],
            annualized_alpha=result["alpha"] * math.sqrt(252),
            r_squared=result["r_squared"],
            adj_r_squared=result["adj_r_squared"],
            residual_std=result["residual_std"],
            t_values={"alpha": result["t_values"][0], "market": result["t_values"][1] if len(result["t_values"]) > 1 else 0.0},
            p_values={"alpha": result["p_values"][0], "market": result["p_values"][1] if len(result["p_values"]) > 1 else 1.0},
            n_observations=n,
            factor_names=["market"],
        )

    return model.fit()


# ── Portfolio Attribution ────────────────────────────────────────────────────


@dataclass
class PortfolioAttribution:
    """Breakdown of portfolio return into factor contributions and residual alpha.

    Attributes:
        factor_contributions: Dict mapping factor name → return contribution.
        alpha_contribution: Return contribution from alpha (manager skill).
        total_return: Total portfolio return being attributed.
        explained_return: Sum of factor contributions.
        unexplained_return: Return not explained by factors (alpha + residual).
        attribution_error: Rounding error check (should be near zero).
        factor_names: Names of factors in order.
    """
    factor_contributions: dict[str, float]
    alpha_contribution: float
    total_return: float
    explained_return: float
    unexplained_return: float
    attribution_error: float
    factor_names: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_contributions": {k: round(v, 6) for k, v in self.factor_contributions.items()},
            "alpha_contribution": round(self.alpha_contribution, 6),
            "total_return": round(self.total_return, 6),
            "explained_return": round(self.explained_return, 6),
            "unexplained_return": round(self.unexplained_return, 6),
            "attribution_error": round(self.attribution_error, 10),
            "factor_names": self.factor_names,
        }

    def summary(self) -> str:
        lines = ["=" * 60, "  Portfolio Return Attribution", "=" * 60]
        lines.append(f"  Total Return:        {self.total_return:>10.4f} ({self.total_return*100:.2f}%)")
        lines.append(f"  Explained Return:    {self.explained_return:>10.4f} ({self.explained_return*100:.2f}%)")
        lines.append(f"  Unexplained (Alpha): {self.unexplained_return:>10.4f} ({self.unexplained_return*100:.2f}%)")
        lines.append("")
        lines.append("  Factor Contributions:")
        for name in self.factor_names:
            contrib = self.factor_contributions.get(name, 0.0)
            pct = contrib / self.total_return * 100 if abs(self.total_return) > 1e-12 else 0.0
            lines.append(f"    {name:<12s} {contrib:>10.6f} ({pct:>5.1f}% of return)")
        lines.append("=" * 60)
        return "\n".join(lines)


@dataclass
class RiskAttribution:
    """Breakdown of portfolio risk into factor contributions.

    Attributes:
        factor_risk_contributions: Dict mapping factor name → risk contribution.
        specific_risk: Risk not explained by factors (idiosyncratic).
        total_risk: Total portfolio risk (volatility).
        explained_risk_pct: Percentage of risk explained by factors.
        factor_risk_pct: Dict mapping factor name → % of total risk explained.
        marginal_ctr: Marginal risk contribution for each factor.
        risk_names: Names of factors.
    """
    factor_risk_contributions: dict[str, float]
    specific_risk: float
    total_risk: float
    explained_risk_pct: float
    factor_risk_pct: dict[str, float]
    marginal_ctr: dict[str, float]
    risk_names: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_risk_contributions": {k: round(v, 6) for k, v in self.factor_risk_contributions.items()},
            "specific_risk": round(self.specific_risk, 6),
            "total_risk": round(self.total_risk, 6),
            "explained_risk_pct": round(self.explained_risk_pct, 2),
            "factor_risk_pct": {k: round(v, 2) for k, v in self.factor_risk_pct.items()},
            "marginal_ctr": {k: round(v, 6) for k, v in self.marginal_ctr.items()},
            "risk_names": self.risk_names,
        }

    def summary(self) -> str:
        lines = ["=" * 60, "  Portfolio Risk Attribution", "=" * 60]
        lines.append(f"  Total Risk (σ):     {self.total_risk:>10.4f}")
        lines.append(f"  Specific Risk:      {self.specific_risk:>10.6f}")
        lines.append(f"  Explained by Factors: {self.explained_risk_pct:.1f}%")
        lines.append("")
        lines.append("  Factor Risk Contributions:")
        for name in self.risk_names:
            contrib = self.factor_risk_contributions.get(name, 0.0)
            pct = self.factor_risk_pct.get(name, 0.0)
            mctr = self.marginal_ctr.get(name, 0.0)
            lines.append(f"    {name:<12s} risk={contrib:>10.6f}  ({pct:>5.1f}%)  MCTR={mctr:.4f}")
        lines.append("=" * 60)
        return "\n".join(lines)


def compute_portfolio_attribution(
    portfolio_return: float,
    factor_loadings: dict[str, float],
    factor_returns: dict[str, float],
    alpha: float = 0.0,
) -> PortfolioAttribution:
    """Compute portfolio return attribution from factor loadings and factor returns.

    Decomposes a single-period portfolio return into:
      - Factor contributions (loading_i × return_i for each factor)
      - Alpha contribution (residual not explained by factors)

    Args:
        portfolio_return: Single-period portfolio return (e.g., 0.02 for 2%)
        factor_loadings: Factor betas (e.g., {"market": 1.05, "smb": 0.3})
        factor_returns: Factor period returns (e.g., {"market": 0.015, "smb": -0.005})
        alpha: Pre-computed alpha (intercept) if available.

    Returns:
        PortfolioAttribution with full breakdown.
    """
    factor_contributions: dict[str, float] = {}
    explained = 0.0
    factor_names: list[str] = []

    for factor_name in factor_loadings:
        if factor_name in factor_returns:
            contrib = factor_loadings[factor_name] * factor_returns[factor_name]
            factor_contributions[factor_name] = contrib
            explained += contrib
            factor_names.append(factor_name)

    # Determine alpha: use provided alpha if non-zero, else compute as residual
    if abs(alpha) > 1e-12:
        alpha_used = alpha
    else:
        alpha_used = portfolio_return - explained

    unexplained = alpha_used  # alpha IS the unexplained return
    attribution_error = abs(alpha_used - (portfolio_return - explained))

    return PortfolioAttribution(
        factor_contributions=factor_contributions,
        alpha_contribution=alpha_used,
        total_return=portfolio_return,
        explained_return=explained,
        unexplained_return=unexplained,
        attribution_error=attribution_error,
        factor_names=factor_names,
    )


def compute_risk_attribution(
    factor_loadings: dict[str, float],
    factor_cov_matrix: dict[str, dict[str, float]],
    specific_variance: float = 0.0,
) -> RiskAttribution:
    """Compute portfolio risk attribution from factor loadings and covariance matrix.

    Decomposes portfolio variance into:
      - Systematic risk from each factor
      - Specific (idiosyncratic) risk
      - Marginal contribution to risk (MCTR) for each factor

    Portfolio variance = β' Σ β + σ²_specific
    where Σ is the factor covariance matrix.

    Args:
        factor_loadings: Factor betas (e.g., {"market": 1.05, "smb": 0.3})
        factor_cov_matrix: Factor covariance matrix (dict of dicts)
        specific_variance: Idiosyncratic variance not explained by factors

    Returns:
        RiskAttribution with full breakdown.
    """
    factor_names = list(factor_loadings.keys())

    # Compute systematic variance: β' Σ β
    # First compute Σ β
    sigma_beta: dict[str, float] = {}
    for fi in factor_names:
        total = 0.0
        for fj in factor_names:
            cov_ij = factor_cov_matrix.get(fi, {}).get(fj, 0.0)
            total += cov_ij * factor_loadings.get(fj, 0.0)
        sigma_beta[fi] = total

    # Then compute β' (Σ β) = sum of β_i * (Σ β)_i
    systematic_variance = sum(
        factor_loadings.get(f, 0.0) * sigma_beta.get(f, 0.0)
        for f in factor_names
    )

    total_variance = systematic_variance + specific_variance
    total_risk = math.sqrt(max(total_variance, 0.0))

    # Factor risk contributions (component of systematic variance)
    factor_risk_contributions: dict[str, float] = {}
    factor_risk_pct: dict[str, float] = {}
    marginal_ctr: dict[str, float] = {}

    for f in factor_names:
        beta_f = factor_loadings.get(f, 0.0)
        sigma_beta_f = sigma_beta.get(f, 0.0)

        # Risk contribution = β_f × (Σ β)_f / σ_portfolio
        contrib = beta_f * sigma_beta_f
        factor_risk_contributions[f] = contrib

        # Percentage of total risk
        if total_variance > 1e-12:
            factor_risk_pct[f] = contrib / total_variance * 100.0
        else:
            factor_risk_pct[f] = 0.0

        # Marginal contribution to risk (MCTR)
        # MCTR_f = (Σ β)_f / σ_portfolio
        if total_risk > 1e-12:
            marginal_ctr[f] = sigma_beta_f / total_risk
        else:
            marginal_ctr[f] = 0.0

    explained_risk_pct = systematic_variance / total_variance * 100.0 if total_variance > 1e-12 else 0.0
    specific_risk = math.sqrt(specific_variance) if specific_variance > 0 else 0.0

    return RiskAttribution(
        factor_risk_contributions=factor_risk_contributions,
        specific_risk=specific_risk,
        total_risk=total_risk,
        explained_risk_pct=explained_risk_pct,
        factor_risk_pct=factor_risk_pct,
        marginal_ctr=marginal_ctr,
        risk_names=factor_names,
    )


# ── CLI ──────────────────────────────────────────────────────────────────────


def _demo_data() -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    """Generate demo return data for CLI demonstration.

    Creates 252 daily observations with realistic factor structure:
      - Market beta ~1.0
      - SMB loading ~0.3
      - HML loading ~0.2
      - MOM loading ~0.1
      - Alpha ~0.0005/day (~0.8% annualized)
    """
    import random
    random.seed(42)
    n = 252
    mkt = [random.gauss(0.0005, 0.01) for _ in range(n)]
    smb = [random.gauss(0.0001, 0.005) for _ in range(n)]
    hml = [random.gauss(0.0002, 0.004) for _ in range(n)]
    mom = [random.gauss(0.0001, 0.003) for _ in range(n)]
    pf = [0.0005 + 1.0 * mkt[i] + 0.3 * smb[i] + 0.2 * hml[i] + 0.1 * mom[i] + random.gauss(0, 0.005) for i in range(n)]
    return pf, mkt, smb, hml, mom


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.factor_models")
    ap.add_argument("--demo", action="store_true", help="Run with demo data")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--model", choices=["ff3", "carhart4", "market"], default="carhart4",
                    help="Factor model to use (default: carhart4)")
    args = ap.parse_args()

    if args.demo:
        pf, mkt, smb, hml, mom = _demo_data()
        result = compute_factor_attribution(pf, mkt, smb, hml, mom,
                                            include_momentum=(args.model == "carhart4"))
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(result.summary())
    else:
        print("Factor Models CLI")
        print("Run with --demo to see sample attribution output")
        print()
        print("Available models:")
        print("  --model ff3       Fama-French 3-Factor (Market + SMB + HML)")
        print("  --model carhart4  Carhart 4-Factor (+ Momentum) [default]")
        print("  --model market    Single-factor Market model")


if __name__ == "__main__":
    _cli()


__all__ = [
    "BaseFactorModel",
    "Carhart4Factor",
    "FactorResult",
    "FactorReturn",
    "FamaFrench3Factor",
    "PortfolioAttribution",
    "RiskAttribution",
    "compute_factor_attribution",
    "compute_portfolio_attribution",
    "compute_risk_attribution",
]

