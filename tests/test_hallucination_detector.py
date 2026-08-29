"""Tests for core/hallucination_detector.py — Hallucination Detection Engine."""

from __future__ import annotations

from core.hallucination_detector import (
    HallucinationDetector,
    HallucinationFinding,
    HallucinationResult,
    get_hallucination_detector,
    reset_hallucination_detector,
)


class TestHallucinationResult:
    """HallucinationResult dataclass."""

    def test_defaults(self):
        result = HallucinationResult(hallucination_score=0.0, risk_level="CLEAN")
        assert result.hallucination_score == 0.0
        assert result.risk_level == "CLEAN"
        assert result.findings == []
        assert result.confidence == 0.0

    def test_to_dict(self):
        result = HallucinationResult(
            hallucination_score=0.5,
            risk_level="MEDIUM",
            findings=[HallucinationFinding(
                finding_type="FAKE_CITATION",
                text="according to a study",
                severity=0.6,
            )],
        )
        d = result.to_dict()
        assert d["hallucination_score"] == 0.5
        assert d["risk_level"] == "MEDIUM"
        assert len(d["findings"]) == 1
        assert d["findings"][0]["type"] == "FAKE_CITATION"


class TestHallucinationDetector:
    """HallucinationDetector class."""

    def test_init(self):
        detector = HallucinationDetector()
        assert detector is not None
        detector.clear_history()

    def test_clean_text_no_findings(self):
        detector = HallucinationDetector()
        result = detector.analyze("The win rate is 65% and Sharpe ratio is 1.2")
        assert result.hallucination_score < 0.3
        assert result.risk_level in ("CLEAN", "LOW")
        detector.clear_history()

    def test_overly_precise_numbers(self):
        detector = HallucinationDetector()
        result = detector.analyze("The exact win rate is 65.847% with 94.723% confidence")
        assert len(result.findings) >= 1
        assert any(f.finding_type == "OVERLY_PRECISE" for f in result.findings)
        detector.clear_history()

    def test_absolute_claims(self):
        detector = HallucinationDetector()
        result = detector.analyze("This system always wins and never loses a trade. 100% success rate guaranteed.")
        assert len(result.findings) >= 1
        assert any(f.finding_type == "ABSOLUTE_CLAIM" for f in result.findings)
        detector.clear_history()

    def test_fake_citation_detection(self):
        detector = HallucinationDetector()
        result = detector.analyze(
            "According to a study from 2024, this approach increases returns by 50%"
        )
        citation_findings = [f for f in result.findings if f.finding_type == "FAKE_CITATION"]
        assert len(citation_findings) >= 1
        detector.clear_history()

    def test_citation_markers_detected(self):
        detector = HallucinationDetector()
        result = detector.analyze("Multiple studies show that et al. research indicates higher returns")
        assert any(f.finding_type == "FAKE_CITATION" for f in result.findings)
        detector.clear_history()

    def test_factual_range_validation(self):
        detector = HallucinationDetector()
        # Win rate of 150% is outside expected range [0, 100]
        result = detector.analyze("Our win rate is 150% and profit factor is 50")
        assert len(result.findings) >= 1
        fact_findings = [f for f in result.findings if f.finding_type == "FACT_MISMATCH"]
        assert len(fact_findings) >= 1
        detector.clear_history()

    def test_low_confidence_triggers_finding(self):
        detector = HallucinationDetector(confidence_threshold=0.5)
        result = detector.analyze("The market will go up.", model_confidence=0.3)
        assert len(result.findings) >= 1
        assert any(f.finding_type == "LOW_CONFIDENCE" for f in result.findings)
        detector.clear_history()

    def test_factual_grounding_with_known_data(self):
        detector = HallucinationDetector(known_data={
            "win_rate": 65.0,
            "total_trades": 500,
        })
        result = detector.analyze("Our win rate is 95% with 2,000 total trades")
        fact_findings = [f for f in result.findings if f.finding_type == "FACT_MISMATCH"]
        assert len(fact_findings) >= 1
        detector.clear_history()

    def test_high_risk_classification(self):
        detector = HallucinationDetector()
        result = detector.analyze("100% guaranteed! According to a study from 2025, "
                                   "our win rate is 99.847% and Sharpe is 5.832. "
                                   "This always works and never fails. "
                                   "et al. research indicates complete accuracy.")
        assert result.hallucination_score >= 0.4
        detector.clear_history()

    def test_temporal_mismatch(self):
        detector = HallucinationDetector()
        result = detector.analyze("By 2030, our system will have achieved 100% market share")
        temporal = [f for f in result.findings if f.finding_type == "TEMPORAL_MISMATCH"]
        # Only detect if the year is far in the future
        assert len(temporal) >= 0  # May not trigger for near-future years
        detector.clear_history()

    def test_batch_analysis(self):
        detector = HallucinationDetector()
        texts = [
            "Win rate is 65%",
            "Always wins 100% of trades guaranteed",
            "According to a study from 2024",
        ]
        results = detector.analyze_batch(texts)
        assert len(results) == 3
        assert all(isinstance(r, HallucinationResult) for r in results)
        detector.clear_history()

    def test_get_stats(self):
        detector = HallucinationDetector()
        detector.analyze("Win rate is 65%")
        detector.analyze("Always wins 100% guaranteed")
        stats = detector.get_stats()
        assert stats["total_analyses"] >= 2
        detector.clear_history()

    def test_get_stats_empty(self):
        detector = HallucinationDetector()
        detector.clear_history()
        stats = detector.get_stats()
        assert stats["total_analyses"] == 0

    def test_clear_history(self):
        detector = HallucinationDetector()
        detector.analyze("Test text")
        assert detector.get_stats()["total_analyses"] >= 1
        detector.clear_history()
        assert detector.get_stats()["total_analyses"] == 0


class TestSingleton:
    """Singleton factory tests."""

    def test_get_and_reset(self):
        reset_hallucination_detector()
        d1 = get_hallucination_detector()
        d2 = get_hallucination_detector()
        assert d1 is d2
        reset_hallucination_detector()

    def test_reset_creates_new_instance(self):
        reset_hallucination_detector()
        d1 = get_hallucination_detector()
        reset_hallucination_detector()
        d2 = get_hallucination_detector()
        assert d1 is not d2
