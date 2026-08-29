"""Tests for core/decision_analyzer.py — Enterprise Decision Analyzer."""

from __future__ import annotations

from core.decision_analyzer import (
    DECISION_QUALITY_DIMENSIONS,
    AnalyzerReport,
    DecisionScore,
    EvidenceQuality,
    ROIAnalysis,
    WhatIfScenario,
    get_decision_analyzer,
    reset_decision_analyzer,
)

# ── Data Model Tests ────────────────────────────────────────────────────────


class TestEvidenceQuality:
    def test_defaults(self):
        eq = EvidenceQuality()
        assert eq.source_count == 0
        assert eq.overall_quality == 0.0
        assert eq.bias_checked is False

    def test_to_dict(self):
        eq = EvidenceQuality(
            source_count=5,
            data_supported=True,
            peer_reviewed=True,
            overall_quality=0.85,
        )
        d = eq.to_dict()
        assert d["source_count"] == 5
        assert d["overall_quality"] == 0.85
        assert d["data_supported"] is True


class TestROIAnalysis:
    def test_defaults(self):
        roi = ROIAnalysis(category="PERFORMANCE")
        assert roi.category == "PERFORMANCE"
        assert roi.roi_pct == 0.0

    def test_to_dict(self):
        roi = ROIAnalysis(
            category="COST_SAVINGS",
            upfront_cost=100.0,
            recurring_cost=10.0,
            expected_benefit=50.0,
            break_even_months=2.5,
            roi_pct=200.0,
            confidence=0.8,
        )
        d = roi.to_dict()
        assert d["roi_pct"] == 200.0
        assert d["break_even_months"] == 2.5


class TestDecisionScore:
    def test_defaults(self):
        s = DecisionScore(decision_id="DEC-001", title="Test decision", timestamp=100.0)
        assert s.overall_score == 0.0
        assert s.strengths == []

    def test_to_dict(self):
        s = DecisionScore(
            decision_id="DEC-002",
            title="Important decision",
            timestamp=200.0,
            overall_score=0.75,
            confidence=0.8,
            quality_dimensions={"EVIDENCE_QUALITY": 0.8, "ALTERNATIVE_COVERAGE": 0.6},
            evidence=EvidenceQuality(source_count=3, overall_quality=0.8),
        )
        d = s.to_dict()
        assert d["overall_score"] == 0.75
        assert d["evidence"]["source_count"] == 3


class TestAnalyzerReport:
    def test_defaults(self):
        r = AnalyzerReport(timestamp=100.0)
        assert r.total_decisions_analyzed == 0
        assert r.avg_decision_score == 0.0

    def test_summary_text(self):
        r = AnalyzerReport(
            timestamp=100.0,
            total_decisions_analyzed=10,
            avg_decision_score=0.65,
            decisions_by_tier={"GOOD": 5, "FAIR": 5},
        )
        text = r.summary_text()
        assert "DECISION ANALYZER REPORT" in text
        assert "10" in text
        assert "GOOD" in text


class TestWhatIfScenario:
    def test_defaults(self):
        s = WhatIfScenario(scenario_name="Test")
        assert s.expected_score == 0.0
        assert s.risk_level == "MEDIUM"

    def test_to_dict(self):
        s = WhatIfScenario(
            scenario_name="Using Redis Cache",
            description="Add Redis for session cache",
            expected_score=8.5,
            expected_roi=150.0,
            risk_level="LOW",
            pros=["Fast", "Proven"],
            cons=["Complex", "Cost"],
        )
        d = s.to_dict()
        assert d["expected_score"] == 8.5
        assert len(d["pros"]) == 2


# ── Constants Tests ─────────────────────────────────────────────────────────


class TestConstants:
    def test_quality_dimensions(self):
        assert "EVIDENCE_QUALITY" in DECISION_QUALITY_DIMENSIONS
        assert "REVERSIBILITY" in DECISION_QUALITY_DIMENSIONS
        assert len(DECISION_QUALITY_DIMENSIONS) == 7


# ── DecisionAnalyzer Tests ──────────────────────────────────────────────────


class TestDecisionAnalyzerInit:
    def test_init(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        assert analyzer is not None
        assert analyzer._scores == []

    def test_singleton(self):
        reset_decision_analyzer()
        a1 = get_decision_analyzer()
        a2 = get_decision_analyzer()
        assert a1 is a2

    def test_reset(self):
        reset_decision_analyzer()
        a1 = get_decision_analyzer()
        reset_decision_analyzer()
        a2 = get_decision_analyzer()
        assert a1 is not a2


class TestDecisionAnalyzerScore:
    def test_basic_scoring(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        score = analyzer.score_decision(
            decision_id="DEC-001",
            title="Use PostgreSQL",
            alternatives_count=3,
            evidence_sources=5,
            has_data_evidence=True,
            has_impact_analysis=True,
            is_peer_reviewed=True,
        )
        assert score.decision_id == "DEC-001"
        assert score.overall_score > 0.5
        assert score.confidence > 0.5

    def test_poor_scoring(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        score = analyzer.score_decision(
            decision_id="DEC-002",
            title="Quick decision",
            alternatives_count=0,
            evidence_sources=0,
        )
        assert score.overall_score < 0.5
        assert len(score.weaknesses) > 0

    def test_high_quality_scoring(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        score = analyzer.score_decision(
            decision_id="DEC-003",
            title="Well-researched decision",
            alternatives_count=5,
            evidence_sources=10,
            has_data_evidence=True,
            has_impact_analysis=True,
            has_risk_assessment=True,
            is_peer_reviewed=True,
            is_reversible=True,
        )
        assert score.overall_score > 0.7
        assert score.confidence > 0.7
        assert len(score.strengths) >= 2

    def test_scoring_with_roi(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        score = analyzer.score_decision(
            decision_id="DEC-004",
            title="Optimize query performance",
            alternatives_count=2,
            evidence_sources=3,
            has_data_evidence=True,
            complexity="MEDIUM",
            roi_category="PERFORMANCE",
            upfront_cost_hours=40,
            monthly_benefit_hours=80,
        )
        assert score.roi is not None
        assert score.roi.roi_pct > 0
        assert score.roi.break_even_months > 0

    def test_bias_risk_assessed(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        # Decision with no alternatives → higher bias risk
        score = analyzer.score_decision(
            decision_id="DEC-005",
            title="No alternatives considered",
            alternatives_count=0,
            evidence_sources=1,
        )
        assert score.bias_risk > 0.1
        assert score.evidence.bias_checked is True

    def test_hallucination_risk_assessed(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        # Decision with no evidence → higher hallucination risk
        score = analyzer.score_decision(
            decision_id="DEC-006",
            title="No evidence",
            alternatives_count=0,
            evidence_sources=0,
        )
        assert score.hallucination_risk > 0.3
        assert score.evidence.hallucination_checked is True


class TestDecisionAnalyzerWhatIf:
    def test_what_if_empty(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        scenarios = analyzer.what_if_analysis(
            base_title="Choose database",
            base_description="Which DB to use?",
            scenarios=[
                {
                    "name": "PostgreSQL",
                    "description": "Use PostgreSQL",
                    "pros": ["ACID", "Mature"],
                    "cons": ["Heavy"],
                    "effort_hours": 40,
                    "risk": "LOW",
                    "expected_benefit": 80,
                },
                {
                    "name": "SQLite",
                    "description": "Use SQLite",
                    "pros": ["Lightweight"],
                    "cons": ["No concurrency"],
                    "effort_hours": 10,
                    "risk": "LOW",
                    "expected_benefit": 30,
                },
            ],
        )
        assert len(scenarios) == 2
        # PostgreSQL should score higher (80 benefit / 40 effort = 2 vs 30/10 = 3... wait)
        # 80/40*10 = 20, 30/10*10 = 30 → SQLite should win by ROI
        # But expected_score = min(10, roi/10), so 20/10=2 and 30/10=3
        # Higher score = better for the scenario
        # SQLite: (30/10)*10 = 30 ROI → score 3.0, PostgreSQL: (80/40)*10 = 20 ROI → score 2.0
        # Higher expected_roi = better ranked
        assert scenarios[0].expected_roi >= scenarios[1].expected_roi

    def test_what_if_single_scenario(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        scenarios = analyzer.what_if_analysis(
            base_title="Migration",
            base_description="Migrate to async",
            scenarios=[
                {
                    "name": "Async rewrite",
                    "description": "Full async rewrite",
                    "pros": ["Performance"],
                    "cons": ["Complex"],
                    "effort_hours": 200,
                    "risk": "HIGH",
                    "expected_benefit": 90,
                },
            ],
        )
        assert len(scenarios) == 1
        assert scenarios[0].expected_roi > 0


class TestDecisionAnalyzerReport:
    def test_empty_report(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        report = analyzer.get_report()
        assert report.total_decisions_analyzed == 0
        assert len(report.recommendations) >= 1
        assert "No decisions" in report.recommendations[0]

    def test_report_after_scoring(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        analyzer.score_decision("DEC-001", "Good decision", alternatives_count=3, evidence_sources=5, has_data_evidence=True)
        analyzer.score_decision("DEC-002", "Poor decision", alternatives_count=0, evidence_sources=0)
        report = analyzer.get_report()
        assert report.total_decisions_analyzed == 2
        assert report.avg_decision_score > 0
        assert report.avg_bias_risk > 0
        assert len(report.decisions_by_tier) > 0

    def test_avg_confidence(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        analyzer.score_decision("DEC-001", "Test", alternatives_count=3, evidence_sources=5)
        report = analyzer.get_report()
        assert report.avg_confidence > 0


class TestDecisionAnalyzerStats:
    def test_empty_stats(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        stats = analyzer.get_stats()
        assert stats["total_analyzed"] == 0

    def test_stats_after_scoring(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        analyzer.score_decision("DEC-001", "Test decision", alternatives_count=2, evidence_sources=3)
        stats = analyzer.get_stats()
        assert stats["total_analyzed"] == 1
        assert "avg_score" in stats
        assert "avg_confidence" in stats


class TestDecisionAnalyzerClearHistory:
    def test_clear_history(self):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        analyzer.score_decision("DEC-001", "Test", alternatives_count=2, evidence_sources=3)
        assert len(analyzer._scores) == 1
        analyzer.clear_history()
        assert len(analyzer._scores) == 0

    def test_clear_history_removes_file(self, tmp_path):
        reset_decision_analyzer()
        analyzer = get_decision_analyzer()
        analyzer._persist_path = tmp_path / "da_test.json"
        analyzer.score_decision("DEC-001", "Test", alternatives_count=2, evidence_sources=3)
        assert analyzer._persist_path.exists()
        analyzer.clear_history()
        assert not analyzer._persist_path.exists()
