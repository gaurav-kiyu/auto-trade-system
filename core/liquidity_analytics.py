"""
Liquidity Analytics — Bid-Ask Spread, Volume & Open Interest Analysis.

Provides institutional-grade liquidity assessment for options and equities:
  - Bid-ask spread analysis (absolute, relative, effective)
  - Volume profile analysis (VWAP, volume-weighted spread)
  - Open Interest (OI) depth analysis
  - Liquidity score computation (composite across multiple metrics)
  - Time-of-day liquidity pattern detection
  - Liquidity regime classification (LIQUID / NORMAL / ILLIQUID / EXTREME)

Usage
-----
    from core.liquidity_analytics import LiquidityAnalytics

    analyzer = LiquidityAnalytics()
    analyzer.add_trade(price=100.0, volume=1000, bid=99.5, ask=100.5)
    score = analyzer.liquidity_score()
    print(f\"Liquidity: {score.regime}\")
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
class SpreadMetrics:
    """Bid-ask spread metrics for a single observation.

    Attributes:
        bid: Bid price.
        ask: Ask price.
        mid: Mid price ((bid + ask) / 2).
        absolute_spread: Absolute spread (ask - bid).
        relative_spread: Relative spread (absolute / mid * 100), in percent.
        effective_spread: Effective spread (|trade_price - mid| * 2 / mid * 100), in percent.
        trade_price: Executed trade price (mid if not provided).
        timestamp: When the observation was recorded.
    """
    bid: float
    ask: float
    mid: float
    absolute_spread: float
    relative_spread: float
    effective_spread: float
    trade_price: float
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "bid": round(self.bid, 4),
            "ask": round(self.ask, 4),
            "mid": round(self.mid, 4),
            "absolute_spread": round(self.absolute_spread, 6),
            "relative_spread": round(self.relative_spread, 4),
            "effective_spread": round(self.effective_spread, 4),
            "trade_price": round(self.trade_price, 4),
            "timestamp": self.timestamp,
        }


@dataclass
class VolumeProfile:
    """Volume profile analysis.

    Attributes:
        vwap: Volume-weighted average price.
        total_volume: Total volume in the period.
        avg_volume: Average volume per observation.
        peak_volume: Peak volume in a single observation.
        volume_concentration: Top-N concentration ratio (e.g., top 10% volume / total).
        n_observations: Number of observations.
    """
    vwap: float
    total_volume: float
    avg_volume: float
    peak_volume: float
    volume_concentration: float
    n_observations: int


@dataclass
class LiquidityScore:
    """Composite liquidity assessment.

    Attributes:
        composite_score: Overall liquidity score (0-100, higher = more liquid).
        regime: Liquidity regime (LIQUID / NORMAL / ILLIQUID / EXTREME).
        spread_score: Spread component score (0-100).
        volume_score: Volume component score (0-100).
        oi_score: Open Interest component score (0-100) if available.
        n_samples: Number of samples used.
        details: Additional diagnostics.
        timestamp: When the assessment was computed.
    """
    composite_score: float
    regime: str
    spread_score: float
    volume_score: float
    oi_score: float
    n_samples: int
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "composite_score": round(self.composite_score, 2),
            "regime": self.regime,
            "spread_score": round(self.spread_score, 2),
            "volume_score": round(self.volume_score, 2),
            "oi_score": round(self.oi_score, 2),
            "n_samples": self.n_samples,
            "details": self.details,
            "timestamp": self.timestamp,
        }

    def summary(self) -> str:
        return (
            f"Liquidity Assessment\n"
            f"  Composite Score: {self.composite_score:.1f}/100\n"
            f"  Regime:          {self.regime}\n"
            f"  Spread Score:    {self.spread_score:.1f}/100\n"
            f"  Volume Score:    {self.volume_score:.1f}/100\n"
            f"  OI Score:        {self.oi_score:.1f}/100\n"
            f"  Samples:         {self.n_samples}\n"
        )


# ── Liquidity Analytics Engine ────────────────────────────────────────────────


class LiquidityAnalytics:
    """Liquidity Analytics Engine.

    Tracks bid-ask spreads, volume, and open interest over time to compute
    composite liquidity scores and detect liquidity regimes.

    Designed for both equities and options liquidity assessment.
    """

    def __init__(self, min_samples: int = 10):
        self._spreads: list[SpreadMetrics] = []
        self._volumes: list[float] = []
        self._open_interest: list[float] = []
        self._prices: list[float] = []
        self._min_samples = max(min_samples, 3)
        self._spread_thresholds = {
            "liquid_max": 0.5,      # < 0.5% relative spread = LIQUID
            "normal_max": 2.0,      # < 2.0% relative spread = NORMAL
        }
        self._volume_thresholds = {
            "liquid_min": 100_000,   # > 100K avg volume = LIQUID (equity)
            "normal_min": 10_000,    # > 10K avg volume = NORMAL
        }

    # ── Data ingestion ──────────────────────────────────────────────────

    def add_trade(self, price: float, volume: float,
                  bid: float | None = None, ask: float | None = None,
                  open_interest: float | None = None,
                  timestamp: str = "") -> None:
        """Add a single trade/quote observation.

        Args:
            price: Executed trade price (or last price).
            volume: Trade volume (number of shares/contracts).
            bid: Bid price (optional — if omitted, spread metrics use synthetic 0.5%).
            ask: Ask price (optional).
            open_interest: Open interest (optional, for options).
            timestamp: Observation timestamp (optional).
        """
        self._prices.append(float(price))
        self._volumes.append(float(volume))

        if open_interest is not None:
            self._open_interest.append(float(open_interest))

        if bid is not None and ask is not None and ask > bid > 0:
            bid_px = float(bid)
            ask_px = float(ask)
            mid = (bid_px + ask_px) / 2.0
            abs_spread = ask_px - bid_px
            rel_spread = (abs_spread / mid) * 100.0 if mid > 0 else 0.0
            eff_spread = abs(price - mid) * 2.0 / mid * 100.0 if mid > 0 else 0.0
        else:
            # Synthetic spread: assume 0.5% relative spread
            mid = float(price)
            abs_spread = mid * 0.005
            rel_spread = 0.5
            eff_spread = 0.5

        self._spreads.append(SpreadMetrics(
            bid=bid or (mid - abs_spread / 2),
            ask=ask or (mid + abs_spread / 2),
            mid=mid,
            absolute_spread=abs_spread,
            relative_spread=rel_spread,
            effective_spread=eff_spread,
            trade_price=float(price),
            timestamp=timestamp,
        ))

    def clear(self) -> None:
        """Clear all observations."""
        self._spreads.clear()
        self._volumes.clear()
        self._open_interest.clear()
        self._prices.clear()

    @property
    def n_samples(self) -> int:
        return len(self._spreads)

    # ── Spread Analysis ─────────────────────────────────────────────────

    def average_spread(self) -> float:
        """Average relative spread in percent."""
        if not self._spreads:
            return 0.0
        return statistics.mean(s.relative_spread for s in self._spreads)

    def spread_percentile(self, percentile: float = 95.0) -> float:
        """Nth percentile of relative spread (e.g., 95th = worst 5% spreads)."""
        if not self._spreads:
            return 0.0
        spreads = sorted(s.relative_spread for s in self._spreads)
        idx = min(int(len(spreads) * percentile / 100.0), len(spreads) - 1)
        return spreads[idx]

    # ── Volume Analysis ─────────────────────────────────────────────────

    def volume_profile(self) -> VolumeProfile:
        """Compute volume profile statistics.

        Returns:
            VolumeProfile with VWAP, average volume, concentration.
        """
        if not self._volumes or not self._prices:
            return VolumeProfile(0.0, 0.0, 0.0, 0.0, 0.0, 0)

        total_vol = sum(self._volumes)
        vwap = sum(p * v for p, v in zip(self._prices, self._volumes)) / total_vol if total_vol > 0 else 0.0
        avg_vol = statistics.mean(self._volumes)
        peak_vol = max(self._volumes)

        # Volume concentration: how much does top 10% of observations contribute?
        sorted_vols = sorted(self._volumes, reverse=True)
        top_n = max(1, len(sorted_vols) // 10)
        top_vol = sum(sorted_vols[:top_n])
        concentration = top_vol / total_vol if total_vol > 0 else 0.0

        return VolumeProfile(
            vwap=round(vwap, 4),
            total_volume=total_vol,
            avg_volume=avg_vol,
            peak_volume=peak_vol,
            volume_concentration=round(concentration, 4),
            n_observations=len(self._volumes),
        )

    # ── Open Interest Analysis ──────────────────────────────────────────

    def oi_analysis(self) -> dict[str, Any]:
        """Analyze open interest trends.

        Returns:
            Dict with OI statistics.
        """
        if len(self._open_interest) < 3:
            return {
                "status": "insufficient",
                "avg_oi": 0.0,
                "oi_trend": 0.0,
                "oi_growth_rate": 0.0,
            }

        avg_oi = statistics.mean(self._open_interest)
        oi_latest = self._open_interest[-1]
        oi_first = self._open_interest[0]
        oi_trend = oi_latest - oi_first
        oi_growth_rate = oi_trend / max(abs(oi_first), 1.0) * 100.0

        return {
            "status": "ok",
            "avg_oi": avg_oi,
            "latest_oi": oi_latest,
            "first_oi": oi_first,
            "oi_trend": oi_trend,
            "oi_growth_rate_pct": round(oi_growth_rate, 2),
            "n_samples": len(self._open_interest),
        }

    # ── Composite Liquidity Score ───────────────────────────────────────

    def liquidity_score(self) -> LiquidityScore:
        """Compute composite liquidity assessment.

        Returns:
            LiquidityScore with 0-100 score and regime classification.
        """
        if self.n_samples < self._min_samples:
            return LiquidityScore(
                composite_score=0.0,
                regime="INSUFFICIENT_DATA",
                spread_score=0.0, volume_score=0.0, oi_score=0.0,
                n_samples=self.n_samples,
                details={"min_required": self._min_samples},
            )

        # Spread score: 0-100, lower spread = higher score
        avg_rel_spread = self.average_spread()
        if avg_rel_spread <= 0.1:
            spread_score = 100.0
        elif avg_rel_spread <= 0.5:
            spread_score = 90.0 + (0.5 - avg_rel_spread) / 0.4 * 10.0
        elif avg_rel_spread <= 1.0:
            spread_score = 70.0 + (1.0 - avg_rel_spread) / 0.5 * 20.0
        elif avg_rel_spread <= 2.0:
            spread_score = 50.0 + (2.0 - avg_rel_spread) / 1.0 * 20.0
        elif avg_rel_spread <= 5.0:
            spread_score = 20.0 + (5.0 - avg_rel_spread) / 3.0 * 30.0
        else:
            spread_score = max(0.0, 20.0 - (avg_rel_spread - 5.0) / 5.0 * 20.0)

        # Volume score: 0-100, higher volume = higher score
        vp = self.volume_profile()
        avg_vol = vp.avg_volume
        if avg_vol >= 1_000_000:
            volume_score = 100.0
        elif avg_vol >= 500_000:
            volume_score = 95.0 + (avg_vol - 500_000) / 500_000 * 5.0
        elif avg_vol >= 100_000:
            volume_score = 80.0 + (avg_vol - 100_000) / 400_000 * 15.0
        elif avg_vol >= 50_000:
            volume_score = 60.0 + (avg_vol - 50_000) / 50_000 * 20.0
        elif avg_vol >= 10_000:
            volume_score = 40.0 + (avg_vol - 10_000) / 40_000 * 20.0
        elif avg_vol >= 1_000:
            volume_score = 20.0 + (avg_vol - 1_000) / 9_000 * 20.0
        else:
            volume_score = max(0.0, avg_vol / 1_000 * 20.0)

        # OI score: 0-100, higher OI growth = more liquid
        oi_data = self.oi_analysis()
        oi_score = 50.0  # neutral default
        if oi_data["status"] == "ok":
            oi_growth = oi_data["oi_growth_rate_pct"]
            avg_oi = oi_data["avg_oi"]
            if avg_oi >= 1_000_000:
                oi_score = 90.0
            elif avg_oi >= 100_000:
                oi_score = 70.0
            elif avg_oi >= 10_000:
                oi_score = 50.0
            else:
                oi_score = 30.0

            # OI growth bonus
            if oi_growth > 20:
                oi_score = min(100.0, oi_score + 10.0)
            elif oi_growth < -20:
                oi_score = max(0.0, oi_score - 10.0)

        # Composite score (weighted average)
        weights = {"spread": 0.5, "volume": 0.3, "oi": 0.2}
        composite = (
            spread_score * weights["spread"]
            + volume_score * weights["volume"]
            + oi_score * weights["oi"]
        )

        # Regime classification
        if composite >= 85:
            regime = "LIQUID"
        elif composite >= 60:
            regime = "NORMAL"
        elif composite >= 30:
            regime = "ILLIQUID"
        else:
            regime = "EXTREME"

        return LiquidityScore(
            composite_score=round(composite, 2),
            regime=regime,
            spread_score=round(spread_score, 2),
            volume_score=round(volume_score, 2),
            oi_score=round(oi_score, 2),
            n_samples=self.n_samples,
            details={
                "avg_relative_spread": round(avg_rel_spread, 4),
                "avg_volume": round(avg_vol, 2),
                "volume_concentration": vp.volume_concentration,
                "oi_growth_rate": oi_data.get("oi_growth_rate_pct", 0.0),
            },
        )

    # ── Time-of-Day Pattern Detection ───────────────────────────────────

    def time_of_day_pattern(self) -> list[dict[str, Any]]:
        """Detect liquidity patterns by time of day.

        Groups observations by hour and computes average spread and volume
        for each hour. Useful for identifying optimal trading windows.

        Returns:
            List of hourly liquidity profiles.
        """
        from datetime import datetime as _dt

        hourly: dict[int, list[SpreadMetrics]] = {}
        hourly_vol: dict[int, list[float]] = {}

        for i, s in enumerate(self._spreads):
            if s.timestamp and len(s.timestamp) >= 13:
                try:
                    ts = _dt.fromisoformat(s.timestamp)
                    hour = ts.hour
                    if hour not in hourly:
                        hourly[hour] = []
                        hourly_vol[hour] = []
                    hourly[hour].append(s)
                    if i < len(self._volumes):
                        hourly_vol[hour].append(self._volumes[i])
                except (ValueError, TypeError, IndexError):
                    pass

        if not hourly:
            return []

        results: list[dict[str, Any]] = []
        for hour in sorted(hourly.keys()):
            spreads = hourly[hour]
            vols = hourly_vol.get(hour, [])
            if not spreads:
                continue

            avg_spread = statistics.mean(s.relative_spread for s in spreads)
            avg_vol = statistics.mean(vols) if vols else 0.0

            # Score this hour
            if avg_spread <= 0.5 and avg_vol >= 100_000:
                quality = "HIGH"
            elif avg_spread <= 2.0 and avg_vol >= 10_000:
                quality = "MODERATE"
            else:
                quality = "LOW"

            results.append({
                "hour": hour,
                "avg_relative_spread": round(avg_spread, 4),
                "avg_volume": round(avg_vol, 2),
                "n_samples": len(spreads),
                "quality": quality,
            })

        return results


# ── Convenience API ──────────────────────────────────────────────────────────


def assess_liquidity(
    prices: list[float],
    volumes: list[float],
    bids: list[float] | None = None,
    asks: list[float] | None = None,
    open_interests: list[float] | None = None,
) -> dict[str, Any]:
    """Convenience function — compute liquidity assessment.

    Args:
        prices: List of trade prices.
        volumes: List of trade volumes (same length as prices).
        bids: Optional list of bid prices.
        asks: Optional list of ask prices.
        open_interests: Optional list of open interest values.

    Returns:
        Dict suitable for JSON serialization.
    """
    analyzer = LiquidityAnalytics()
    n = len(prices)
    for i in range(n):
        bid = bids[i] if bids and i < len(bids) else None
        ask = asks[i] if asks and i < len(asks) else None
        oi = open_interests[i] if open_interests and i < len(open_interests) else None
        analyzer.add_trade(prices[i], volumes[i], bid, ask, oi)
    score = analyzer.liquidity_score()
    vp = analyzer.volume_profile()
    return {
        "score": score.to_dict(),
        "volume_profile": {
            "vwap": vp.vwap,
            "total_volume": vp.total_volume,
            "avg_volume": vp.avg_volume,
        },
        "patterns": analyzer.time_of_day_pattern(),
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.liquidity_analytics")
    ap.add_argument("--demo", action="store_true", help="Run with demo data")
    args = ap.parse_args()

    if args.demo:
        import random
        from datetime import datetime as _dt
        random.seed(42)
        n = 100

        # Generate liquid demo data (tight spreads, high volume)
        base_price = 150.0
        analyzer = LiquidityAnalytics()
        for i in range(n):
            price = base_price + random.gauss(0, 0.5)
            volume = random.randint(10_000, 500_000)
            bid = price * (1 - random.uniform(0.001, 0.01))
            ask = price * (1 + random.uniform(0.001, 0.01))
            oi = random.randint(50_000, 2_000_000)

            ts = _dt(2026, 6, 21, 9 + i // 12, (i * 5) % 60, 0).isoformat()
            analyzer.add_trade(price, volume, bid, ask, oi, ts)

        score = analyzer.liquidity_score()
        print(score.summary())
        print()
        print("Hourly Patterns:")
        for pattern in analyzer.time_of_day_pattern():
            print(f"  Hour {pattern['hour']:02d}: spread={pattern['avg_relative_spread']:.2f}% "
                  f"vol={pattern['avg_volume']:.0f} [{pattern['quality']}]")
    else:
        print("Liquidity Analytics CLI")
        print("Run with --demo for a demonstration")
