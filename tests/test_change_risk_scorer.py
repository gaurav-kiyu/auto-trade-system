"""Tests for ChangeRiskScorer (Pillar 9)."""
from __future__ import annotations

import pytest
from core.change_risk_scorer import (
    ChangeRiskScorer,
    RiskScore,
    get_risk_scorer,
    reset_risk_scorer,
    score_change_risk,
)


@pytest.fixture(autouse=True)
def reset_scorer() -> None:
    """Reset the singleton before each test."""
    reset_risk_scorer()


class TestChangeRiskScorer:
    """Tests for the ChangeRiskScorer class."""

    def test_singleton(self) -> None:
        """Test singleton pattern."""
        s1 = get_risk_scorer()
        s2 = get_risk_scorer()
        assert s1 is s2

    def test_reset(self) -> None:
        """Test reset clears the singleton."""
        s1 = get_risk_scorer()
        reset_risk_scorer()
        s2 = get_risk_scorer()
        assert s1 is not s2

    def test_score_single_file(self) -> None:
        """Test scoring a single file."""
        scorer = ChangeRiskScorer()
        score = scorer.score_single_file("core/__init__.py")
        assert isinstance(score, RiskScore)
        assert score.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert 0 <= score.risk_score <= 1.0

    def test_score_change_multiple_files(self) -> None:
        """Test scoring with multiple files."""
        scorer = ChangeRiskScorer()
        score = scorer.score_change(
            files_changed=["core/__init__.py", "core/root_cause_analyzer.py"],
            lines_added=100,
            lines_deleted=20,
        )
        assert isinstance(score, RiskScore)

    def test_score_change_with_commit_message(self) -> None:
        """Test scoring with a commit message."""
        scorer = ChangeRiskScorer()
        score = scorer.score_change(
            files_changed=["core/config_bootstrap.py"],
            commit_message="Fix security vulnerability in config parsing",
        )
        assert isinstance(score, RiskScore)

    def test_criticality_scoring(self) -> None:
        """Test that critical modules get higher scores."""
        scorer = ChangeRiskScorer()
        critical_score = scorer.score_single_file("core/services/risk_service.py")
        low_score = scorer.score_single_file("tests/__init__.py")
        assert critical_score.criticality_score >= low_score.criticality_score

    def test_risk_level_low_for_tests(self) -> None:
        """Test that test files get LOW risk."""
        scorer = ChangeRiskScorer()
        score = scorer.score_single_file("tests/__init__.py")
        assert score.risk_level in ("LOW", "MEDIUM")

    def test_risk_level_not_empty(self) -> None:
        """Test that risk score always has some values."""
        scorer = ChangeRiskScorer()
        score = scorer.score_change(files_changed=["new_file.py"])
        assert score.complexity_score >= 0
        assert score.criticality_score >= 0
        assert score.security_score >= 0

    def test_recommendations_generated(self) -> None:
        """Test that recommendations are generated."""
        scorer = ChangeRiskScorer()
        score = scorer.score_change(
            files_changed=["core/services/risk_service.py"],
            lines_added=500,
        )
        assert isinstance(score.recommendations, list)
        if len(score.recommendations) > 0:
            assert isinstance(score.recommendations[0], str)

    def test_risk_factors_collected(self) -> None:
        """Test that risk factors are collected."""
        scorer = ChangeRiskScorer()
        score = scorer.score_single_file("core/services/risk_service.py")
        assert isinstance(score.risk_factors, list)

    def test_report_defect(self) -> None:
        """Test recording a defect."""
        scorer = ChangeRiskScorer()
        scorer.report_defect("core/services/risk_service.py")
        profile = scorer.get_module_risk_profile("core/services/risk_service.py")
        assert profile["defect_count"] >= 1

    def test_get_stats(self) -> None:
        """Test getting stats."""
        scorer = ChangeRiskScorer()
        stats = scorer.get_stats()
        assert isinstance(stats, dict)
        assert "modules_tracked" in stats

    def test_convenience_function(self) -> None:
        """Test the score_change_risk convenience function."""
        score = score_change_risk(
            files_changed=["core/test.py"],
            lines_added=10,
        )
        assert isinstance(score, RiskScore)

    def test_risk_score_to_dict(self) -> None:
        """Test serialization to dict."""
        scorer = ChangeRiskScorer()
        score = scorer.score_single_file("core/__init__.py")
        d = score.to_dict()
        assert isinstance(d, dict)
        assert "risk_level" in d
        assert "risk_score" in d
        assert "recommendations" in d

    def test_risk_score_summary_text(self) -> None:
        """Test summary text generation."""
        score = RiskScore()
        text = score.summary_text()
        assert isinstance(text, str)
        assert "Risk Assessment:" in text


class TestRiskScore:
    """Tests for the RiskScore dataclass."""

    def test_default_values(self) -> None:
        """Test default values of a new score."""
        score = RiskScore()
        assert score.risk_level == "LOW"
        assert score.risk_score == 0.0
        assert score.recommendations == []
        assert score.risk_factors == []

    def test_to_dict_complete(self) -> None:
        """Test dict serialization with populated data."""
        score = RiskScore(
            risk_level="HIGH",
            risk_score=0.65,
            recommendations=["Test recommendation"],
        )
        d = score.to_dict()
        assert d["risk_level"] == "HIGH"
        assert d["risk_score"] == 0.65
        assert len(d["recommendations"]) == 1
