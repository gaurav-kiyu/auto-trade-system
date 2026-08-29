"""Risk Parity Portfolio Optimization (Phase 9 — Master Prompt).

Computes risk-parity allocations where each asset contributes equally to
portfolio risk. Also supports Equal Risk Contribution (ERC) mode.

Usage:
    from core.risk_parity import RiskParityOptimizer

    optimizer = RiskParityOptimizer()
    result = optimizer.optimize(volatilities={"NIFTY": 0.20, "BANKNIFTY": 0.25},
                                 correlations={("NIFTY", "BANKNIFTY"): 0.85})
    print(result.weights)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

__all__ = [
    "RiskParityResult",
    "RiskParityOptimizer",
]


@dataclass
class RiskParityResult:
    """Result of a risk parity optimization.

    Attributes:
        weights: Dict mapping asset name → allocation weight (sums to 1.0).
        risk_contributions: Dict mapping asset name → risk contribution (sums to 1.0).
        portfolio_volatility: Expected portfolio volatility.
        convergence: Whether the optimizer converged.
        iterations: Number of iterations taken.
        method: "risk_parity" or "equal_risk_contribution".
    """

    weights: dict[str, float] = field(default_factory=dict)
    risk_contributions: dict[str, float] = field(default_factory=dict)
    portfolio_volatility: float = 0.0
    convergence: bool = True
    iterations: int = 0
    method: str = "risk_parity"

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights,
            "risk_contributions": self.risk_contributions,
            "portfolio_volatility": round(self.portfolio_volatility, 6),
            "convergence": self.convergence,
            "iterations": self.iterations,
            "method": self.method,
        }

    def summary(self) -> str:
        lines = [
            f"Risk Parity Result [{self.method}]",
            f"  Portfolio Volatility: {self.portfolio_volatility:.4f}",
            f"  Convergence: {self.convergence} ({self.iterations} iterations)",
        ]
        lines.append("  Allocations:")
        for asset, w in sorted(self.weights.items()):
            rc = self.risk_contributions.get(asset, 0.0)
            lines.append(f"    {asset:<20s} weight={w:.4f}  risk_contrib={rc:.4f}")
        return "\n".join(lines)


class RiskParityOptimizer:
    """Risk Parity / Equal Risk Contribution portfolio optimizer.

    Uses iterative gradient-based optimization to find weights where each
    asset contributes equally to portfolio risk.

    Config keys (read from optional cfg dict):
        risk_parity_max_iter    : int   default 1000
        risk_parity_tol         : float default 1e-6
        risk_parity_min_weight  : float default 0.05  (minimum per-asset weight)
        risk_parity_max_weight  : float default 0.60  (maximum per-asset weight)
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg = cfg or {}
        self._max_iter = int(self._cfg.get("risk_parity_max_iter", 1000))
        self._tol = float(self._cfg.get("risk_parity_tol", 1e-6))
        self._min_weight = float(self._cfg.get("risk_parity_min_weight", 0.05))
        self._max_weight = float(self._cfg.get("risk_parity_max_weight", 0.60))

    def optimize(
        self,
        volatilities: dict[str, float],
        correlations: dict[tuple[str, str], float] | None = None,
        method: str = "risk_parity",
        initial_weights: dict[str, float] | None = None,
    ) -> RiskParityResult:
        """Compute risk-parity portfolio weights.

        Args:
            volatilities: Dict mapping asset name → annualized volatility.
            correlations: Dict mapping (asset_a, asset_b) → correlation.
                          Defaults to 0.0 for missing pairs (assumes uncorrelated).
            method: "risk_parity" (equal risk contribution) or "erc"
                    (same algorithm — ERC is a special case of risk parity).
            initial_weights: Starting weights for optimization (default: equal weight).

        Returns:
            RiskParityResult with optimized weights.
        """
        assets = list(volatilities.keys())
        n = len(assets)

        if n == 0:
            return RiskParityResult(method=method)

        if n == 1:
            return RiskParityResult(
                weights={assets[0]: 1.0},
                risk_contributions={assets[0]: 1.0},
                portfolio_volatility=volatilities[assets[0]],
                method=method,
                iterations=0,
            )

        # Build correlation matrix
        corr: dict[tuple[str, str], float] = {}
        if correlations:
            corr.update(correlations)
        for i in range(n):
            for j in range(n):
                if i == j:
                    corr[(assets[i], assets[j])] = 1.0
                elif (assets[i], assets[j]) not in corr:
                    corr[(assets[i], assets[j])] = 0.0
                    corr[(assets[j], assets[i])] = 0.0

        # Initialize weights (equal weight or provided)
        w = {a: 1.0 / n for a in assets}
        if initial_weights and len(initial_weights) == n:
            total = sum(initial_weights.values())
            if total > 0:
                w = {a: v / total for a, v in initial_weights.items()}

        # Iterative optimization: Newton-like method for risk parity
        for iteration in range(self._max_iter):
            # Compute portfolio variance and marginal contributions
            total_var = 0.0
            for i in range(n):
                for j in range(n):
                    ai, aj = assets[i], assets[j]
                    total_var += w[ai] * w[aj] * volatilities[ai] * volatilities[aj] * corr.get((ai, aj), 0.0)

            portfolio_vol = math.sqrt(max(total_var, 1e-12))

            # Marginal risk contributions
            mc = {}
            for i in range(n):
                ai = assets[i]
                m = 0.0
                for j in range(n):
                    aj = assets[j]
                    m += w[aj] * volatilities[ai] * volatilities[aj] * corr.get((ai, aj), 0.0)
                mc[ai] = m / max(portfolio_vol, 1e-12)

            # Risk contributions
            rc = {a: w[a] * mc[a] for a in assets}
            total_rc = sum(rc.values()) if rc else 1.0
            rc_normalized = {a: v / max(total_rc, 1e-12) for a, v in rc.items()}

            # Target: all risk contributions equal (1/n)
            target = 1.0 / n
            max_dev = max(abs(v - target) for v in rc_normalized.values())

            if max_dev < self._tol:
                return RiskParityResult(
                    weights=w,
                    risk_contributions=rc_normalized,
                    portfolio_volatility=round(portfolio_vol, 6),
                    convergence=True,
                    iterations=iteration + 1,
                    method=method,
                )

            # Update weights: increase weight of assets with below-target risk contribution
            step = 0.5 / max(portfolio_vol, 1e-12)
            new_w = {}
            for a in assets:
                deviation = target - rc_normalized[a]
                new_w[a] = w[a] + step * deviation * w[a]
                new_w[a] = max(self._min_weight, min(self._max_weight, new_w[a]))

            # Normalize
            total = sum(new_w.values()) or 1.0
            w = {a: v / total for a, v in new_w.items()}

        # Did not converge within max_iter
        _log.warning("[RISK_PARITY] Did not converge within %d iterations", self._max_iter)

        # Return best result found
        total_var = 0.0
        for i in range(n):
            for j in range(n):
                ai, aj = assets[i], assets[j]
                total_var += w[ai] * w[aj] * volatilities[ai] * volatilities[aj] * corr.get((ai, aj), 0.0)
        pv = math.sqrt(max(total_var, 1e-12))
        rc_final = {a: w[a] * sum(
            w[aj] * volatilities[a] * volatilities[aj] * corr.get((a, aj), 0.0)
            for aj in assets
        ) / max(pv, 1e-12) for a in assets}
        trc = sum(rc_final.values()) or 1.0
        rcn = {a: v / trc for a, v in rc_final.items()}

        return RiskParityResult(
            weights=w,
            risk_contributions=rcn,
            portfolio_volatility=round(pv, 6),
            convergence=False,
            iterations=self._max_iter,
            method=method,
        )


def compute_risk_parity(
    volatilities: dict[str, float],
    correlations: dict[tuple[str, str], float] | None = None,
    cfg: dict[str, Any] | None = None,
) -> RiskParityResult:
    """Convenience function: compute risk parity in one call."""
    return RiskParityOptimizer(cfg).optimize(volatilities, correlations)
