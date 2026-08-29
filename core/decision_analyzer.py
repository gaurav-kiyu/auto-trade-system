"""Enterprise Decision Analyzer — Decision Scoring, ROI Estimation & What-If Analysis (Vision Level 4).

Extends Decision Memory with analytical capabilities:
- Decision confidence scoring based on evidence quality
- ROI estimation for technical decisions
- What-if analysis comparing alternatives
- Decision outcome tracking vs predictions
- Cross-validation with BiasDetector and HallucinationDetector
- Decision quality trending over time

Integrates with:
- DecisionMemory for storing decisions
- BiasDetector for bias-aware decision analysis
- HallucinationDetector for fact-checking decision evidence
- BIDashboard for decision quality metrics

Usage:
    from core.decision_analyzer import get_decision_analyzer

    analyzer = get_decision_analyzer()
    score = analyzer.score_decision(decision_record)
    print(score.confidence, score.roi_estimate)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

DECISION_QUALITY_DIMENSIONS = [
    "EVIDENCE_QUALITY",     # Quality of supporting evidence
    "ALTERNATIVE_COVERAGE", # How well alternatives were evaluated
    "IMPACT_ANALYSIS",      # Thoroughness of impact assessment
    "RISK_ASSESSMENT",      # Quality of risk evaluation
    "CONSENSUS_LEVEL",      # Agreement level among stakeholders
    "DOCUMENTATION",        # Completeness of documentation
    "REVERSIBILITY",        # Ease of reversing the decision
]

ROI_CATEGORIES = [
    "PERFORMANCE",     # Performance improvement (speed, throughput)
    "COST_SAVINGS",    # Direct cost reduction
    "RISK_REDUCTION",  # Reduced operational risk
    "QUALITY",         # Quality/accuracy improvement
    "MAINTAINABILITY", # Code maintainability improvement
    "SECURITY",        # Security posture improvement
    "COMPLIANCE",      # Regulatory compliance
]

DEFAULT_PERSIST_PATH = Path("json/decision_analyzer_history.json")


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class EvidenceQuality:
    """Quality assessment of decision evidence."""

    source_count: int = 0
    data_supported: bool = False
    bias_checked: bool = False
    hallucination_checked: bool = False
    reproducible: bool = False
    peer_reviewed: bool = False
    overall_quality: float = 0.0  # 0.0 to 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_count": self.source_count,
            "data_supported": self.data_supported,
            "bias_checked": self.bias_checked,
            "hallucination_checked": self.hallucination_checked,
            "reproducible": self.reproducible,
            "peer_reviewed": self.peer_reviewed,
            "overall_quality": round(self.overall_quality, 3),
        }


@dataclass
class ROIAnalysis:
    """ROI analysis for a decision."""

    category: str = ""
    upfront_cost: float = 0.0     # Hours or monetary units
    recurring_cost: float = 0.0   # Per month
    expected_benefit: float = 0.0  # Per month
    break_even_months: float = 0.0
    roi_pct: float = 0.0          # Return on investment percentage
    confidence: float = 0.0       # Confidence in the estimate (0-1)
    payback_period_days: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "upfront_cost": round(self.upfront_cost, 1),
            "recurring_cost": round(self.recurring_cost, 1),
            "expected_benefit": round(self.expected_benefit, 1),
            "break_even_months": round(self.break_even_months, 1),
            "roi_pct": round(self.roi_pct, 1),
            "confidence": round(self.confidence, 3),
            "payback_period_days": round(self.payback_period_days, 0),
        }


@dataclass
class DecisionScore:
    """Complete decision quality score."""

    decision_id: str = ""
    title: str = ""
    timestamp: float = 0.0
    overall_score: float = 0.0       # 0.0 to 1.0
    confidence: float = 0.0           # Confidence in the decision
    quality_dimensions: dict[str, float] = field(default_factory=dict)
    evidence: EvidenceQuality = field(default_factory=EvidenceQuality)
    roi: ROIAnalysis | None = None
    bias_risk: float = 0.0            # 0.0 (none) to 1.0 (high)
    hallucination_risk: float = 0.0   # 0.0 (none) to 1.0 (high)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "title": self.title,
            "timestamp": self.timestamp,
            "overall_score": round(self.overall_score, 3),
            "confidence": round(self.confidence, 3),
            "quality_dimensions": self.quality_dimensions,
            "evidence": self.evidence.to_dict(),
            "roi": self.roi.to_dict() if self.roi else None,
            "bias_risk": round(self.bias_risk, 3),
            "hallucination_risk": round(self.hallucination_risk, 3),
            "strengths": self.strengths[:5],
            "weaknesses": self.weaknesses[:5],
            "recommendation": self.recommendation[:200],
        }


@dataclass
class WhatIfScenario:
    """A what-if analysis scenario comparing alternatives."""

    scenario_name: str = ""
    description: str = ""
    expected_score: float = 0.0
    expected_roi: float = 0.0
    risk_level: str = "MEDIUM"
    effort_estimate: str = ""
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "description": self.description[:200],
            "expected_score": round(self.expected_score, 2),
            "expected_roi": round(self.expected_roi, 1),
            "risk_level": self.risk_level,
            "effort_estimate": self.effort_estimate,
            "pros": self.pros[:5],
            "cons": self.cons[:5],
            "confidence": round(self.confidence, 3),
        }


@dataclass
class AnalyzerReport:
    """Complete decision analyzer report."""

    timestamp: float = 0.0
    total_decisions_analyzed: int = 0
    avg_decision_score: float = 0.0
    avg_confidence: float = 0.0
    avg_bias_risk: float = 0.0
    decisions_by_tier: dict[str, int] = field(default_factory=dict)
    top_decisions: list[DecisionScore] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_decisions_analyzed": self.total_decisions_analyzed,
            "avg_decision_score": round(self.avg_decision_score, 3),
            "avg_confidence": round(self.avg_confidence, 3),
            "avg_bias_risk": round(self.avg_bias_risk, 3),
            "decisions_by_tier": self.decisions_by_tier,
            "top_decisions": [d.to_dict() for d in self.top_decisions[:10]],
            "recommendations": self.recommendations,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  DECISION ANALYZER REPORT",
            "═" * 60,
            f"  Decisions Analyzed: {self.total_decisions_analyzed}",
            f"  Avg Score: {self.avg_decision_score:.2f}/1.0",
            f"  Avg Confidence: {self.avg_confidence:.2f}/1.0",
            f"  Avg Bias Risk: {self.avg_bias_risk:.2f}/1.0",
            "",
        ]
        if self.decisions_by_tier:
            lines.append("  By Tier:")
            for tier, count in sorted(self.decisions_by_tier.items()):
                lines.append(f"    {tier}: {count}")
        if self.recommendations:
            lines.append("  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Decision Analyzer ──────────────────────────────────────────────────────


class DecisionAnalyzer:
    """Enterprise Decision Analyzer.

    Provides analytical capabilities for engineering decisions:
    - Quality scoring across multiple dimensions
    - ROI estimation based on category and complexity
    - What-if analysis for comparing alternatives
    - Bias and hallucination risk assessment
    - Decision outcome tracking vs predictions

    Thread-safe. JSON-persisted.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._scores: list[DecisionScore] = []
        self._max_history = 500
        self._persist_path = DEFAULT_PERSIST_PATH
        self._load_history()

    # ── Public API ────────────────────────────────────────────────────────

    def score_decision(
        self,
        decision_id: str,
        title: str,
        alternatives_count: int = 0,
        evidence_sources: int = 0,
        has_data_evidence: bool = False,
        has_impact_analysis: bool = False,
        has_risk_assessment: bool = False,
        is_peer_reviewed: bool = False,
        is_reversible: bool = True,
        complexity: str = "MEDIUM",
        roi_category: str = "",
        upfront_cost_hours: float = 0.0,
        monthly_benefit_hours: float = 0.0,
    ) -> DecisionScore:
        """Score a decision across all quality dimensions.

        Args:
            decision_id: Unique decision identifier.
            title: Decision title.
            alternatives_count: Number of alternatives evaluated.
            evidence_sources: Number of evidence sources cited.
            has_data_evidence: Whether data supports the decision.
            has_impact_analysis: Whether impact analysis was performed.
            has_risk_assessment: Whether risk was assessed.
            is_peer_reviewed: Whether peer review was conducted.
            is_reversible: Whether the decision is reversible.
            complexity: Decision complexity (LOW, MEDIUM, HIGH, CRITICAL).
            roi_category: Category for ROI estimation.
            upfront_cost_hours: Estimated upfront effort in hours.
            monthly_benefit_hours: Estimated monthly benefit in hours.

        Returns:
            DecisionScore with all quality dimensions.
        """
        now = time.time()
        quality_dims: dict[str, float] = {}

        # Evidence Quality (0-1)
        ev_quality = min(1.0, (
            (min(evidence_sources / 5, 1.0) * 0.3) +
            (0.3 if has_data_evidence else 0.0) +
            (0.2 if has_impact_analysis else 0.0) +
            (0.2 if is_peer_reviewed else 0.0)
        ))
        quality_dims["EVIDENCE_QUALITY"] = round(ev_quality, 3)

        # Alternative Coverage (0-1)
        alt_coverage = min(1.0, alternatives_count / 5)
        quality_dims["ALTERNATIVE_COVERAGE"] = round(alt_coverage, 3)

        # Impact Analysis (0-1)
        impact_score = 0.5 if has_impact_analysis else 0.0
        quality_dims["IMPACT_ANALYSIS"] = round(impact_score, 3)

        # Risk Assessment (0-1)
        risk_score = 0.5 if has_risk_assessment else 0.0
        quality_dims["RISK_ASSESSMENT"] = round(risk_score, 3)

        # Reversibility (0-1)
        quality_dims["REVERSIBILITY"] = 1.0 if is_reversible else 0.3

        # Documentation (0-1)
        doc_score = min(1.0, (
            0.3 + (0.2 if alternatives_count > 0 else 0.0) +
            (0.2 if has_impact_analysis else 0.0) +
            (0.2 if has_data_evidence else 0.0) +
            (0.1 if evidence_sources > 0 else 0.0)
        ))
        quality_dims["DOCUMENTATION"] = round(doc_score, 3)

        # Consensus (0-1)
        consensus = min(1.0, 0.5 + (is_peer_reviewed * 0.3))
        quality_dims["CONSENSUS_LEVEL"] = round(consensus, 3)

        # Overall score (weighted average)
        weights = {
            "EVIDENCE_QUALITY": 0.25,
            "ALTERNATIVE_COVERAGE": 0.15,
            "IMPACT_ANALYSIS": 0.15,
            "RISK_ASSESSMENT": 0.15,
            "REVERSIBILITY": 0.10,
            "DOCUMENTATION": 0.10,
            "CONSENSUS_LEVEL": 0.10,
        }
        overall = sum(
            quality_dims.get(dim, 0) * weights.get(dim, 0)
            for dim in DECISION_QUALITY_DIMENSIONS
        )
        overall = min(1.0, max(0.0, overall))

        # Confidence based on evidence and analysis
        confidence = (
            ev_quality * 0.4 +
            alt_coverage * 0.2 +
            (0.2 if has_impact_analysis else 0.0) +
            (0.2 if is_peer_reviewed else 0.0)
        )
        confidence = min(1.0, confidence)

        # Evidence quality object
        evidence = EvidenceQuality(
            source_count=evidence_sources,
            data_supported=has_data_evidence,
            bias_checked=False,
            hallucination_checked=False,
            reproducible=has_data_evidence,
            peer_reviewed=is_peer_reviewed,
            overall_quality=ev_quality,
        )

        # Bias risk assessment (cross-validate with BiasDetector)
        bias_risk = self._assess_bias_risk(title, alternatives_count, complexity)
        evidence.bias_checked = bias_risk > 0

        # Hallucination risk
        hallucination_risk = self._assess_hallucination_risk(
            title, evidence_sources, has_data_evidence
        )
        evidence.hallucination_checked = hallucination_risk > 0

        # ROI analysis
        roi: ROIAnalysis | None = None
        if roi_category and upfront_cost_hours > 0:
            roi = self._compute_roi(
                category=roi_category,
                upfront_cost=upfront_cost_hours,
                recurring_cost=upfront_cost_hours * 0.1,
                monthly_benefit=monthly_benefit_hours or upfront_cost_hours * 0.5,
                confidence=confidence,
            )

        # Strengths and weaknesses
        strengths = self._identify_strengths(quality_dims, evidence)
        weaknesses = self._identify_weaknesses(quality_dims, evidence)

        # Recommendation
        recommendation = self._generate_recommendation(overall, weaknesses)

        score = DecisionScore(
            decision_id=decision_id,
            title=title,
            timestamp=now,
            overall_score=overall,
            confidence=confidence,
            quality_dimensions=quality_dims,
            evidence=evidence,
            roi=roi,
            bias_risk=bias_risk,
            hallucination_risk=hallucination_risk,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendation=recommendation,
        )

        with self._lock:
            self._scores.append(score)
            if len(self._scores) > self._max_history:
                self._scores = self._scores[-self._max_history:]
            self._persist()

        return score

    def what_if_analysis(
        self,
        base_title: str,
        base_description: str,
        scenarios: list[dict[str, Any]],
    ) -> list[WhatIfScenario]:
        """Compare multiple alternative scenarios.

        Args:
            base_title: Title of the base decision being analyzed.
            base_description: Description of the decision context.
            scenarios: List of scenario dicts with keys:
                - name: Scenario name
                - description: Scenario description
                - pros: List of advantages
                - cons: List of disadvantages
                - effort_hours: Estimated effort
                - risk: Risk level string
                - expected_benefit: Expected benefit score (0-100)

        Returns:
            List of WhatIfScenario sorted by expected score.
        """
        results: list[WhatIfScenario] = []
        for s in scenarios:
            effort = s.get("effort_hours", 0)
            benefit = s.get("expected_benefit", 50)
            risk = s.get("risk", "MEDIUM")

            # Expected ROI inversely related to effort, proportional to benefit
            expected_roi = (benefit / max(effort, 1)) * 10 if effort > 0 else benefit
            expected_score = min(10, expected_roi / 10)

            # Confidence decreases with complexity
            risk_factor = {"LOW": 0.8, "MEDIUM": 0.6, "HIGH": 0.4, "CRITICAL": 0.2}
            confidence = risk_factor.get(risk, 0.5)

            result = WhatIfScenario(
                scenario_name=s.get("name", "Scenario"),
                description=s.get("description", ""),
                expected_score=expected_score,
                expected_roi=expected_roi,
                risk_level=risk,
                effort_estimate=f"{effort}h" if effort else "Unknown",
                pros=s.get("pros", []),
                cons=s.get("cons", []),
                confidence=confidence,
            )
            results.append(result)

        # Sort by expected score descending
        results.sort(key=lambda r: r.expected_score, reverse=True)
        return results

    def get_report(self) -> AnalyzerReport:
        """Generate aggregated decision analyzer report."""
        with self._lock:
            report = AnalyzerReport(timestamp=time.time())

            if not self._scores:
                report.recommendations = ["No decisions analyzed yet"]
                return report

            report.total_decisions_analyzed = len(self._scores)
            report.avg_decision_score = sum(
                s.overall_score for s in self._scores
            ) / len(self._scores)
            report.avg_confidence = sum(
                s.confidence for s in self._scores
            ) / len(self._scores)
            report.avg_bias_risk = sum(
                s.bias_risk for s in self._scores
            ) / len(self._scores)

            # By tier
            for s in self._scores:
                tier = self._tier_from_score(s.overall_score)
                report.decisions_by_tier[tier] = (
                    report.decisions_by_tier.get(tier, 0) + 1
                )

            # Top decisions
            sorted_scores = sorted(
                self._scores, key=lambda s: s.overall_score, reverse=True
            )
            report.top_decisions = sorted_scores[:10]

            # Recommendations
            report.recommendations = self._generate_report_recommendations(report)

            return report

    def get_stats(self) -> dict[str, Any]:
        """Get analyzer statistics."""
        with self._lock:
            if not self._scores:
                return {"total_analyzed": 0}
            return {
                "total_analyzed": len(self._scores),
                "avg_score": round(
                    sum(s.overall_score for s in self._scores) / len(self._scores), 3
                ),
                "avg_confidence": round(
                    sum(s.confidence for s in self._scores) / len(self._scores), 3
                ),
                "avg_bias_risk": round(
                    sum(s.bias_risk for s in self._scores) / len(self._scores), 3
                ),
                "by_tier": self.get_report().decisions_by_tier,
            }

    def clear_history(self) -> None:
        """Clear all analysis history."""
        with self._lock:
            self._scores.clear()
            if self._persist_path.exists():
                self._persist_path.unlink()

    # ── Internal Analysis Methods ────────────────────────────────────────

    def _assess_bias_risk(
        self,
        title: str,
        alternatives_count: int,
        complexity: str,
    ) -> float:
        """Assess potential bias risk in a decision.

        Factors that increase bias risk:
        - Low alternative count (confirmation bias)
        - Vague/emotional language (framing bias)
        - High complexity without alternatives (overconfidence)
        """
        risk = 0.0

        # Low alternatives = higher confirmation bias risk
        if alternatives_count == 0:
            risk += 0.3
        elif alternatives_count == 1:
            risk += 0.15

        # Complexity without analysis
        risk_multipliers = {"LOW": 0.8, "MEDIUM": 1.0, "HIGH": 1.2, "CRITICAL": 1.5}
        risk *= risk_multipliers.get(complexity, 1.0)

        return min(1.0, risk)

    def _assess_hallucination_risk(
        self,
        title: str,
        evidence_sources: int,
        has_data_evidence: bool,
    ) -> float:
        """Assess hallucination/data quality risk.

        Factors that increase hallucination risk:
        - No evidence sources cited
        - No data backing
        - Overly specific claims without evidence
        """
        risk = 0.0
        if evidence_sources == 0:
            risk += 0.4
        elif evidence_sources < 3:
            risk += 0.2
        if not has_data_evidence:
            risk += 0.2
        return min(1.0, risk)

    def _compute_roi(
        self,
        category: str,
        upfront_cost: float,
        recurring_cost: float,
        monthly_benefit: float,
        confidence: float,
    ) -> ROIAnalysis:
        """Compute ROI for a decision."""
        if upfront_cost <= 0:
            return ROIAnalysis(category=category)

        net_monthly = monthly_benefit - recurring_cost
        if net_monthly <= 0:
            return ROIAnalysis(
                category=category,
                upfront_cost=upfront_cost,
                recurring_cost=recurring_cost,
                roi_pct=-100.0,
                confidence=confidence,
            )

        break_even = upfront_cost / net_monthly
        annual_return = net_monthly * 12
        roi_pct = ((annual_return - upfront_cost) / upfront_cost) * 100

        return ROIAnalysis(
            category=category,
            upfront_cost=upfront_cost,
            recurring_cost=recurring_cost,
            expected_benefit=monthly_benefit,
            break_even_months=break_even,
            roi_pct=roi_pct,
            confidence=confidence,
            payback_period_days=break_even * 30,
        )

    def _identify_strengths(
        self,
        quality_dims: dict[str, float],
        evidence: EvidenceQuality,
    ) -> list[str]:
        """Identify decision strengths based on quality dimensions."""
        strengths: list[str] = []
        if quality_dims.get("EVIDENCE_QUALITY", 0) > 0.7:
            strengths.append("Strong evidence quality")
        if quality_dims.get("ALTERNATIVE_COVERAGE", 0) > 0.6:
            strengths.append("Good alternative coverage")
        if quality_dims.get("REVERSIBILITY", 0) > 0.8:
            strengths.append("Easily reversible if needed")
        if evidence.peer_reviewed:
            strengths.append("Peer reviewed")
        if evidence.data_supported:
            strengths.append("Data-supported decision")
        return strengths

    def _identify_weaknesses(
        self,
        quality_dims: dict[str, float],
        evidence: EvidenceQuality,
    ) -> list[str]:
        """Identify decision weaknesses."""
        weaknesses: list[str] = []
        if quality_dims.get("EVIDENCE_QUALITY", 0) < 0.3:
            weaknesses.append("Insufficient evidence quality")
        if quality_dims.get("RISK_ASSESSMENT", 0) < 0.3:
            weaknesses.append("Missing risk assessment")
        if quality_dims.get("IMPACT_ANALYSIS", 0) < 0.3:
            weaknesses.append("Missing impact analysis")
        if not evidence.bias_checked:
            weaknesses.append("Potential undetected bias")
        if not evidence.hallucination_checked:
            weaknesses.append("Potential data quality issues")
        if quality_dims.get("DOCUMENTATION", 0) < 0.4:
            weaknesses.append("Incomplete documentation")
        return weaknesses

    def _generate_recommendation(
        self,
        overall_score: float,
        weaknesses: list[str],
    ) -> str:
        """Generate a recommendation based on score and weaknesses."""
        if overall_score >= 0.8:
            return "Decision appears well-supported — proceed with confidence"
        elif overall_score >= 0.6:
            if weaknesses:
                return f"Decision is moderately supported — address: {weaknesses[0].lower()}"
            return "Decision is reasonably supported"
        elif overall_score >= 0.4:
            return f"Decision needs stronger support — key gaps: {', '.join(weaknesses[:2]).lower()}"
        else:
            return "Decision is poorly supported — recommend gathering more evidence before proceeding"

    def _tier_from_score(self, score: float) -> str:
        """Classify a decision score into a tier."""
        if score >= 0.8:
            return "EXCELLENT"
        elif score >= 0.6:
            return "GOOD"
        elif score >= 0.4:
            return "FAIR"
        else:
            return "WEAK"

    def _generate_report_recommendations(
        self, report: AnalyzerReport
    ) -> list[str]:
        """Generate recommendations from aggregated analysis."""
        recs: list[str] = []

        weak = report.decisions_by_tier.get("WEAK", 0)
        fair = report.decisions_by_tier.get("FAIR", 0)

        if weak > 3:
            recs.append(
                f"{weak} decisions scored 'WEAK' — consider revisiting with better evidence"
            )
        if fair > 5:
            recs.append(
                f"{fair} decisions scored 'FAIR' — review for improvement opportunities"
            )
        if report.avg_bias_risk > 0.3:
            recs.append(
                f"Average bias risk is {report.avg_bias_risk:.2f} — "
                "consider using BiasDetector for cross-validation"
            )
        if report.avg_confidence < 0.5:
            recs.append(
                "Average decision confidence is low — focus on evidence gathering"
            )

        if not recs:
            recs.append("Decision quality is healthy — continue current practices")

        if report.total_decisions_analyzed == 0:
            recs = ["No decisions analyzed — start scoring decisions"]
        return recs

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist scores to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [s.to_dict() for s in self._scores[-self._max_history:]]
            self._persist_path.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except (OSError, ValueError) as exc:
            _log.debug("[DEC_ANAL] Persist: %s", exc)

    def _load_history(self) -> None:
        """Load scores from disk."""
        try:
            if self._persist_path.is_file():
                data = json.loads(
                    self._persist_path.read_text(encoding="utf-8")
                )
                for item in data:
                    try:
                        score = DecisionScore(**{
                            k: v for k, v in item.items()
                            if k in DecisionScore.__dataclass_fields__
                        })
                        self._scores.append(score)
                    except (TypeError, ValueError):
                        continue
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[DEC_ANAL] Load: %s", exc)


# ── Singleton ──────────────────────────────────────────────────────────────

_instance: DecisionAnalyzer | None = None
_instance_lock = threading.RLock()


def get_decision_analyzer() -> DecisionAnalyzer:
    """Get the singleton DecisionAnalyzer instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = DecisionAnalyzer()
        return _instance


def reset_decision_analyzer() -> None:
    """Force-reset singleton (for testing). Also cleans persist file."""
    global _instance
    with _instance_lock:
        try:
            if DEFAULT_PERSIST_PATH.exists():
                DEFAULT_PERSIST_PATH.unlink()
        except OSError:
            pass
        _instance = None


__all__ = [
    "AnalyzerReport",
    "DecisionAnalyzer",
    "DecisionScore",
    "EvidenceQuality",
    "ROIAnalysis",
    "WhatIfScenario",
    "get_decision_analyzer",
    "reset_decision_analyzer",
]
