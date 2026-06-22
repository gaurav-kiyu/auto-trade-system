"""
Cross Asset Analytics — Multi-Instrument Correlation & Relative Value Analysis.

Provides institutional-grade analytics across multiple asset classes for:
  - Cross-asset correlation matrix computation
  - Relative value analysis (z-score spread between assets)
  - Regime detection across correlated assets
  - Flight-to-safety detection (risk-off / risk-on)
  - Cross-asset momentum divergence detection
  - Rolling correlation stability monitoring

Usage
-----
    from core.cross_asset_analytics import CrossAssetAnalytics

    analyzer = CrossAssetAnalytics()
    analyzer.add_returns("NIFTY", [0.01, -0.005, 0.02, ...])
    analyzer.add_returns("GOLD", [0.005, 0.01, -0.003, ...])
    corr = analyzer.correlation_matrix()
    print(corr.summary())
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)


# ── Data structures ─────────────────────────────────────────────────────────


@dataclass
class CrossAssetCorrelation:
    """Cross-asset correlation matrix with statistics.

    Attributes:
        matrix: Dict of dicts mapping asset pairs to correlation values.
        avg_correlation: Average pairwise correlation across all assets.
        max_correlation: Maximum pairwise correlation.
        min_correlation: Minimum pairwise correlation.
        n_assets: Number of assets in the matrix.
        n_observations: Number of observations used.
        timestamp: When the analysis was computed.
    """
    matrix: dict[str, dict[str, float]]
    avg_correlation: float
    max_correlation: float
    min_correlation: float
    n_assets: int
    n_observations: int
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "matrix": {k: {k2: round(v2, 4) for k2, v2 in v.items()} for k, v in self.matrix.items()},
            "avg_correlation": round(self.avg_correlation, 4),
            "max_correlation": round(self.max_correlation, 4),
            "min_correlation": round(self.min_correlation, 4),
            "n_assets": self.n_assets,
            "n_observations": self.n_observations,
            "timestamp": self.timestamp,
        }

    def summary(self) -> str:
        lines = ["=" * 60, "  Cross-Asset Correlation Analysis", "=" * 60]
        lines.append(f"  Assets:          {self.n_assets}")
        lines.append(f"  Observations:    {self.n_observations}")
        lines.append(f"  Avg Correlation: {self.avg_correlation:.4f}")
        lines.append(f"  Max Correlation: {self.max_correlation:.4f}")
        lines.append(f"  Min Correlation: {self.min_correlation:.4f}")
        lines.append("")
        lines.append("  Correlation Matrix:")
        assets = list(self.matrix.keys())
        header = "  " + "".join(f"{a:>12s}" for a in assets)
        lines.append(header)
        lines.append("  " + "-" * len(header))
        for a in assets:
            row = f"  {a:<10s}"
            for b in assets:
                row += f"{self.matrix.get(a, {}).get(b, 0.0):>12.4f}"
            lines.append(row)
        lines.append("=" * 60)
        return "\n".join(lines)


@dataclass
class RelativeValueResult:
    """Relative value analysis between two assets.

    Attributes:
        asset_a: Name of the first asset.
        asset_b: Name of the second asset.
        z_score: Current z-score of the spread (how many std devs from mean).
        spread_mean: Mean of the spread over the observation period.
        spread_std: Standard deviation of the spread.
        current_spread: Current spread value (return_a - return_b).
        percentile: Current percentile rank of the spread.
        is_extreme: Whether the z-score exceeds ±2.0 (statistically significant).
        interpretation: Text interpretation of the relative value.
    """
    asset_a: str
    asset_b: str
    z_score: float
    spread_mean: float
    spread_std: float
    current_spread: float
    percentile: float
    is_extreme: bool
    interpretation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_a": self.asset_a,
            "asset_b": self.asset_b,
            "z_score": round(self.z_score, 4),
            "spread_mean": round(self.spread_mean, 6),
            "spread_std": round(self.spread_std, 6),
            "current_spread": round(self.current_spread, 6),
            "percentile": round(self.percentile, 2),
            "is_extreme": self.is_extreme,
            "interpretation": self.interpretation,
        }

    def summary(self) -> str:
        return (
            f"Relative Value: {self.asset_a} vs {self.asset_b}\n"
            f"  Z-Score:       {self.z_score:.4f} ({'EXTREME' if self.is_extreme else 'normal'})\n"
            f"  Spread Mean:   {self.spread_mean:.6f}\n"
            f"  Spread Std:    {self.spread_std:.6f}\n"
            f"  Current:       {self.current_spread:.6f}\n"
            f"  Percentile:    {self.percentile:.1f}%\n"
            f"  Interpretation: {self.interpretation}"
        )


@dataclass
class FlightToSafetyResult:
    """Flight-to-safety detection result.

    Attributes:
        is_flight_to_safety: Whether risk-off conditions are detected.
        risk_asset_performance: Average return of risk assets (equities).
        safe_asset_performance: Average return of safe assets (gold, bonds).
        spread: Performance spread (risk - safe). Negative = risk-off.
        strength: Strength of the signal (NONE, WEAK, MODERATE, STRONG).
        n_observations: Number of observations used.
    """
    is_flight_to_safety: bool
    risk_asset_performance: float
    safe_asset_performance: float
    spread: float
    strength: str
    n_observations: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_flight_to_safety": self.is_flight_to_safety,
            "risk_asset_performance": round(self.risk_asset_performance, 6),
            "safe_asset_performance": round(self.safe_asset_performance, 6),
            "spread": round(self.spread, 6),
            "strength": self.strength,
            "n_observations": self.n_observations,
        }

    def summary(self) -> str:
        return (
            f"Flight to Safety: {'DETECTED' if self.is_flight_to_safety else 'NOT DETECTED'}\n"
            f"  Risk Assets:   {self.risk_asset_performance:+.4f}\n"
            f"  Safe Assets:   {self.safe_asset_performance:+.4f}\n"
            f"  Spread:        {self.spread:+.4f}\n"
            f"  Strength:      {self.strength}"
        )


# ── Analytics Engine ─────────────────────────────────────────────────────────


class CrossAssetAnalytics:
    """Cross-Asset Analytics Engine.

    Maintains return histories for multiple assets and computes:
    - Correlation matrices
    - Relative value z-scores
    - Flight-to-safety detection
    - Momentum divergence
    - Correlation stability
    """

    def __init__(self, min_observations: int = 20):
        self._returns: dict[str, list[float]] = {}
        self._min_obs = max(min_observations, 5)

    def add_returns(self, asset_name: str, returns: list[float]) -> None:
        """Add or update return history for an asset.

        Args:
            asset_name: Name of the asset (e.g., 'NIFTY', 'GOLD').
            returns: List of period returns (same length as other assets).
        """
        self._returns[asset_name] = list(returns)

    def clear(self) -> None:
        """Clear all return histories."""
        self._returns.clear()

    @property
    def n_assets(self) -> int:
        return len(self._returns)

    @property
    def n_observations(self) -> int:
        if not self._returns:
            return 0
        return min(len(v) for v in self._returns.values()) if self._returns else 0

    def _validate(self) -> list[str]:
        """Validate that enough data exists for analysis."""
        issues: list[str] = []
        if self.n_assets < 2:
            issues.append("Need at least 2 assets")
        if self.n_observations < self._min_obs:
            issues.append(f"Need at least {self._min_obs} observations, got {self.n_observations}")
        if self._returns and len(set(len(v) for v in self._returns.values())) > 1:
            issues.append("All assets must have the same number of observations")
        return issues

    # ── Core statistics ──────────────────────────────────────────────────

    def _pearson(self, x: list[float], y: list[float]) -> float:
        """Compute Pearson correlation coefficient."""
        n = min(len(x), len(y))
        if n < 3:
            return 0.0
        x_mean = statistics.mean(x)
        y_mean = statistics.mean(y)
        cov = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        std_x = math.sqrt(sum((xi - x_mean) ** 2 for xi in x))
        std_y = math.sqrt(sum((yi - y_mean) ** 2 for yi in y))
        if std_x * std_y == 0:
            return 0.0
        return cov / (std_x * std_y)

    # ── Correlation Matrix ───────────────────────────────────────────────

    def correlation_matrix(self) -> CrossAssetCorrelation:
        """Compute the full cross-asset correlation matrix.

        Returns:
            CrossAssetCorrelation with the correlation matrix and statistics.
        """
        issues = self._validate()
        if issues:
            return CrossAssetCorrelation(
                matrix={}, avg_correlation=0.0, max_correlation=0.0,
                min_correlation=0.0, n_assets=0, n_observations=0,
            )

        assets = list(self._returns.keys())
        n = len(assets)
        matrix: dict[str, dict[str, float]] = {a: {} for a in assets}
        correlations: list[float] = []

        for i, a in enumerate(assets):
            for j, b in enumerate(assets):
                if i == j:
                    matrix[a][b] = 1.0
                elif b in matrix and a in matrix[b]:
                    matrix[a][b] = matrix[b][a]
                else:
                    corr = self._pearson(self._returns[a], self._returns[b])
                    matrix[a][b] = corr
                    correlations.append(corr)
                    if a != b:
                        matrix[b][a] = corr

        avg_corr = statistics.mean(correlations) if correlations else 0.0
        max_corr = max(correlations) if correlations else 0.0
        min_corr = min(correlations) if correlations else 0.0

        return CrossAssetCorrelation(
            matrix=matrix,
            avg_correlation=avg_corr,
            max_correlation=max_corr,
            min_correlation=min_corr,
            n_assets=n,
            n_observations=self.n_observations,
        )

    # ── Relative Value (Z-Score) ─────────────────────────────────────────

    def relative_value(self, asset_a: str, asset_b: str) -> RelativeValueResult:
        """Compute relative value z-score between two assets.

        The z-score measures how many standard deviations the current spread
        is from its historical mean. Z-scores beyond ±2.0 are considered
        statistically significant.

        Args:
            asset_a: Name of the first asset.
            asset_b: Name of the second asset.

        Returns:
            RelativeValueResult with z-score, spread statistics, and interpretation.
        """
        if asset_a not in self._returns or asset_b not in self._returns:
            return RelativeValueResult(
                asset_a=asset_a, asset_b=asset_b,
                z_score=0.0, spread_mean=0.0, spread_std=0.0,
                current_spread=0.0, percentile=50.0,
                is_extreme=False, interpretation="Missing data",
            )

        ra = self._returns[asset_a]
        rb = self._returns[asset_b]
        n = min(len(ra), len(rb))

        if n < 3:
            return RelativeValueResult(
                asset_a=asset_a, asset_b=asset_b,
                z_score=0.0, spread_mean=0.0, spread_std=0.0,
                current_spread=0.0, percentile=50.0,
                is_extreme=False, interpretation="Insufficient data",
            )

        spreads = [ra[i] - rb[i] for i in range(n)]
        spread_mean = statistics.mean(spreads)
        spread_std = statistics.stdev(spreads) if len(spreads) > 1 else 0.0
        current_spread = spreads[-1] if spreads else 0.0
        z_score = (current_spread - spread_mean) / spread_std if spread_std > 1e-12 else 0.0

        # Percentile rank of current spread
        count_below = sum(1 for s in spreads if s <= current_spread)
        percentile = count_below / len(spreads) * 100.0

        is_extreme = abs(z_score) > 2.0

        if z_score > 2.0:
            interpretation = f"{asset_a} is significantly outperforming {asset_b} (z={z_score:.2f})"
        elif z_score < -2.0:
            interpretation = f"{asset_a} is significantly underperforming {asset_b} (z={z_score:.2f})"
        elif z_score > 1.0:
            interpretation = f"{asset_a} is modestly outperforming {asset_b}"
        elif z_score < -1.0:
            interpretation = f"{asset_a} is modestly underperforming {asset_b}"
        else:
            interpretation = f"{asset_a} and {asset_b} are in line with historical relationship"

        return RelativeValueResult(
            asset_a=asset_a, asset_b=asset_b,
            z_score=z_score, spread_mean=spread_mean,
            spread_std=spread_std, current_spread=current_spread,
            percentile=round(percentile, 1), is_extreme=is_extreme,
            interpretation=interpretation,
        )

    # ── Flight to Safety ─────────────────────────────────────────────────

    def detect_flight_to_safety(self, risk_assets: list[str],
                                safe_assets: list[str]) -> FlightToSafetyResult:
        """Detect flight-to-safety (risk-off) conditions.

        Compares the average performance of risk assets (e.g., equities)
        against safe assets (e.g., gold, bonds). A negative spread with
        risk assets declining and safe assets rising indicates risk-off.

        Args:
            risk_assets: List of asset names classified as risk-on (e.g., ['NIFTY', 'BANKNIFTY'])
            safe_assets: List of asset names classified as safe-haven (e.g., ['GOLD'])

        Returns:
            FlightToSafetyResult with detection status and strength.
        """
        n = self.n_observations
        if n < 5 or not risk_assets or not safe_assets:
            return FlightToSafetyResult(
                is_flight_to_safety=False,
                risk_asset_performance=0.0, safe_asset_performance=0.0,
                spread=0.0, strength="NONE", n_observations=n,
            )

        # Get latest period returns
        risk_returns: list[float] = []
        safe_returns: list[float] = []

        for asset in risk_assets:
            if asset in self._returns and self._returns[asset]:
                risk_returns.append(self._returns[asset][-1])

        for asset in safe_assets:
            if asset in self._returns and self._returns[asset]:
                safe_returns.append(self._returns[asset][-1])

        if not risk_returns or not safe_returns:
            return FlightToSafetyResult(
                is_flight_to_safety=False,
                risk_asset_performance=0.0, safe_asset_performance=0.0,
                spread=0.0, strength="NONE", n_observations=n,
            )

        avg_risk = statistics.mean(risk_returns)
        avg_safe = statistics.mean(safe_returns)
        spread = avg_risk - avg_safe

        # Determine strength
        is_flight = avg_risk < 0 and avg_safe > 0 and spread < 0
        if is_flight:
            if spread < -0.02 and avg_risk < -0.01:
                strength = "STRONG"
            elif spread < -0.01:
                strength = "MODERATE"
            else:
                strength = "WEAK"
        else:
            strength = "NONE"

        return FlightToSafetyResult(
            is_flight_to_safety=is_flight,
            risk_asset_performance=avg_risk,
            safe_asset_performance=avg_safe,
            spread=spread,
            strength=strength,
            n_observations=n,
        )

    # ── Rolling Correlation Stability ────────────────────────────────────

    def rolling_correlation_stability(self, asset_a: str, asset_b: str,
                                      window: int = 20) -> dict[str, Any]:
        """Measure rolling correlation stability between two assets.

        Computes rolling correlations and measures their stability via
        standard deviation of rolling estimates.

        Args:
            asset_a: Name of the first asset.
            asset_b: Name of the second asset.
            window: Rolling window size in periods.

        Returns:
            Dict with stability metrics.
        """
        if asset_a not in self._returns or asset_b not in self._returns:
            return {"status": "error", "message": "Asset data not found"}

        ra = self._returns[asset_a]
        rb = self._returns[asset_b]
        n = min(len(ra), len(rb))

        if n < window + 5:
            return {"status": "error", "message": f"Need at least {window + 5} observations"}

        rolling_corrs: list[float] = []
        for i in range(window, n):
            segment_a = ra[i - window:i]
            segment_b = rb[i - window:i]
            corr = self._pearson(segment_a, segment_b)
            rolling_corrs.append(corr)

        if len(rolling_corrs) < 3:
            return {"status": "insufficient", "message": "Not enough rolling windows"}

        corr_mean = statistics.mean(rolling_corrs)
        corr_std = statistics.stdev(rolling_corrs) if len(rolling_corrs) > 1 else 0.0
        corr_min = min(rolling_corrs)
        corr_max = max(rolling_corrs)
        corr_latest = rolling_corrs[-1] if rolling_corrs else 0.0
        corr_trend = rolling_corrs[-1] - rolling_corrs[0] if len(rolling_corrs) > 1 else 0.0

        # Stability: low std dev = stable correlation
        if corr_std < 0.1:
            stability = "STABLE"
        elif corr_std < 0.25:
            stability = "MODERATE"
        else:
            stability = "VOLATILE"

        return {
            "status": "ok",
            "asset_a": asset_a,
            "asset_b": asset_b,
            "window": window,
            "n_windows": len(rolling_corrs),
            "mean_correlation": round(corr_mean, 4),
            "std_correlation": round(corr_std, 4),
            "min_correlation": round(corr_min, 4),
            "max_correlation": round(corr_max, 4),
            "latest_correlation": round(corr_latest, 4),
            "correlation_trend": round(corr_trend, 4),
            "stability": stability,
        }


# ── Convenience API ──────────────────────────────────────────────────────────


def compute_cross_asset_correlation(
    return_histories: dict[str, list[float]],
) -> dict[str, Any]:
    """Convenience function — compute cross-asset correlation matrix.

    Args:
        return_histories: Dict mapping asset name → list of returns.

    Returns:
        Dict suitable for JSON serialization.
    """
    analyzer = CrossAssetAnalytics()
    for name, returns in return_histories.items():
        analyzer.add_returns(name, returns)
    result = analyzer.correlation_matrix()
    return result.to_dict()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.cross_asset_analytics")
    ap.add_argument("--demo", action="store_true", help="Run with demo data")
    args = ap.parse_args()

    if args.demo:
        import random
        random.seed(42)
        n = 100

        # Generate correlated returns
        nifty = [random.gauss(0.0005, 0.01) for _ in range(n)]
        bnifty = [0.8 * nifty[i] + 0.6 * random.gauss(0.0003, 0.008) for i in range(n)]
        finnifty = [0.7 * nifty[i] + 0.7 * random.gauss(0.0004, 0.007) for i in range(n)]
        gold = [-0.1 * nifty[i] + random.gauss(0.0002, 0.005) for i in range(n)]

        analyzer = CrossAssetAnalytics()
        analyzer.add_returns("NIFTY", nifty)
        analyzer.add_returns("BANKNIFTY", bnifty)
        analyzer.add_returns("FINNIFTY", finnifty)
        analyzer.add_returns("GOLD", gold)

        print(analyzer.correlation_matrix().summary())
        print()
        print(analyzer.relative_value("NIFTY", "BANKNIFTY").summary())
        print()
        fts = analyzer.detect_flight_to_safety(
            risk_assets=["NIFTY", "BANKNIFTY", "FINNIFTY"],
            safe_assets=["GOLD"],
        )
        print(fts.summary())
    else:
        print("Cross Asset Analytics CLI")
        print("Run with --demo for a demonstration")
