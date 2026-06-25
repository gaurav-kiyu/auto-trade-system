"""
Recommendation Engine — Trade Recommendations from Analytics Signals.

Generates actionable trade recommendations by combining:
  - Factor model attribution (alpha generation vs factor returns)
  - Cross-asset correlation regime (diversification opportunities)
  - Liquidity assessment (which strikes/expiries are tradeable)
  - Risk attribution (which factors drive portfolio risk)
  - Score-based signal classification

Usage
-----
    from core.recommendation_engine import RecommendationEngine

    engine = RecommendationEngine()
    recs = engine.generate(analytics_data)
    for rec in recs:
        print(rec.summary())
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)


# ── Data structures ─────────────────────────────────────────────────────────


@dataclass
class Recommendation:
    """A single actionable recommendation.

    Attributes:
        recommendation_id: Unique identifier.
        direction: BUY, SELL, HOLD, or REDUCE.
        instrument: Target instrument (e.g., 'NIFTY', 'BANKNIFTY').
        confidence: Confidence level (0-1).
        rationale: Human-readable explanation.
        score: Numeric score (0-100) supporting this recommendation.
        source: Which analytics engine generated this (FACTOR, LIQUIDITY, etc.).
        priority: Priority level (CRITICAL, HIGH, NORMAL, LOW).
        tags: Classification tags for filtering.
        timestamp: When the recommendation was generated.
        details: Additional structured data.
    """
    recommendation_id: str = ""
    direction: str = "HOLD"
    instrument: str = ""
    confidence: float = 0.0
    rationale: str = ""
    score: float = 0.0
    source: str = "ANALYTICS"
    priority: str = "NORMAL"
    tags: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "direction": self.direction,
            "instrument": self.instrument,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "score": round(self.score, 1),
            "source": self.source,
            "priority": self.priority,
            "tags": self.tags,
            "timestamp": self.timestamp,
        }

    def summary(self) -> str:
        return (
            f"[{self.priority}] {self.direction} {self.instrument} "
            f"(confidence: {self.confidence:.1%}, score: {self.score:.0f})\n"
            f"  Source: {self.source}\n"
            f"  Rationale: {self.rationale}"
        )


@dataclass
class RecommendationReport:
    """Complete recommendation report with aggregate metrics."""
    recommendations: list[Recommendation] = field(default_factory=list)
    total_recommendations: int = 0
    high_priority_count: int = 0
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    reduce_count: int = 0
    avg_confidence: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendations": [r.to_dict() for r in self.recommendations],
            "total_recommendations": self.total_recommendations,
            "high_priority_count": self.high_priority_count,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "hold_count": self.hold_count,
            "reduce_count": self.reduce_count,
            "avg_confidence": round(self.avg_confidence, 3),
            "timestamp": self.timestamp,
        }


# ── Recommendation Engine ────────────────────────────────────────────────────


class RecommendationEngine:
    """Generates trade recommendations by combining analytics signals.

    Ingests data from multiple analytics sources and produces ranked,
    actionable recommendations with confidence scores and rationale.
    """

    def __init__(self):
        self._recommendation_id_counter = 0

    def _next_id(self) -> str:
        self._recommendation_id_counter += 1
        return f"REC-{self._recommendation_id_counter:06d}"

    # ── Factor-Based Recommendations ────────────────────────────────────

    def _factor_recommendations(self, analytics: dict[str, Any]) -> list[Recommendation]:
        """Generate recommendations from factor model attribution."""
        recs: list[Recommendation] = []
        factor_data = analytics.get("factor_attribution", {})

        if not factor_data:
            return recs

        alpha = factor_data.get("alpha_contribution", 0.0)
        r_squared = factor_data.get("r_squared", 0.0)

        # Strong positive alpha → BUY signal
        if alpha > 0.001 and r_squared > 0.5:
            recs.append(Recommendation(
                recommendation_id=self._next_id(),
                direction="BUY",
                instrument=analytics.get("instrument", "PORTFOLIO"),
                confidence=min(1.0, alpha * 500 + r_squared * 0.3),
                score=min(100, alpha * 50000 + r_squared * 30),
                source="FACTOR",
                priority="HIGH" if alpha > 0.005 else "NORMAL",
                rationale=f"Strong alpha generation ({alpha:.4f}) with model fit R²={r_squared:.2f}",
                tags=["alpha", "factor_model", "buy_signal"],
                details={"alpha": alpha, "r_squared": r_squared},
            ))

        # Negative alpha → REDUCE / HOLD
        if alpha < -0.001:
            recs.append(Recommendation(
                recommendation_id=self._next_id(),
                direction="REDUCE" if alpha < -0.005 else "HOLD",
                instrument=analytics.get("instrument", "PORTFOLIO"),
                confidence=min(1.0, abs(alpha) * 300),
                score=min(100, abs(alpha) * 30000),
                source="FACTOR",
                priority="HIGH" if alpha < -0.005 else "NORMAL",
                rationale=f"Negative alpha ({alpha:.4f}) — review strategy allocation",
                tags=["alpha", "factor_model", "reduce_signal"],
                details={"alpha": alpha, "r_squared": r_squared},
            ))

        return recs

    # ── Cross-Asset Recommendations ─────────────────────────────────────

    def _cross_asset_recommendations(self, analytics: dict[str, Any]) -> list[Recommendation]:
        """Generate recommendations from cross-asset correlation analysis."""
        recs: list[Recommendation] = []
        cross_asset = analytics.get("cross_asset", {})

        if not cross_asset:
            return recs

        # Check for extreme relative value
        relative_values = cross_asset.get("relative_values", [])
        for rv in relative_values:
            z_score = rv.get("z_score", 0.0)
            if abs(z_score) > 2.0:
                asset_a = rv.get("asset_a", "A")
                asset_b = rv.get("asset_b", "B")
                if z_score > 2.0:
                    direction = "SELL"
                    rationale = f"{asset_a} overvalued vs {asset_b} (z={z_score:.2f})"
                else:
                    direction = "BUY"
                    rationale = f"{asset_a} undervalued vs {asset_b} (z={z_score:.2f})"

                recs.append(Recommendation(
                    recommendation_id=self._next_id(),
                    direction=direction,
                    instrument=asset_a,
                    confidence=min(1.0, abs(z_score) / 4.0),
                    score=min(100, abs(z_score) * 30),
                    source="CROSS_ASSET",
                    priority="HIGH" if abs(z_score) > 3.0 else "NORMAL",
                    rationale=rationale,
                    tags=["relative_value", "cross_asset", "pair_trade"],
                    details=rv,
                ))

        # Flight to safety
        flight = cross_asset.get("flight_to_safety", {})
        if flight.get("is_flight_to_safety"):
            recs.append(Recommendation(
                recommendation_id=self._next_id(),
                direction="REDUCE",
                instrument="RISK_POSITIONS",
                confidence=0.7,
                score=70,
                source="CROSS_ASSET",
                priority="HIGH",
                rationale=f"Flight-to-safety detected: risk assets declining, safe assets rising",
                tags=["flight_to_safety", "risk_off", "reduce_signal"],
                details=flight,
            ))

        return recs

    # ── Liquidity Recommendations ──────────────────────────────────────

    def _liquidity_recommendations(self, analytics: dict[str, Any]) -> list[Recommendation]:
        """Generate recommendations from liquidity assessment."""
        recs: list[Recommendation] = []
        liquidity = analytics.get("liquidity", {})

        if not liquidity:
            return recs

        regime = liquidity.get("regime", "NORMAL")
        composite = liquidity.get("composite_score", 50.0)

        if regime == "ILLIQUID" or regime == "EXTREME":
            recs.append(Recommendation(
                recommendation_id=self._next_id(),
                direction="HOLD",
                instrument=analytics.get("instrument", "MARKET"),
                confidence=min(1.0, (100 - composite) / 100),
                score=composite,
                source="LIQUIDITY",
                priority="HIGH" if regime == "EXTREME" else "NORMAL",
                rationale=f"Low liquidity ({regime}, score={composite:.0f}) — avoid new entries, widen spreads",
                tags=["liquidity", "risk", regime.lower()],
                details=liquidity,
            ))

        if regime == "LIQUID":
            recs.append(Recommendation(
                recommendation_id=self._next_id(),
                direction="BUY",
                instrument=analytics.get("instrument", "MARKET"),
                confidence=0.8,
                score=85,
                source="LIQUIDITY",
                priority="NORMAL",
                rationale=f"High liquidity ({regime}) — favorable entry conditions",
                tags=["liquidity", "buy_signal", regime.lower()],
                details=liquidity,
            ))

        return recs

    # ── Risk Recommendations ──────────────────────────────────────────

    def _risk_recommendations(self, analytics: dict[str, Any]) -> list[Recommendation]:
        """Generate recommendations from risk attribution."""
        recs: list[Recommendation] = []
        risk = analytics.get("risk", {})

        if not risk:
            return recs

        risk_attribution = risk.get("risk_attribution", {})
        if risk_attribution:
            total_risk = risk_attribution.get("total_risk", 0.0)
            specific_risk = risk_attribution.get("specific_risk", 0.0)
            explained_pct = risk_attribution.get("explained_risk_pct", 100.0)

            # Low systematic risk → well-diversified
            if explained_pct < 50.0 and specific_risk > 0:
                recs.append(Recommendation(
                    recommendation_id=self._next_id(),
                    direction="HOLD",
                    instrument="PORTFOLIO",
                    confidence=0.6,
                    score=60,
                    source="RISK",
                    priority="NORMAL",
                    rationale=f"High specific risk ({specific_risk:.4f}) vs systematic — diversify further",
                    tags=["risk", "diversification", "specific_risk"],
                    details=risk_attribution,
                ))

        # Stress test results
        stress = risk.get("stress_test", [])
        for s in stress:
            if s.get("alert"):
                recs.append(Recommendation(
                    recommendation_id=self._next_id(),
                    direction="REDUCE",
                    instrument=s.get("worst_position", "POSITION"),
                    confidence=0.9,
                    score=90,
                    source="RISK",
                    priority="CRITICAL",
                    rationale=f"Stress scenario '{s.get('scenario')}' shows {s.get('pct_of_capital', 0):.1f}% capital at risk",
                    tags=["stress_test", "risk", "critical"],
                    details=s,
                ))

        return recs

    # ── Score-Based Recommendations ────────────────────────────────────

    def _score_recommendations(self, analytics: dict[str, Any]) -> list[Recommendation]:
        """Generate recommendations from signal scores."""
        recs: list[Recommendation] = []
        signals = analytics.get("signals", [])

        for signal in signals:
            score = signal.get("score", 0)
            direction = signal.get("direction", "CALL")
            instrument = signal.get("instrument", "NIFTY")
            confidence = signal.get("confidence", 0.5)

            if score >= 80:
                recs.append(Recommendation(
                    recommendation_id=self._next_id(),
                    direction="BUY",
                    instrument=instrument,
                    confidence=confidence,
                    score=score,
                    source="SIGNAL",
                    priority="HIGH",
                    rationale=f"Strong signal ({score}) for {direction} on {instrument}",
                    tags=["signal", "strong", direction.lower()],
                    details=signal,
                ))
            elif score >= 70:
                recs.append(Recommendation(
                    recommendation_id=self._next_id(),
                    direction="BUY",
                    instrument=instrument,
                    confidence=confidence * 0.8,
                    score=score,
                    source="SIGNAL",
                    priority="NORMAL",
                    rationale=f"Moderate signal ({score}) for {direction} on {instrument}",
                    tags=["signal", "moderate", direction.lower()],
                    details=signal,
                ))

        return recs

    # ── Main Generation Method ─────────────────────────────────────────

    def generate(self, analytics: dict[str, Any]) -> RecommendationReport:
        """Generate all recommendations from available analytics data.

        Args:
            analytics: Dict containing analytics data from various sources.
                Expected keys: factor_attribution, cross_asset, liquidity,
                risk, signals (all optional).

        Returns:
            RecommendationReport with ranked, actionable recommendations.
        """
        all_recs: list[Recommendation] = []
        all_recs.extend(self._factor_recommendations(analytics))
        all_recs.extend(self._cross_asset_recommendations(analytics))
        all_recs.extend(self._liquidity_recommendations(analytics))
        all_recs.extend(self._risk_recommendations(analytics))
        all_recs.extend(self._score_recommendations(analytics))

        # Sort by priority: CRITICAL > HIGH > NORMAL > LOW
        priority_order = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
        all_recs.sort(key=lambda r: (priority_order.get(r.priority, 99), -r.score))

        if not all_recs:
            all_recs.append(Recommendation(
                recommendation_id=self._next_id(),
                direction="HOLD",
                instrument="ALL",
                confidence=1.0,
                score=50,
                source="ANALYTICS",
                priority="NORMAL",
                rationale="No actionable signals from any analytics source",
                tags=["no_signal", "hold"],
            ))

        high_count = sum(1 for r in all_recs if r.priority == "HIGH" or r.priority == "CRITICAL")
        buy_count = sum(1 for r in all_recs if r.direction == "BUY")
        sell_count = sum(1 for r in all_recs if r.direction == "SELL")
        hold_count = sum(1 for r in all_recs if r.direction == "HOLD")
        reduce_count = sum(1 for r in all_recs if r.direction == "REDUCE")
        avg_conf = sum(r.confidence for r in all_recs) / len(all_recs) if all_recs else 0.0

        return RecommendationReport(
            recommendations=all_recs,
            total_recommendations=len(all_recs),
            high_priority_count=high_count,
            buy_count=buy_count,
            sell_count=sell_count,
            hold_count=hold_count,
            reduce_count=reduce_count,
            avg_confidence=avg_conf,
        )


# ── Convenience API ──────────────────────────────────────────────────────────


def generate_recommendations(analytics: dict[str, Any]) -> dict[str, Any]:
    """Convenience function — generate recommendations and return dict.

    Args:
        analytics: Analytics data dict.

    Returns:
        Dict suitable for JSON serialization.
    """
    engine = RecommendationEngine()
    report = engine.generate(analytics)
    return report.to_dict()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.recommendation_engine")
    ap.add_argument("--demo", action="store_true", help="Run with demo data")
    args = ap.parse_args()

    if args.demo:
        engine = RecommendationEngine()

        # Demo analytics data
        analytics = {
            "instrument": "NIFTY",
            "factor_attribution": {
                "alpha_contribution": 0.008,
                "r_squared": 0.75,
                "loadings": {"market": 1.05, "smb": 0.3, "hml": -0.2},
            },
            "cross_asset": {
                "relative_values": [
                    {"asset_a": "NIFTY", "asset_b": "BANKNIFTY", "z_score": 2.5},
                ],
                "flight_to_safety": {
                    "is_flight_to_safety": False,
                    "strength": "NONE",
                },
            },
            "liquidity": {
                "regime": "LIQUID",
                "composite_score": 88.0,
                "spread_score": 92.0,
                "volume_score": 85.0,
            },
            "risk": {
                "risk_attribution": {
                    "total_risk": 0.25,
                    "specific_risk": 0.02,
                    "explained_risk_pct": 85.0,
                },
                "stress_test": [],
            },
            "signals": [
                {"score": 85, "direction": "CALL", "instrument": "NIFTY", "confidence": 0.85},
            ],
        }

        report = engine.generate(analytics)
        print(f"Recommendation Report ({report.total_recommendations} total)")
        print(f"  High Priority: {report.high_priority_count}")
        print(f"  Buy: {report.buy_count} | Sell: {report.sell_count} | Hold: {report.hold_count} | Reduce: {report.reduce_count}")
        print(f"  Avg Confidence: {report.avg_confidence:.1%}")
        print()
        for rec in report.recommendations:
            print(rec.summary())
            print()
    else:
        print("Recommendation Engine CLI")
        print("Run with --demo for a demonstration")


__all__ = [
    "Recommendation",
    "RecommendationEngine",
    "RecommendationReport",
    "generate_recommendations",
]

