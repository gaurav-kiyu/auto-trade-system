"""
IV Surface Calculator — Phase 11 Options Analytics.

Maps implied volatility across strikes (volatility skew/smile) and expiries
(term structure) to produce a 3D IV surface. This is a critical tool for
understanding relative option pricing and identifying mispriced contracts.

Components:
  - Strike Skew: IV variation across moneyness (OTM, ATM, ITM)
  - Term Structure: IV variation across expiries (short-term, medium-term, long-term)
  - Surface Interpolation: Grid of (strike_ratio, dte) → IV
  - Surface Metrics: Skew slope, term slope, surface convexity

Usage:
    from core.iv_surface import IVSurfaceBuilder, IVPoint
    
    builder = IVSurfaceBuilder()
    builder.add_point(strike=25000, dte=7, iv=0.15, option_type="CE")
    builder.add_point(strike=25500, dte=7, iv=0.18, option_type="CE")
    surface = builder.build()
    
    # Get IV for any (strike, dte) via interpolation
    iv_estimate = surface.interpolate(strike=25200, dte=7)
    
    # CLI
    python -m core.iv_surface --spot 23363 --demo
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

_log = logging.getLogger(__name__)


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IVPoint:
    """A single IV observation on the surface."""
    strike: float
    dte: int               # Days to expiry
    iv: float              # Implied volatility (decimal, e.g. 0.15 = 15%)
    option_type: str = ""  # "CE" or "PE"
    moneyness: float = 0.0  # strike / spot ratio (computed from spot)
    weight: float = 1.0     # confidence weight for interpolation


@dataclass
class IVSurfaceResult:
    """Complete IV surface with derived metrics."""
    spot_price: float
    points: list[IVPoint] = field(default_factory=list)
    skew_slope: float = 0.0       # IV change per 10% moneyness (basis points)
    term_slope: float = 0.0       # IV change per 30 DTE (basis points)
    atm_iv: float = 0.0            # ATM implied volatility
    surface_convexity: float = 0.0 # Smile curvature (high = more convex)
    dte_range: tuple[int, int] = (0, 0)
    strike_range: tuple[float, float] = (0.0, 0.0)
    interpolation_points: int = 0
    timestamp: float = 0.0

    def interpolate(
        self,
        strike: float,
        dte: int,
        method: str = "linear",
    ) -> float | None:
        """Interpolate IV for a given strike and DTE.

        Uses inverse-distance weighted interpolation across nearest neighbors.
        Falls back to ATM IV if no nearby points.

        Args:
            strike: Strike price to interpolate.
            dte: Days to expiry.
            method: 'linear' (inverse-distance) or 'nearest' (closest point).

        Returns:
            Estimated IV (decimal), or None if no data available.
        """
        if not self.points:
            return None

        if method == "nearest":
            return self._nearest_neighbor(strike, dte)

        # Inverse-distance weighted interpolation
        distances: list[tuple[float, float]] = []
        for p in self.points:
            # Normalize strike distance by spot, DTE by max DTE
            strike_dist = abs(p.strike - strike) / max(self.spot_price, 1)
            dte_dist = abs(p.dte - dte) / max(self.dte_range[1], 1)
            dist = math.sqrt(strike_dist ** 2 + dte_dist ** 2)
            if dist < 0.001:
                return p.iv  # Exact match
            distances.append((dist, p.iv))

        if not distances:
            return self.atm_iv if self.atm_iv > 0 else None

        # Weight by inverse distance
        total_weight = sum(1.0 / max(d, 0.001) for d, _ in distances)
        weighted_iv = sum((1.0 / max(d, 0.001)) * iv for d, iv in distances)
        return min(2.0, max(0.0, weighted_iv / total_weight))

    def _nearest_neighbor(self, strike: float, dte: int) -> float | None:
        """Find the IV of the nearest observed point."""
        if not self.points:
            return None
        best = min(
            self.points,
            key=lambda p: ((p.strike - strike) / max(self.spot_price, 1)) ** 2
                          + ((p.dte - dte) / max(self.dte_range[1], 1)) ** 2,
        )
        return best.iv

    def get_skew_slice(self, dte: int, tolerance: int = 2) -> list[IVPoint]:
        """Get all IV points for a specific expiry (within tolerance)."""
        return [p for p in self.points if abs(p.dte - dte) <= tolerance]

    def get_term_slice(self, strike: float, tolerance_pct: float = 0.02) -> list[IVPoint]:
        """Get all IV points for a specific strike (within tolerance %)."""
        return [
            p for p in self.points
            if abs(p.strike - strike) / max(self.spot_price, 1) <= tolerance_pct
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "spot_price": self.spot_price,
            "atm_iv": round(self.atm_iv, 4),
            "skew_slope_bp": round(self.skew_slope, 1),
            "term_slope_bp": round(self.term_slope, 1),
            "convexity": round(self.surface_convexity, 4),
            "dte_range": list(self.dte_range),
            "strike_range": [round(s, 2) for s in self.strike_range],
            "points_count": len(self.points),
            "interpolation_points": self.interpolation_points,
            "timestamp": self.timestamp or time.time(),
        }

    def summary(self) -> str:
        return (
            f"IV Surface (spot={self.spot_price:.0f})\n"
            f"  ATM IV: {self.atm_iv*100:.1f}%\n"
            f"  Skew: {self.skew_slope:+.1f} bp/10%% moneyness\n"
            f"  Term: {self.term_slope:+.1f} bp/30DTE\n"
            f"  Convexity: {self.surface_convexity:.4f}\n"
            f"  DTE: {self.dte_range[0]}-{self.dte_range[1]}d | "
            f"Strikes: {self.strike_range[0]:.0f}-{self.strike_range[1]:.0f}\n"
            f"  Points: {len(self.points)} observed, {self.interpolation_points} interpolated"
        )


# ── Surface Builder ──────────────────────────────────────────────────────────

class IVSurfaceBuilder:
    """Builds and analyzes the IV surface from observed option prices.

    Usage:
        builder = IVSurfaceBuilder()
        for point in observed_data:
            builder.add_point(strike, dte, iv, option_type="CE", spot=spot)
        surface = builder.build()
        iv = surface.interpolate(strike=25200, dte=7)
    """

    def __init__(self):
        self._points: list[IVPoint] = []
        self._spot_price: float = 0.0

    def add_point(
        self,
        strike: float,
        dte: int,
        iv: float,
        option_type: str = "",
        spot: float | None = None,
        weight: float = 1.0,
    ) -> None:
        """Add an IV observation point.

        Args:
            strike: Strike price.
            dte: Days to expiry.
            iv: Implied volatility (decimal).
            option_type: 'CE' or 'PE'.
            spot: Current spot price (set once, subsequent calls ignored).
            weight: Confidence weight for interpolation.
        """
        if spot is not None and self._spot_price == 0:
            self._spot_price = spot

        moneyness = strike / max(self._spot_price, 1) if self._spot_price > 0 else 1.0

        self._points.append(IVPoint(
            strike=strike,
            dte=dte,
            iv=min(2.0, max(0.01, iv)),  # Clamp IV to [1%, 200%]
            option_type=option_type,
            moneyness=moneyness,
            weight=weight,
        ))

    def add_from_chain(
        self,
        option_chain: dict[str, dict[float, dict[str, Any]]],
        dte: int,
        spot: float,
    ) -> None:
        """Add multiple IV points from an option chain.

        Args:
            option_chain: {"calls": {strike: {iv, ltp, oi}}, "puts": {strike: ...}}
            dte: Days to expiry for this chain.
            spot: Current spot price.
        """
        self._spot_price = spot

        for opt_type in ("calls", "puts"):
            strikes_data = option_chain.get(opt_type, {})
            ot = "CE" if opt_type == "calls" else "PE"
            for strike_str, data in strikes_data.items():
                strike = float(strike_str)
                iv = float(data.get("iv", 0.0) if isinstance(data, dict) else 0.0)
                oi = int(data.get("oi", 0) if isinstance(data, dict) else 0)
                weight = min(1.0, math.log10(max(oi, 1)) / 5.0)  # Higher OI = higher weight
                if iv > 0:
                    self.add_point(strike, dte, iv, option_type=ot, weight=max(0.1, weight))

    def build(self) -> IVSurfaceResult:
        """Build the IV surface from added points and compute derived metrics.

        Returns:
            IVSurfaceResult with interpolated surface and metrics.
        """
        if not self._points:
            _log.warning("[IV_SURFACE] No points to build surface")
            return IVSurfaceResult(spot_price=self._spot_price, timestamp=time.time())

        self._points.sort(key=lambda p: (p.dte, p.strike))
        spot = self._spot_price or self._points[0].strike

        dte_values = [p.dte for p in self._points]
        strike_values = [p.strike for p in self._points]
        iv_values = [p.iv for p in self._points]

        dte_range = (min(dte_values), max(dte_values))
        strike_range = (min(strike_values), max(strike_values))

        # ATM IV: average IV around moneyness ≈ 1.0 (±2%)
        atm_points = [p for p in self._points if 0.98 <= p.moneyness <= 1.02]
        atm_iv = mean([p.iv for p in atm_points]) if atm_points else mean(iv_values)

        # Skew slope: IV change per 10% moneyness change
        otm_puts = [p for p in self._points if p.moneyness < 0.95 and p.option_type in ("PE", "")]
        otm_calls = [p for p in self._points if p.moneyness > 1.05 and p.option_type in ("CE", "")]
        skew_slope = 0.0
        if otm_puts and otm_calls:
            avg_put_iv = mean([p.iv for p in otm_puts])
            avg_call_iv = mean([p.iv for p in otm_calls])
            # Convert to basis points per 10% moneyness
            skew_slope = (avg_put_iv - avg_call_iv) * 10000 / 0.1  # bp per 10% strike move

        # Term slope: IV change per 30 DTE
        short_term = [p for p in self._points if p.dte <= 15]
        long_term = [p for p in self._points if p.dte > 15]
        term_slope = 0.0
        if short_term and long_term:
            avg_short_iv = mean([p.iv for p in short_term])
            avg_long_iv = mean([p.iv for p in long_term])
            avg_short_dte = mean([p.dte for p in short_term])
            avg_long_dte = mean([p.dte for p in long_term])
            dte_diff = max(avg_long_dte - avg_short_dte, 1)
            term_slope = (avg_long_iv - avg_short_iv) * 10000 / (dte_diff / 30)

        # Surface convexity: how much the smile curves
        far_otm = [p for p in self._points if p.moneyness < 0.90 or p.moneyness > 1.10]
        convexity = 0.0
        if far_otm and atm_points:
            avg_far_iv = mean([p.iv for p in far_otm])
            convexity = avg_far_iv - atm_iv  # Positive = smile, Negative = frown

        return IVSurfaceResult(
            spot_price=spot,
            points=self._points,
            skew_slope=round(skew_slope, 1),
            term_slope=round(term_slope, 1),
            atm_iv=round(atm_iv, 4),
            surface_convexity=round(max(0, convexity), 4),
            dte_range=dte_range,
            strike_range=(round(strike_range[0], 2), round(strike_range[1], 2)),
            interpolation_points=len(self._points),
            timestamp=time.time(),
        )


# ── Quick helpers ────────────────────────────────────────────────────────────

def quick_surface_metrics(
    atm_iv: float,
    otm_put_iv: float,
    otm_call_iv: float,
    short_term_iv: float,
    long_term_iv: float,
) -> dict[str, float]:
    """Quick calculation of key IV surface metrics from summary values."""
    return {
        "skew_slope_bp": round((otm_put_iv - otm_call_iv) * 10000, 1),
        "term_slope_bp": round((long_term_iv - short_term_iv) * 10000, 1),
        "atm_iv_pct": round(atm_iv * 100, 1),
        "put_premium_bp": round((otm_put_iv - atm_iv) * 10000, 1),
        "call_discount_bp": round((atm_iv - otm_call_iv) * 10000, 1),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.iv_surface",
        description="IV Surface Calculator — map implied volatility across strikes and expiries",
    )
    ap.add_argument("--spot", type=float, default=23363.0, help="Current spot price")
    ap.add_argument("--demo", action="store_true", help="Run with demo data")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    if args.demo:
        builder = IVSurfaceBuilder()
        # Generate demo IV surface points across strikes and expiries
        for dte in [1, 7, 14, 30, 60, 90]:
            for moneyness in [0.92, 0.95, 0.98, 1.00, 1.02, 1.05, 1.08]:
                strike = round(args.spot * moneyness)
                # Puts have higher IV OTM, calls have lower IV OTM (skew)
                base_iv = 0.14 + (dte / 365) * 0.02  # Term structure: longer = slightly higher
                if moneyness < 1.0:
                    iv = base_iv + (1.0 - moneyness) * 0.15  # Put skew
                    ot = "PE"
                else:
                    iv = base_iv - (moneyness - 1.0) * 0.05  # Call discount
                    ot = "CE"
                builder.add_point(strike, dte, max(0.05, iv), option_type=ot, spot=args.spot)
        surface = builder.build()
    else:
        _log.error("No data source specified. Use --demo for demonstration.")
        return

    if args.json:
        print(json.dumps(surface.to_dict(), indent=2))
    else:
        print(surface.summary())
        # Show sample interpolations
        print("\n  Sample interpolations:")
        for strike in [args.spot * 0.97, args.spot, args.spot * 1.03]:
            iv = surface.interpolate(strike=strike, dte=14)
            if iv:
                print(f"    Strike {strike:.0f} (14 DTE): {iv*100:.1f}%")


if __name__ == "__main__":
    _cli()


__all__ = [
    "IVPoint",
    "IVSurfaceBuilder",
    "IVSurfaceResult",
    "quick_surface_metrics",
]

