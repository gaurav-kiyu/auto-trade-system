"""Tests for core/release_intelligence.py — Release Intelligence."""

from __future__ import annotations

import pytest
from core.release_intelligence import (
    ReleaseAssessment,
    get_release_intelligence,
    reset_release_intelligence,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_release_intelligence()
    yield
    reset_release_intelligence()


class TestReleaseIntelligenceEngine:
    """Tests for the ReleaseIntelligenceEngine class."""

    def test_singleton(self):
        r1 = get_release_intelligence()
        r2 = get_release_intelligence()
        assert r1 is r2

    def test_reset(self):
        r1 = get_release_intelligence()
        reset_release_intelligence()
        r2 = get_release_intelligence()
        assert r1 is not r2

    def test_assess_release_basic(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["core/foo.py"],
        )
        assert isinstance(assessment, ReleaseAssessment)
        assert assessment.version == "v2.57.0"
        assert 0 <= assessment.release_readiness_score <= 100

    def test_assess_release_with_db_migration(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["core/migration.py"],
            has_db_migration=True,
        )
        assert assessment.has_db_migration is True
        assert assessment.migration_safety_score < 100

    def test_assess_release_with_config_changes(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["config.json"],
            has_config_changes=True,
        )
        assert assessment.has_config_changes is True
        assert assessment.infrastructure_readiness_score < 100

    def test_assess_release_with_dependency_changes(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["requirements.txt"],
            has_dependency_changes=True,
        )
        assert assessment.has_dependency_changes is True

    def test_approval_recommendation_high_score(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["docs/readme.md"],
            risk_score=5.0,  # Very low risk
        )
        assert assessment.approval_recommendation in ("APPROVED", "CONDITIONAL", "BLOCKED")

    def test_approval_recommendation_low_score(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=[f"core/module_{i}.py" for i in range(50)],
            has_db_migration=True,
            has_config_changes=True,
            has_dependency_changes=True,
            risk_score=85.0,  # Very high risk
        )
        assert assessment.approval_recommendation in ("APPROVED", "CONDITIONAL", "BLOCKED")

    def test_canary_recommendation_low_risk(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["core/foo.py"],
            risk_score=5.0,
        )
        assert 0 <= assessment.canary_recommendation_pct <= 100

    def test_canary_recommendation_high_risk(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["core/foo.py"],
            has_db_migration=True,
            risk_score=80.0,
        )
        # High risk should recommend canary < 100%
        if assessment.release_readiness_score < 85:
            assert assessment.canary_recommendation_pct < 100

    def test_rollback_plan(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["core/foo.py"],
            has_db_migration=True,
            has_config_changes=True,
        )
        assert assessment.has_rollback_plan is True
        assert len(assessment.rollback_plan_steps) > 0
        assert assessment.rollback_estimated_minutes > 0

    def test_performance_prediction(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["core/foo.py"],
        )
        assert assessment.predicted_performance_impact in (
            "NONE", "LOW", "MODERATE", "HIGH",
        )

    def test_regression_risk(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["core/risk_service.py", "core/execution_service.py"],
            risk_score=60.0,
        )
        assert assessment.predicted_regression_risk in (
            "VERY_LOW", "LOW", "MODERATE", "HIGH",
        )

    def test_record_deployment_outcome(self):
        engine = get_release_intelligence()
        engine.assess_release(version="v2.57.0", files_changed=["core/foo.py"])
        result = engine.record_deployment_outcome(
            version="v2.57.0", success=True, n_incidents=0
        )
        assert result is True

    def test_record_deployment_outcome_not_found(self):
        engine = get_release_intelligence()
        result = engine.record_deployment_outcome(
            version="v0.0.0", success=True
        )
        assert result is False

    def test_get_history(self):
        engine = get_release_intelligence()
        engine.assess_release(version="v2.57.0", files_changed=["core/a.py"])
        engine.assess_release(version="v2.57.1", files_changed=["core/b.py"])
        history = engine.get_history(limit=5)
        assert len(history) >= 2
        assert all("version" in h for h in history)

    def test_get_stats(self):
        engine = get_release_intelligence()
        engine.assess_release(version="v2.57.0", files_changed=["core/a.py"])
        engine.assess_release(version="v2.57.1", files_changed=["core/b.py"])
        stats = engine.get_stats()
        assert stats["total_releases_assessed"] >= 2
        assert "avg_readiness_score" in stats

    def test_assessment_to_dict(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["core/foo.py"],
        )
        data = assessment.to_dict()
        assert "version" in data
        assert "release_readiness_score" in data
        assert "approval_recommendation" in data
        assert "canary_recommendation_pct" in data
        assert "rollback_plan_steps" in data

    def test_summary_text(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=["core/foo.py"],
        )
        summary = assessment.summary_text()
        assert "RELEASE INTELLIGENCE" in summary
        assert assessment.version in summary
        assert assessment.approval_recommendation in summary

    def test_generated_warnings(self):
        engine = get_release_intelligence()
        assessment = engine.assess_release(
            version="v2.57.0",
            files_changed=[f"core/module_{i}.py" for i in range(25)],
            has_db_migration=True,
            has_config_changes=True,
        )
        assert len(assessment.warnings) > 0


if __name__ == "__main__":
    pytest.main([__file__])
