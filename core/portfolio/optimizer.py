"""
Portfolio Optimization Engine — Mean-Variance, Risk-Parity, Efficient Frontier.

Provides institutional-grade portfolio optimization methods for computing
optimal capital allocations across a basket of assets/trades/strategies.

Methods
-------
- Mean-Variance Optimization (Markowitz)
- Maximum Sharpe Ratio Portfolio
- Minimum Volatility Portfolio
- Risk-Parity (Inverse Volatility)
- Maximum Diversification
- Efficient Frontier computation

Usage
-----
    from core.portfolio.optimizer import PortfolioOptimizer

    optimizer = PortfolioOptimizer()
    result = optimizer.max_sharpe(returns, cov_matrix)
    print(result.summary())

Config keys
-----------
    None required.  All parameters are function arguments with safe defaults.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── Result dataclasses ──────────────────────────────────────────────────────

@dataclass
class OptimizationResult:
    """Result of a single portfolio optimization run."""

    method: str                          # "max_sharpe" | "min_vol" | "risk_parity" | "max_div" | "efficient_frontier"
    weights: dict[str, float]            # Asset name -> weight (0-1)
    expected_return: float               # Portfolio expected return
    expected_volatility: float           # Portfolio expected volatility (std dev)
    sharpe_ratio: float                  # Sharpe ratio (if risk-free rate known)
    diversification_ratio: float         # Diversification ratio (>= 1 means diversified)
    n_assets: int                        # Number of assets in the portfolio
    status: str = "SUCCESS"              # SUCCESS | WARNING | FAILED
    message: str = ""                    # Status description or error message
    details: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """Return a human-readable summary."""
        lines = [
            f"Portfolio Optimization [{self.method}]",
            f"  Status: {self.status}",
            f"  Assets: {self.n_assets}",
            f"  Expected Return: {self.expected_return:.4f} ({self.expected_return*100:.2f}%)",
            f"  Expected Volatility: {self.expected_volatility:.4f} ({self.expected_volatility*100:.2f}%)",
            f"  Sharpe Ratio: {self.sharpe_ratio:.4f}",
            f"  Diversification Ratio: {self.diversification_ratio:.4f}",
            f"  Weights:",
        ]
        for symbol, wt in sorted(self.weights.items(), key=lambda x: -x[1]):
            lines.append(f"    {symbol:<20s} {wt:>8.4f} ({wt*100:>5.1f}%)")
        if self.message:
            lines.append(f"  Message: {self.message}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON audit records."""
        return {
            "method": self.method,
            "weights": self.weights,
            "expected_return": round(self.expected_return, 6),
            "expected_volatility": round(self.expected_volatility, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 6),
            "diversification_ratio": round(self.diversification_ratio, 6),
            "n_assets": self.n_assets,
            "status": self.status,
            "message": self.message,
        }


@dataclass
class EfficientFrontierResult:
    """Result containing the full efficient frontier."""

    portfolios: list[OptimizationResult] = field(default_factory=list)
    max_sharpe_portfolio: OptimizationResult | None = None
    min_vol_portfolio: OptimizationResult | None = None
    n_points: int = 0

    def summary(self) -> str:
        """Return a human-readable summary."""
        lines = [
            f"Efficient Frontier ({self.n_points} points)",
            "",
        ]
        if self.max_sharpe_portfolio:
            lines.append("Maximum Sharpe Ratio Portfolio:")
            for ln in self.max_sharpe_portfolio.summary().split("\n"):
                lines.append(f"  {ln}")
            lines.append("")
        if self.min_vol_portfolio:
            lines.append("Minimum Volatility Portfolio:")
            for ln in self.min_vol_portfolio.summary().split("\n"):
                lines.append(f"  {ln}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "n_points": self.n_points,
            "max_sharpe": self.max_sharpe_portfolio.to_dict() if self.max_sharpe_portfolio else None,
            "min_vol": self.min_vol_portfolio.to_dict() if self.min_vol_portfolio else None,
            "frontier": [p.to_dict() for p in self.portfolios[:100]],  # cap for serialization
        }


# ── Core Portfolio Optimizer ───────────────────────────────────────────────

class PortfolioOptimizer:
    """
    Portfolio Optimization Engine.

    Implements mean-variance optimization (Markowitz), risk-parity, and
    maximum diversification methods without external solver dependencies.
    Uses grid-search over weight space for the efficient frontier.

    All methods expect:
      - returns: dict[str, float]  — expected annual return per asset
      - cov_matrix: dict[str, dict[str, float]] — covariance matrix
      - risk_free_rate: float — risk-free rate for Sharpe (default 0.05 = 5%)
    """

    def __init__(self, n_grid: int = 1000):
        """
        Args:
            n_grid: Number of points to sample on the efficient frontier grid.
                    Higher values yield smoother frontiers but slower computation.
        """
        self._n_grid = max(100, min(n_grid, 10000))

    # ── Portfolio statistics ──────────────────────────────────────────────

    def _portfolio_return(self, weights: dict[str, float],
                          returns: dict[str, float]) -> float:
        """Compute portfolio expected return given weights."""
        total = 0.0
        for symbol, wt in weights.items():
            total += wt * returns.get(symbol, 0.0)
        return total

    def _portfolio_volatility(self, weights: dict[str, float],
                              cov_matrix: dict[str, dict[str, float]]) -> float:
        """Compute portfolio variance/std dev given weights and covariance."""
        symbols = list(weights.keys())
        var = 0.0
        for si in symbols:
            wi = weights.get(si, 0.0)
            if wi == 0:
                continue
            for sj in symbols:
                wj = weights.get(sj, 0.0)
                if wj == 0:
                    continue
                cov_ij = cov_matrix.get(si, {}).get(sj, 0.0)
                var += wi * wj * cov_ij
        return math.sqrt(max(var, 0.0))

    def _portfolio_sharpe(self, ret: float, vol: float,
                          risk_free_rate: float) -> float:
        """Compute Sharpe ratio."""
        if vol <= 0:
            return 0.0
        return (ret - risk_free_rate) / vol

    def _diversification_ratio(self, weights: dict[str, float],
                                volatility: dict[str, float],
                                portfolio_vol: float) -> float:
        """Compute diversification ratio: weighted avg vol / portfolio vol."""
        if portfolio_vol <= 0:
            return 1.0
        weighted_vol = sum(weights.get(s, 0.0) * volatility.get(s, 0.0)
                          for s in weights)
        return weighted_vol / portfolio_vol if portfolio_vol > 0 else 1.0

    # ── Validation ────────────────────────────────────────────────────────

    def _validate_inputs(self, returns: dict[str, float],
                         cov_matrix: dict[str, dict[str, float]]) -> list[str]:
        """Validate inputs and return list of structural issues (not asset count)."""
        issues: list[str] = []

        if not returns:
            issues.append("Returns dict is empty")
        if not cov_matrix:
            issues.append("Covariance matrix is empty")

        symbols = set(returns.keys()) | set(cov_matrix.keys())

        for s in symbols:
            if s not in returns:
                issues.append(f"Symbol '{s}' has no expected return")
            if s not in cov_matrix:
                issues.append(f"Symbol '{s}' has no covariance data")

        for s, cov in cov_matrix.items():
            for s2 in cov:
                val = cov[s2]
                if not isinstance(val, (int, float)):
                    issues.append(f"Covariance {s}/{s2} is not numeric: {val}")

        return issues

    def _weight_grid(self, symbols: list[str]) -> list[dict[str, float]]:
        """Generate a grid of random weight vectors (simplex)."""
        import random
        rng = random.Random(42)
        portfolios: list[dict[str, float]] = []

        for _ in range(self._n_grid):
            # Generate random weights that sum to 1
            raw = [rng.random() for _ in symbols]
            total = sum(raw)
            weights = {sym: r / total for sym, r in zip(symbols, raw)}
            portfolios.append(weights)

        return portfolios

    # ── Optimization methods ──────────────────────────────────────────────

    def max_sharpe(self, returns: dict[str, float],
                   cov_matrix: dict[str, dict[str, float]],
                   risk_free_rate: float = 0.05) -> OptimizationResult:
        """
        Find the portfolio with the maximum Sharpe ratio.

        Searches the random weight grid for the portfolio that maximizes
        (return - risk_free_rate) / volatility.
        """
        issues = self._validate_inputs(returns, cov_matrix)
        if issues:
            return OptimizationResult(
                method="max_sharpe",
                weights={},
                expected_return=0.0, expected_volatility=0.0,
                sharpe_ratio=0.0, diversification_ratio=1.0,
                n_assets=0, status="FAILED",
                message=f"Validation failed: {'; '.join(issues[:3])}",
            )

        symbols = list(set(returns.keys()) & set(cov_matrix.keys()))
        if len(symbols) < 2:
            # Single asset — optimize by putting all weight there
            sym = symbols[0] if symbols else list(returns.keys())[0] if returns else ""
            if not sym:
                return OptimizationResult(
                    method="max_sharpe", weights={},
                    expected_return=0.0, expected_volatility=0.0,
                    sharpe_ratio=0.0, diversification_ratio=1.0,
                    n_assets=0, status="FAILED", message="No assets available",
                )
            ret = returns.get(sym, 0.0)
            vol = math.sqrt(cov_matrix.get(sym, {}).get(sym, 0.01))
            sharpe = self._portfolio_sharpe(ret, vol, risk_free_rate)
            return OptimizationResult(
                method="max_sharpe", weights={sym: 1.0},
                expected_return=ret, expected_volatility=vol,
                sharpe_ratio=sharpe, diversification_ratio=1.0,
                n_assets=1, status="SUCCESS",
                message="Single asset portfolio",
            )

        # Grid search
        best_sharpe = -float("inf")
        best_weights: dict[str, float] = {}
        best_ret = best_vol = 0.0

        portfolios = self._weight_grid(symbols)
        vol_map = {s: math.sqrt(cov_matrix.get(s, {}).get(s, 0.01)) for s in symbols}

        for weights in portfolios:
            ret = self._portfolio_return(weights, returns)
            vol = self._portfolio_volatility(weights, cov_matrix)
            sharpe = self._portfolio_sharpe(ret, vol, risk_free_rate)

            if sharpe > best_sharpe or not best_weights:
                best_sharpe = sharpe
                best_weights = weights
                best_ret = ret
                best_vol = vol

        div_ratio = self._diversification_ratio(best_weights, vol_map, best_vol)
        return OptimizationResult(
            method="max_sharpe", weights=best_weights,
            expected_return=best_ret, expected_volatility=best_vol,
            sharpe_ratio=best_sharpe, diversification_ratio=div_ratio,
            n_assets=len(symbols), status="SUCCESS",
        )

    def min_volatility(self, returns: dict[str, float],
                       cov_matrix: dict[str, dict[str, float]],
                       risk_free_rate: float = 0.05) -> OptimizationResult:
        """
        Find the portfolio with the minimum volatility (risk).

        Searches the random weight grid for the portfolio with the lowest
        standard deviation.
        """
        issues = self._validate_inputs(returns, cov_matrix)
        if issues:
            return OptimizationResult(
                method="min_vol", weights={},
                expected_return=0.0, expected_volatility=0.0,
                sharpe_ratio=0.0, diversification_ratio=1.0,
                n_assets=0, status="FAILED",
                message=f"Validation failed: {'; '.join(issues[:3])}",
            )

        symbols = list(set(returns.keys()) & set(cov_matrix.keys()))
        if len(symbols) < 2:
            sym = symbols[0] if symbols else list(returns.keys())[0] if returns else ""
            if not sym:
                return OptimizationResult(
                    method="min_vol", weights={},
                    expected_return=0.0, expected_volatility=0.0,
                    sharpe_ratio=0.0, diversification_ratio=1.0,
                    n_assets=0, status="FAILED", message="No assets available",
                )
            ret = returns.get(sym, 0.0)
            vol = math.sqrt(cov_matrix.get(sym, {}).get(sym, 0.01))
            sharpe = self._portfolio_sharpe(ret, vol, risk_free_rate)
            return OptimizationResult(
                method="min_vol", weights={sym: 1.0},
                expected_return=ret,
                expected_volatility=vol,
                sharpe_ratio=sharpe, diversification_ratio=1.0,
                n_assets=1, status="SUCCESS",
            )

        best_vol = float("inf")
        best_weights: dict[str, float] = {}

        portfolios = self._weight_grid(symbols)
        vol_map = {s: math.sqrt(cov_matrix.get(s, {}).get(s, 0.01)) for s in symbols}

        for weights in portfolios:
            vol = self._portfolio_volatility(weights, cov_matrix)
            if vol < best_vol:
                best_vol = vol
                best_weights = weights

        ret = self._portfolio_return(best_weights, returns)
        sharpe = self._portfolio_sharpe(ret, best_vol, risk_free_rate)
        div_ratio = self._diversification_ratio(best_weights, vol_map, best_vol)

        return OptimizationResult(
            method="min_vol", weights=best_weights,
            expected_return=ret, expected_volatility=best_vol,
            sharpe_ratio=sharpe, diversification_ratio=div_ratio,
            n_assets=len(symbols), status="SUCCESS",
        )

    def risk_parity(self, returns: dict[str, float],
                    cov_matrix: dict[str, dict[str, float]],
                    risk_free_rate: float = 0.05) -> OptimizationResult:
        """
        Risk-parity portfolio using inverse-volatility weighting.

        Allocates capital so each asset contributes equally to portfolio risk.
        Simplified implementation: weights inversely proportional to volatility.
        """
        issues = self._validate_inputs(returns, cov_matrix)
        if issues:
            return OptimizationResult(
                method="risk_parity", weights={},
                expected_return=0.0, expected_volatility=0.0,
                sharpe_ratio=0.0, diversification_ratio=1.0,
                n_assets=0, status="FAILED",
                message=f"Validation failed: {'; '.join(issues[:3])}",
            )

        symbols = list(set(returns.keys()) & set(cov_matrix.keys()))
        if not symbols:
            return OptimizationResult(
                method="risk_parity", weights={},
                expected_return=0.0, expected_volatility=0.0,
                sharpe_ratio=0.0, diversification_ratio=1.0,
                n_assets=0, status="FAILED", message="No assets available",
            )

        # Inverse volatility weighting
        vols = {s: math.sqrt(max(cov_matrix.get(s, {}).get(s, 0.0001), 0.0001))
                for s in symbols}
        inv_vol = {s: 1.0 / v for s, v in vols.items()}
        total_inv = sum(inv_vol.values())

        weights = {s: v / total_inv for s, v in inv_vol.items()}
        ret = self._portfolio_return(weights, returns)
        vol = self._portfolio_volatility(weights, cov_matrix)
        sharpe = self._portfolio_sharpe(ret, vol, risk_free_rate)
        div_ratio = self._diversification_ratio(weights, vols, vol)

        return OptimizationResult(
            method="risk_parity", weights=weights,
            expected_return=ret, expected_volatility=vol,
            sharpe_ratio=sharpe, diversification_ratio=div_ratio,
            n_assets=len(symbols), status="SUCCESS",
        )

    def max_diversification(self, returns: dict[str, float],
                            cov_matrix: dict[str, dict[str, float]],
                            risk_free_rate: float = 0.05) -> OptimizationResult:
        """
        Maximum diversification portfolio.

        Maximizes the diversification ratio: weighted average volatility divided
        by portfolio volatility. Higher values indicate better diversification.
        """
        issues = self._validate_inputs(returns, cov_matrix)
        if issues:
            return OptimizationResult(
                method="max_div", weights={},
                expected_return=0.0, expected_volatility=0.0,
                sharpe_ratio=0.0, diversification_ratio=1.0,
                n_assets=0, status="FAILED",
                message=f"Validation failed: {'; '.join(issues[:3])}",
            )

        symbols = list(set(returns.keys()) & set(cov_matrix.keys()))
        if len(symbols) < 2:
            sym = symbols[0] if symbols else list(returns.keys())[0] if returns else ""
            if not sym:
                return OptimizationResult(
                    method="max_div", weights={},
                    expected_return=0.0, expected_volatility=0.0,
                    sharpe_ratio=0.0, diversification_ratio=1.0,
                    n_assets=0, status="FAILED", message="No assets available",
                )
            return OptimizationResult(
                method="max_div", weights={sym: 1.0},
                expected_return=returns.get(sym, 0.0),
                expected_volatility=math.sqrt(cov_matrix.get(sym, {}).get(sym, 0.01)),
                sharpe_ratio=0.0, diversification_ratio=1.0,
                n_assets=1, status="SUCCESS",
            )

        vol_map = {s: math.sqrt(max(cov_matrix.get(s, {}).get(s, 0.0001), 0.0001))
                   for s in symbols}

        best_div = -float("inf")
        best_weights: dict[str, float] = {}
        best_vol = 0.0

        portfolios = self._weight_grid(symbols)
        for weights in portfolios:
            vol = self._portfolio_volatility(weights, cov_matrix)
            if vol <= 0:
                continue
            div_ratio = self._diversification_ratio(weights, vol_map, vol)
            if div_ratio > best_div:
                best_div = div_ratio
                best_weights = weights
                best_vol = vol

        ret = self._portfolio_return(best_weights, returns)
        sharpe = self._portfolio_sharpe(ret, best_vol, risk_free_rate)

        return OptimizationResult(
            method="max_div", weights=best_weights,
            expected_return=ret, expected_volatility=best_vol,
            sharpe_ratio=sharpe, diversification_ratio=best_div,
            n_assets=len(symbols), status="SUCCESS",
        )

    def efficient_frontier(self, returns: dict[str, float],
                           cov_matrix: dict[str, dict[str, float]],
                           risk_free_rate: float = 0.05,
                           n_points: int = 50) -> EfficientFrontierResult:
        """
        Compute the full efficient frontier.

        Finds the efficient frontier by filtering the random weight grid for
        Pareto-optimal portfolios (highest return at each risk level).

        Args:
            returns: Expected returns per asset
            cov_matrix: Covariance matrix
            risk_free_rate: Risk-free rate for Sharpe ratio
            n_points: Number of frontier points to return

        Returns:
            EfficientFrontierResult with frontier, max_sharpe, and min_vol.
        """
        max_sharpe_result = self.max_sharpe(returns, cov_matrix, risk_free_rate)
        min_vol_result = self.min_volatility(returns, cov_matrix, risk_free_rate)

        symbols = list(set(returns.keys()) & set(cov_matrix.keys()))
        if len(symbols) < 2:
            ef = EfficientFrontierResult(
                portfolios=[max_sharpe_result] if max_sharpe_result.status == "SUCCESS" else [],
                max_sharpe_portfolio=max_sharpe_result,
                min_vol_portfolio=min_vol_result,
                n_points=1,
            )
            return ef

        # Generate many portfolios and find Pareto frontier
        portfolios = self._weight_grid(symbols)
        frontier: list[tuple[float, float, dict[str, float]]] = []

        for weights in portfolios:
            ret = self._portfolio_return(weights, returns)
            vol = self._portfolio_volatility(weights, cov_matrix)
            frontier.append((vol, ret, weights))

        # Sort by volatility
        frontier.sort(key=lambda x: x[0])

        # Filter for Pareto efficiency: keep only portfolios with
        # strictly increasing return as volatility increases
        pareto: list[tuple[float, float, dict[str, float]]] = []
        max_ret_so_far = -float("inf")
        for vol, ret, weights in frontier:
            if ret > max_ret_so_far:
                pareto.append((vol, ret, weights))
                max_ret_so_far = ret

        # Resample to n_points
        step = max(1, len(pareto) // max(n_points, 1))
        sampled = pareto[::step][:n_points]

        vol_map = {s: math.sqrt(max(cov_matrix.get(s, {}).get(s, 0.0001), 0.0001))
                   for s in symbols}

        results: list[OptimizationResult] = []
        for vol, ret, weights in sampled:
            sharpe = self._portfolio_sharpe(ret, vol, risk_free_rate)
            div_ratio = self._diversification_ratio(weights, vol_map, vol)
            results.append(OptimizationResult(
                method="efficient_frontier", weights=weights,
                expected_return=ret, expected_volatility=vol,
                sharpe_ratio=sharpe, diversification_ratio=div_ratio,
                n_assets=len(symbols), status="SUCCESS",
            ))

        return EfficientFrontierResult(
            portfolios=results,
            max_sharpe_portfolio=max_sharpe_result,
            min_vol_portfolio=min_vol_result,
            n_points=len(results),
        )

    def optimize(self, method: str,
                 returns: dict[str, float],
                 cov_matrix: dict[str, dict[str, float]],
                 risk_free_rate: float = 0.05) -> OptimizationResult | EfficientFrontierResult:
        """
        Dispatch to the requested optimization method.

        Args:
            method: "max_sharpe", "min_vol", "risk_parity", "max_div", or "efficient_frontier"
            returns: Expected returns per asset
            cov_matrix: Covariance matrix
            risk_free_rate: Risk-free rate

        Returns:
            OptimizationResult or EfficientFrontierResult
        """
        method_map = {
            "max_sharpe": self.max_sharpe,
            "min_vol": self.min_volatility,
            "risk_parity": self.risk_parity,
            "max_div": self.max_diversification,
            "efficient_frontier": self.efficient_frontier,
        }

        if method not in method_map:
            return OptimizationResult(
                method=method, weights={},
                expected_return=0.0, expected_volatility=0.0,
                sharpe_ratio=0.0, diversification_ratio=1.0,
                n_assets=0, status="FAILED",
                message=f"Unknown method: {method}. Options: {list(method_map.keys())}",
            )

        return method_map[method](returns, cov_matrix, risk_free_rate)

    # ── CVaR (Conditional Value at Risk) Optimization ───────────────────────────

    def _norm_pdf(self, x: float) -> float:
        """Standard normal PDF (no scipy dependency)."""
        return math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)

    def _norm_ppf(self, p: float) -> float:
        """Standard normal quantile function (no scipy dependency).

        Uses the Hastings rational approximation:
          For p > 0.5: x = t - (c0 + c1*t + c2*t^2) / (1 + d1*t + d2*t^2 + d3*t^3)
          For p <= 0.5: x = -ppf(1-p)
        where t = sqrt(-2 * ln(min(p, 1-p)))

        Accurate to ~0.00045, sufficient for portfolio optimization.
        """
        if p <= 0.0:
            return -8.0
        if p >= 1.0:
            return 8.0

        # Hastings coefficients
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308

        # Use the smaller tail for better accuracy
        tail = p if p <= 0.5 else 1.0 - p
        t = math.sqrt(-2.0 * math.log(tail))
        num = c0 + t * (c1 + t * c2)
        den = 1.0 + t * (d1 + t * (d2 + t * d3))
        x = t - num / den

        # Negate for lower tail (p < 0.5)
        if p < 0.5:
            x = -x
        return x

    def cvar_optimization(self, returns: dict[str, float],
                          cov_matrix: dict[str, dict[str, float]],
                          risk_free_rate: float = 0.05,
                          confidence_level: float = 0.95) -> OptimizationResult:
        """
        Find the portfolio that minimizes Conditional Value at Risk (CVaR).

        CVaR (Expected Shortfall) measures the expected loss in the worst
        (1-confidence_level) percentile of outcomes. This optimization finds
        the weight allocation that minimizes this tail risk metric.

        Uses a grid search over weight space, estimating CVaR via portfolio
        variance under a normal distribution assumption:
          CVaR = -μ + σ × φ(Z_α) / (1-α)
        where φ is the standard normal PDF and Z_α is the α-quantile.

        Args:
            returns: Expected returns per asset
            cov_matrix: Covariance matrix
            risk_free_rate: Risk-free rate (used for Sharpe reporting)
            confidence_level: Confidence level for CVaR (default 0.95 = 95%)

        Returns:
            OptimizationResult with weights that minimize CVaR
        """
        issues = self._validate_inputs(returns, cov_matrix)
        if issues:
            return OptimizationResult(
                method="cvar", weights={},
                expected_return=0.0, expected_volatility=0.0,
                sharpe_ratio=0.0, diversification_ratio=1.0,
                n_assets=0, status="FAILED",
                message=f"Validation failed: {'; '.join(issues[:3])}",
            )

        symbols = list(set(returns.keys()) & set(cov_matrix.keys()))
        if not symbols:
            return OptimizationResult(
                method="cvar", weights={},
                expected_return=0.0, expected_volatility=0.0,
                sharpe_ratio=0.0, diversification_ratio=1.0,
                n_assets=0, status="FAILED", message="No assets available",
            )

        # Pre-compute CVaR parameters (no scipy dependency)
        z_alpha = self._norm_ppf(confidence_level)
        pdf_z = self._norm_pdf(z_alpha)
        cvar_factor = pdf_z / (1.0 - confidence_level)

        if len(symbols) < 2:
            sym = symbols[0]
            ret = returns.get(sym, 0.0)
            vol = math.sqrt(max(cov_matrix.get(sym, {}).get(sym, 0.01), 0.0001))
            cvar = -ret + vol * cvar_factor
            sharpe = self._portfolio_sharpe(ret, vol, risk_free_rate)
            return OptimizationResult(
                method="cvar", weights={sym: 1.0},
                expected_return=ret, expected_volatility=vol,
                sharpe_ratio=sharpe, diversification_ratio=1.0,
                n_assets=1, status="SUCCESS",
                details={"cvar": round(cvar, 6)},
            )

        vol_map = {s: math.sqrt(max(cov_matrix.get(s, {}).get(s, 0.0001), 0.0001))
                   for s in symbols}

        best_cvar = float("inf")
        best_weights: dict[str, float] = {}
        best_ret = best_vol = 0.0

        portfolios = self._weight_grid(symbols)
        for weights in portfolios:
            ret = self._portfolio_return(weights, returns)
            vol = self._portfolio_volatility(weights, cov_matrix)
            cvar = -ret + vol * cvar_factor
            if cvar < best_cvar:
                best_cvar = cvar
                best_weights = weights
                best_ret = ret
                best_vol = vol

        sharpe = self._portfolio_sharpe(best_ret, best_vol, risk_free_rate)
        div_ratio = self._diversification_ratio(best_weights, vol_map, best_vol)

        return OptimizationResult(
            method="cvar", weights=best_weights,
            expected_return=best_ret, expected_volatility=best_vol,
            sharpe_ratio=sharpe, diversification_ratio=div_ratio,
            n_assets=len(symbols), status="SUCCESS",
            details={"cvar": round(best_cvar, 6), "confidence_level": confidence_level},
        )

    # ── Equal Risk Contribution (ERC) ───────────────────────────────────────────

    def equal_risk_contribution(self, returns: dict[str, float],
                                cov_matrix: dict[str, dict[str, float]],
                                risk_free_rate: float = 0.05) -> OptimizationResult:
        """
        Equal Risk Contribution portfolio (a.k.a. risk budgeting).

        Allocates capital so that each asset contributes equally to total
        portfolio risk. Unlike risk_parity (inverse volatility), ERC accounts
        for correlations between assets.

        Uses iterative numerical optimization to find weights that equalize
        each asset's marginal risk contribution:
          min Σ_i Σ_j (RC_i - RC_j)²
        where RC_i = w_i × (Σ w)_i / σ_portfolio

        Args:
            returns: Expected returns per asset
            cov_matrix: Covariance matrix
            risk_free_rate: Risk-free rate

        Returns:
            OptimizationResult with ERC weights
        """
        issues = self._validate_inputs(returns, cov_matrix)
        if issues:
            return OptimizationResult(
                method="erc", weights={},
                expected_return=0.0, expected_volatility=0.0,
                sharpe_ratio=0.0, diversification_ratio=1.0,
                n_assets=0, status="FAILED",
                message=f"Validation failed: {'; '.join(issues[:3])}",
            )

        symbols = list(set(returns.keys()) & set(cov_matrix.keys()))
        if not symbols:
            return OptimizationResult(
                method="erc", weights={},
                expected_return=0.0, expected_volatility=0.0,
                sharpe_ratio=0.0, diversification_ratio=1.0,
                n_assets=0, status="FAILED", message="No assets available",
            )

        if len(symbols) < 2:
            sym = symbols[0]
            ret = returns.get(sym, 0.0)
            vol = math.sqrt(max(cov_matrix.get(sym, {}).get(sym, 0.01), 0.0001))
            sharpe = self._portfolio_sharpe(ret, vol, risk_free_rate)
            return OptimizationResult(
                method="erc", weights={sym: 1.0},
                expected_return=ret, expected_volatility=vol,
                sharpe_ratio=sharpe, diversification_ratio=1.0,
                n_assets=1, status="SUCCESS",
            )

        vol_map = {s: math.sqrt(max(cov_matrix.get(s, {}).get(s, 0.0001), 0.0001))
                   for s in symbols}

        # Iterative risk budgeting: start from equal weight, then adjust
        weights = {s: 1.0 / len(symbols) for s in symbols}

        for _iteration in range(100):
            vol = self._portfolio_volatility(weights, cov_matrix)
            if vol <= 1e-12:
                break

            # Compute risk contributions
            rc_squared_sum = 0.0
            target_rc = 1.0 / len(symbols)  # Target: equal risk contribution

            # Σ w (covariance vector)
            sigma_w: dict[str, float] = {}
            for si in symbols:
                total = 0.0
                for sj in symbols:
                    total += cov_matrix.get(si, {}).get(sj, 0.0) * weights.get(sj, 0.0)
                sigma_w[si] = total

            # Compute risk contributions and gradient
            risk_contribs: dict[str, float] = {}
            for s in symbols:
                rc = weights.get(s, 0.0) * sigma_w.get(s, 0.0) / max(vol, 1e-12)
                risk_contribs[s] = rc

            total_rc = sum(risk_contribs.values())
            if total_rc > 1e-12:
                # Normalize risk contributions
                risk_contribs = {s: rc / total_rc for s, rc in risk_contribs.items()}

            # Compute convergence metric: how far from equal risk contribution?
            rc_squared_sum = sum((rc - target_rc) ** 2 for rc in risk_contribs.values())
            if rc_squared_sum < 1e-8:
                break

            # Update weights: scale each weight by (target_rc / rc) and renormalize
            for s in symbols:
                rc_s = risk_contribs.get(s, target_rc)
                if rc_s > 1e-12:
                    weights[s] = weights.get(s, 0.0) * (target_rc / rc_s)

            # Normalize
            total_w = sum(weights.values())
            if total_w > 1e-12:
                weights = {s: w / total_w for s, w in weights.items()}
            else:
                weights = {s: 1.0 / len(symbols) for s in symbols}
                break

        ret = self._portfolio_return(weights, returns)
        vol = self._portfolio_volatility(weights, cov_matrix)
        sharpe = self._portfolio_sharpe(ret, vol, risk_free_rate)
        div_ratio = self._diversification_ratio(weights, vol_map, vol)

        return OptimizationResult(
            method="erc", weights=weights,
            expected_return=ret, expected_volatility=vol,
            sharpe_ratio=sharpe, diversification_ratio=div_ratio,
            n_assets=len(symbols), status="SUCCESS",
            details={"rc_convergence": round(rc_squared_sum, 10)},
        )


# ── Convenience API ───────────────────────────────────────────────────────────

def optimize_portfolio(
    returns: dict[str, float],
    cov_matrix: dict[str, dict[str, float]],
    method: str = "max_sharpe",
    risk_free_rate: float = 0.05,
) -> dict[str, Any]:
    """
    Convenience function — run portfolio optimization and return serializable dict.

    Args:
        returns: Expected annual returns (e.g., {"NIFTY": 0.12, "BANKNIFTY": 0.15})
        cov_matrix: Covariance matrix
        method: Optimization method
        risk_free_rate: Risk-free rate (default 0.05 = 5%)

    Returns:
        Dict suitable for JSON serialization.
    """
    optimizer = PortfolioOptimizer()
    result = optimizer.optimize(method, returns, cov_matrix, risk_free_rate)
    if isinstance(result, EfficientFrontierResult):
        return result.to_dict()
    return result.to_dict()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m core.portfolio.optimizer",
        description="Portfolio Optimization Engine",
    )
    ap.add_argument("--method", default="max_sharpe",
                    choices=["max_sharpe", "min_vol", "risk_parity", "max_div", "efficient_frontier"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--risk-free", type=float, default=0.05)
    args = ap.parse_args()

    # Demo with sample data
    returns = {
        "NIFTY": 0.12,
        "BANKNIFTY": 0.15,
        "FINNIFTY": 0.14,
        "GOLD": 0.08,
    }
    cov_matrix = {
        "NIFTY": {"NIFTY": 0.04, "BANKNIFTY": 0.03, "FINNIFTY": 0.025, "GOLD": 0.005},
        "BANKNIFTY": {"NIFTY": 0.03, "BANKNIFTY": 0.06, "FINNIFTY": 0.035, "GOLD": 0.008},
        "FINNIFTY": {"NIFTY": 0.025, "BANKNIFTY": 0.035, "FINNIFTY": 0.05, "GOLD": 0.006},
        "GOLD": {"NIFTY": 0.005, "BANKNIFTY": 0.008, "FINNIFTY": 0.006, "GOLD": 0.02},
    }

    optimizer = PortfolioOptimizer()
    result = optimizer.optimize(args.method, returns, cov_matrix, args.risk_free)

    if args.json:
        if isinstance(result, EfficientFrontierResult):
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(json.dumps(result.to_dict(), indent=2))
    else:
        if isinstance(result, EfficientFrontierResult):
            print(result.summary())
        else:
            print(result.summary())
