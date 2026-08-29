"""Mean-Variance Portfolio Optimization (Phase 9 — Master Prompt).

Computes optimal portfolio weights using Markowitz mean-variance optimization.
Supports maximum Sharpe ratio and minimum volatility objectives.

Usage:
    from core.mean_variance import MeanVarianceOptimizer

    optimizer = MeanVarianceOptimizer()
    result = optimizer.maximize_sharpe(expected_returns={"NIFTY": 0.15, "BANKNIFTY": 0.18},
                                        cov_matrix={("NIFTY","NIFTY"): 0.04, ...})
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

__all__ = [
    "MeanVarianceResult",
    "MeanVarianceOptimizer",
]


@dataclass
class MeanVarianceResult:
    """Result of a mean-variance optimization.

    Attributes:
        weights: Dict mapping asset name → allocation weight.
        expected_return: Portfolio expected return.
        portfolio_variance: Portfolio variance.
        portfolio_volatility: Portfolio volatility (std dev).
        sharpe_ratio: Portfolio Sharpe ratio (if risk_free_rate > 0).
        objective: The optimization objective used.
    """

    weights: dict[str, float] = field(default_factory=dict)
    expected_return: float = 0.0
    portfolio_variance: float = 0.0
    portfolio_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    objective: str = "max_sharpe"

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights,
            "expected_return": round(self.expected_return, 6),
            "portfolio_variance": round(self.portfolio_variance, 6),
            "portfolio_volatility": round(self.portfolio_volatility, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "objective": self.objective,
        }

    def summary(self) -> str:
        lines = [
            f"Mean-Variance Result [{self.objective}]",
            f"  Expected Return:       {self.expected_return:.4f}",
            f"  Portfolio Volatility:  {self.portfolio_volatility:.4f}",
            f"  Sharpe Ratio:          {self.sharpe_ratio:.4f}",
        ]
        lines.append("  Allocations:")
        for asset, w in sorted(self.weights.items()):
            lines.append(f"    {asset:<20s} weight={w:.4f}")
        return "\n".join(lines)


class MeanVarianceOptimizer:
    """Mean-Variance portfolio optimizer.

    Supports maximum Sharpe ratio and minimum volatility objectives using
    iterative gradient-based optimization.

    Config keys (read from optional cfg dict):
        mv_max_iter          : int   default 10000
        mv_tol               : float default 1e-8
        mv_min_weight        : float default 0.0   (minimum per-asset weight)
        mv_max_weight        : float default 1.0   (maximum per-asset weight)
        mv_default_return    : float default 0.12  (default expected return when not provided)
        mv_default_variance  : float default 0.04  (default variance when not provided)
        mv_default_covariance: float default 0.0   (default covariance when not provided)
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg = cfg or {}
        self._max_iter = int(self._cfg.get("mv_max_iter", 10000))
        self._tol = float(self._cfg.get("mv_tol", 1e-8))
        self._min_weight = float(self._cfg.get("mv_min_weight", 0.0))
        self._max_weight = float(self._cfg.get("mv_max_weight", 1.0))
        self._def_return = float(self._cfg.get("mv_default_return", 0.12))
        self._def_var = float(self._cfg.get("mv_default_variance", 0.04))
        self._def_cov = float(self._cfg.get("mv_default_covariance", 0.0))

    def _get_cov(self, a: str, b: str,
                 cov_matrix: dict[tuple[str, str], float] | None) -> float:
        if cov_matrix is None:
            return self._def_var if a == b else self._def_cov
        return cov_matrix.get((a, b),
               cov_matrix.get((b, a),
               self._def_var if a == b else self._def_cov))

    def maximize_sharpe(
        self,
        expected_returns: dict[str, float],
        cov_matrix: dict[tuple[str, str], float] | None = None,
        risk_free_rate: float = 0.065,
    ) -> MeanVarianceResult:
        """Maximize the Sharpe ratio.

        Args:
            expected_returns: Dict mapping asset name → expected annual return.
            cov_matrix: Dict mapping (a, b) → covariance. Symmetric lookup.
            risk_free_rate: Risk-free rate (default 6.5% for Indian context).

        Returns:
            MeanVarianceResult with optimal weights.
        """
        return self._optimize(expected_returns, cov_matrix,
                              objective="max_sharpe", risk_free_rate=risk_free_rate)

    def minimize_volatility(
        self,
        expected_returns: dict[str, float],
        cov_matrix: dict[tuple[str, str], float] | None = None,
    ) -> MeanVarianceResult:
        """Minimize portfolio volatility.

        Args:
            expected_returns: Dict mapping asset name → expected annual return.
            cov_matrix: Dict mapping (a, b) → covariance.

        Returns:
            MeanVarianceResult with minimum variance weights.
        """
        return self._optimize(expected_returns, cov_matrix,
                              objective="min_volatility")

    def _optimize(
        self,
        expected_returns: dict[str, float],
        cov_matrix: dict[tuple[str, str], float] | None,
        objective: str = "max_sharpe",
        risk_free_rate: float = 0.065,
    ) -> MeanVarianceResult:
        assets = list(expected_returns.keys())
        n = len(assets)
        if n == 0:
            return MeanVarianceResult(objective=objective)
        if n == 1:
            er = expected_returns[assets[0]]
            var = self._get_cov(assets[0], assets[0], cov_matrix)
            vol = math.sqrt(max(var, 1e-12))
            sr = (er - risk_free_rate) / max(vol, 1e-12) if vol > 0 else 0.0
            return MeanVarianceResult(
                weights={assets[0]: 1.0},
                expected_return=er,
                portfolio_variance=var,
                portfolio_volatility=vol,
                sharpe_ratio=sr,
                objective=objective,
            )

        w = {a: 1.0 / n for a in assets}

        for iteration in range(self._max_iter):
            # Portfolio return and variance
            p_ret = sum(w[a] * expected_returns.get(a, self._def_return) for a in assets)
            p_var = 0.0
            for i in range(n):
                for j in range(n):
                    p_var += w[assets[i]] * w[assets[j]] * self._get_cov(assets[i], assets[j], cov_matrix)
            p_vol = math.sqrt(max(p_var, 1e-12))

            # Gradient
            grad = {}
            if objective == "max_sharpe":
                sr = (p_ret - risk_free_rate) / max(p_vol, 1e-12)
                for a in assets:
                    d_ret = expected_returns.get(a, self._def_return)
                    d_var = 2 * sum(w[aj] * self._get_cov(a, aj, cov_matrix) for aj in assets)
                    d_vol = d_var / max(2 * p_vol, 1e-12)
                    grad[a] = (d_ret * p_vol - (p_ret - risk_free_rate) * d_vol) / max(p_vol ** 2, 1e-12)
            else:  # min_volatility
                for a in assets:
                    d_var = 2 * sum(w[aj] * self._get_cov(a, aj, cov_matrix) for aj in assets)
                    grad[a] = d_var / max(2 * p_vol, 1e-12)

            # Gradient descent step
            step = 0.01 / max(max(abs(g) for g in grad.values()), 1e-12)
            new_w = {}
            for a in assets:
                delta = -step * grad[a] if objective == "min_volatility" else step * grad[a]
                new_w[a] = max(self._min_weight, min(self._max_weight, w[a] + delta))

            total = sum(new_w.values()) or 1.0
            w = {a: v / total for a, v in new_w.items()}

            # Check convergence
            if max(abs(g) for g in grad.values()) < self._tol:
                break

        # Final metrics
        p_ret = sum(w[a] * expected_returns.get(a, self._def_return) for a in assets)
        p_var = 0.0
        for i in range(n):
            for j in range(n):
                p_var += w[assets[i]] * w[assets[j]] * self._get_cov(assets[i], assets[j], cov_matrix)
        p_vol = math.sqrt(max(p_var, 1e-12))
        sr = (p_ret - risk_free_rate) / max(p_vol, 1e-12) if p_vol > 0 else 0.0

        return MeanVarianceResult(
            weights=w,
            expected_return=p_ret,
            portfolio_variance=p_var,
            portfolio_volatility=round(p_vol, 6),
            sharpe_ratio=round(sr, 4),
            objective=objective,
        )
