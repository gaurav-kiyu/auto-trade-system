"""CVaR (Conditional Value at Risk) Optimization (Phase 9 — Master Prompt).

Computes portfolio CVaR (Expected Shortfall) and optimizes weights to
minimize CVaR at a given confidence level.

Usage:
    from core.cvar_optimization import CVaROptimizer

    optimizer = CVaROptimizer()
    result = optimizer.minimize_cvar(returns={"NIFTY": [...], "BANKNIFTY": [...]})
    print(result.cvar, result.weights)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

__all__ = [
    "CVaRResult",
    "CVaROptimizer",
]


@dataclass
class CVaRResult:
    """Result of a CVaR optimization.

    Attributes:
        weights: Dict mapping asset name → allocation weight.
        cvar: Portfolio CVaR (Expected Shortfall) value.
        var: Portfolio VaR at the specified confidence level.
        confidence_level: The confidence level used (e.g., 0.95).
        objective: Objective type ("min_cvar" or "evaluate").
    """

    weights: dict[str, float] = field(default_factory=dict)
    cvar: float = 0.0
    var: float = 0.0
    confidence_level: float = 0.95
    objective: str = "evaluate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights,
            "cvar": round(self.cvar, 6),
            "var": round(self.var, 6),
            "confidence_level": self.confidence_level,
            "objective": self.objective,
        }

    def summary(self) -> str:
        return (
            f"CVaR Result [{self.objective}]\n"
            f"  Confidence Level: {self.confidence_level:.0%}\n"
            f"  VaR:              {self.var:.4f}\n"
            f"  CVaR:             {self.cvar:.4f}\n"
            f"  Allocations:\n"
            + "\n".join(f"    {a:<20s} weight={w:.4f}"
                        for a, w in sorted(self.weights.items()))
        )


class CVaROptimizer:
    """CVaR (Expected Shortfall) optimizer.

    Computes portfolio CVaR from historical return scenarios and finds
    the weight allocation that minimizes CVaR.

    Config keys (read from optional cfg dict):
        cvar_confidence      : float default 0.95  (confidence level for VaR/CVaR)
        cvar_max_iter        : int   default 5000
        cvar_tol             : float default 1e-6
        cvar_min_weight      : float default 0.0
        cvar_max_weight      : float default 1.0
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg = cfg or {}
        self._confidence = float(self._cfg.get("cvar_confidence", 0.95))
        self._max_iter = int(self._cfg.get("cvar_max_iter", 5000))
        self._tol = float(self._cfg.get("cvar_tol", 1e-6))
        self._min_weight = float(self._cfg.get("cvar_min_weight", 0.0))
        self._max_weight = float(self._cfg.get("cvar_max_weight", 1.0))

    def evaluate(
        self,
        returns: dict[str, list[float]],
        weights: dict[str, float],
        confidence: float | None = None,
    ) -> CVaRResult:
        """Evaluate CVaR of a portfolio given historical returns and weights.

        Args:
            returns: Dict mapping asset name → list of historical returns.
            weights: Dict mapping asset name → portfolio weight.
            confidence: Confidence level (default: from config).

        Returns:
            CVaRResult with VaR and CVaR values.
        """
        conf = confidence or self._confidence
        portfolio_returns = self._portfolio_returns(returns, weights)
        if not portfolio_returns:
            return CVaRResult(weights=weights, confidence_level=conf)

        sorted_ret = sorted(portfolio_returns)
        n = len(sorted_ret)
        var_index = max(0, int(n * (1 - conf)) - 1)
        var = sorted_ret[var_index]
        cvar = sum(sorted_ret[:var_index + 1]) / max(var_index + 1, 1)

        return CVaRResult(
            weights=weights,
            cvar=round(cvar, 6),
            var=round(var, 6),
            confidence_level=conf,
            objective="evaluate",
        )

    def minimize_cvar(
        self,
        returns: dict[str, list[float]],
        confidence: float | None = None,
    ) -> CVaRResult:
        """Find portfolio weights that minimize CVaR.

        Args:
            returns: Dict mapping asset name → list of historical returns.
            confidence: Confidence level (default: from config).

        Returns:
            CVaRResult with optimal weights and minimized CVaR.
        """
        conf = confidence or self._confidence
        assets = list(returns.keys())
        n = len(assets)
        if n == 0:
            return CVaRResult(confidence_level=conf, objective="min_cvar")
        if n == 1:
            result = self.evaluate(returns, {assets[0]: 1.0}, conf)
            result.objective = "min_cvar"
            return result

        w = {a: 1.0 / n for a in assets}
        best_w = dict(w)
        best_cvar = float("inf")

        for iteration in range(self._max_iter):
            pr = self._portfolio_returns(returns, w)
            if not pr:
                break

            sorted_ret = sorted(pr)
            n_s = len(sorted_ret)
            var_idx = max(0, int(n_s * (1 - conf)) - 1)
            cvar = sum(sorted_ret[:var_idx + 1]) / max(var_idx + 1, 1)

            if cvar < best_cvar:
                best_cvar = cvar
                best_w = dict(w)

            # Identify tail scenarios
            tail_returns = sorted_ret[:var_idx + 1]
            if not tail_returns:
                break

            # Gradient: increase weight in assets that perform better in tail
            tail_asset_returns: dict[str, float] = {a: 0.0 for a in assets}
            for r in tail_returns:
                for a in assets:
                    # Approximate which asset contributed to this tail return
                    tail_asset_returns[a] += r / max(len(tail_returns), 1)

            step = 0.1 / max(max(abs(v) for v in tail_asset_returns.values()), 1e-12)
            new_w = {}
            for a in assets:
                delta = -step * tail_asset_returns[a]
                new_w[a] = max(self._min_weight, min(self._max_weight, w[a] + delta))

            total = sum(new_w.values()) or 1.0
            w = {a: v / total for a, v in new_w.items()}

            if iteration > 100 and abs(best_cvar - cvar) < self._tol:
                break

        result = self.evaluate(returns, best_w, conf)
        result.objective = "min_cvar"
        return result

    def _portfolio_returns(
        self,
        returns: dict[str, list[float]],
        weights: dict[str, float],
    ) -> list[float]:
        """Compute portfolio returns from individual asset returns and weights."""
        if not returns or not weights:
            return []
        min_len = min(len(v) for v in returns.values() if v)
        if min_len == 0:
            return []
        portfolio_ret: list[float] = []
        for i in range(min_len):
            total = sum(weights.get(a, 0.0) * returns[a][i] for a in returns if i < len(returns[a]))
            portfolio_ret.append(total)
        return portfolio_ret
