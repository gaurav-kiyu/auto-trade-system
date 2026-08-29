"""Tests for core/enterprise_portfolio_intelligence.py — Portfolio Intelligence."""

from __future__ import annotations

import pytest
from core.enterprise_portfolio_intelligence import (
    Epic,
    Feature,
    PortfolioReport,
    get_portfolio_intelligence,
    reset_portfolio_intelligence,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_portfolio_intelligence()
    yield
    reset_portfolio_intelligence()


class TestPortfolioIntelligenceEngine:
    """Tests for the PortfolioIntelligenceEngine class."""

    def test_singleton(self):
        p1 = get_portfolio_intelligence()
        p2 = get_portfolio_intelligence()
        assert p1 is p2

    def test_reset(self):
        p1 = get_portfolio_intelligence()
        reset_portfolio_intelligence()
        p2 = get_portfolio_intelligence()
        assert p1 is not p2

    def test_register_epic(self):
        engine = get_portfolio_intelligence()
        epic = engine.register_epic(
            epic_id="EPIC-001",
            title="Risk Management Overhaul",
            affected_modules=["core/risk_service.py", "core/execution_service.py"],
        )
        assert isinstance(epic, Epic)
        assert epic.epic_id == "EPIC-001"
        assert epic.title == "Risk Management Overhaul"
        assert "core/risk_service.py" in epic.affected_modules

    def test_register_feature(self):
        engine = get_portfolio_intelligence()
        engine.register_epic(epic_id="EPIC-001", title="Test Epic")
        feature = engine.register_feature(
            epic_id="EPIC-001",
            feature_id="FTR-001",
            title="Circuit Breaker Improvement",
            business_value_score=8.0,
            technical_complexity=6.0,
        )
        assert isinstance(feature, Feature)
        assert feature.feature_id == "FTR-001"
        assert feature.epic_id == "EPIC-001"

    def test_register_feature_without_epic(self):
        engine = get_portfolio_intelligence()
        feature = engine.register_feature(
            epic_id="EPIC-MISSING",
            feature_id="FTR-001",
            title="Orphan Feature",
        )
        assert feature is None

    def test_update_epic_status(self):
        engine = get_portfolio_intelligence()
        engine.register_epic(epic_id="EPIC-001", title="Test")
        result = engine.update_epic_status("EPIC-001", "COMPLETED")
        assert result is True

    def test_update_epic_status_invalid(self):
        engine = get_portfolio_intelligence()
        engine.register_epic(epic_id="EPIC-001", title="Test")
        result = engine.update_epic_status("EPIC-001", "INVALID_STATUS")
        assert result is False

    def test_update_feature_status(self):
        engine = get_portfolio_intelligence()
        engine.register_epic(epic_id="EPIC-001", title="Test")
        engine.register_feature(epic_id="EPIC-001", feature_id="FTR-001", title="Test Feat")
        result = engine.update_feature_status("FTR-001", "COMPLETED")
        assert result is True

    def test_update_feature_status_invalid(self):
        engine = get_portfolio_intelligence()
        engine.register_epic(epic_id="EPIC-001", title="Test")
        engine.register_feature(epic_id="EPIC-001", feature_id="FTR-001", title="Test Feat")
        result = engine.update_feature_status("FTR-001", "INVALID")
        assert result is False

    def test_report_feature_effort(self):
        engine = get_portfolio_intelligence()
        engine.register_epic(epic_id="EPIC-001", title="Test")
        engine.register_feature(epic_id="EPIC-001", feature_id="FTR-001", title="Test Feat")
        result = engine.report_feature_effort("FTR-001", actual_hours=40.0)
        assert result is True
        result = engine.report_feature_effort("FTR-NOT", actual_hours=40.0)
        assert result is False

    def test_register_bug(self):
        engine = get_portfolio_intelligence()
        bug = engine.register_bug(
            bug_id="BUG-001",
            module="core/risk_service.py",
            title="Incorrect VaR calculation",
            severity="HIGH",
        )
        assert bug.bug_id == "BUG-001"
        assert bug.module == "core/risk_service.py"

    def test_resolve_bug(self):
        engine = get_portfolio_intelligence()
        engine.register_bug(bug_id="BUG-001", module="core/foo.py", title="Test bug")
        result = engine.resolve_bug("BUG-001")
        assert result is True

    def test_register_goal(self):
        engine = get_portfolio_intelligence()
        goal = engine.register_goal(
            goal_id="GOAL-001",
            title="Achieve 90% test coverage",
            target_value=90.0,
            unit="pct",
            category="QUALITY",
        )
        assert goal.goal_id == "GOAL-001"
        assert goal.target_value == 90.0

    def test_update_goal_progress(self):
        engine = get_portfolio_intelligence()
        engine.register_goal(goal_id="GOAL-001", title="Test goal", target_value=100.0)
        result = engine.update_goal_progress("GOAL-001", current_value=75.0)
        assert result is True
        goal = engine._goals.get("GOAL-001")
        assert goal is not None
        assert goal.current_value == 75.0
        assert goal.progress_pct == 75.0

    def test_get_portfolio_report(self):
        engine = get_portfolio_intelligence()
        # Add epics and features
        engine.register_epic(epic_id="EPIC-001", title="Epic 1")
        engine.register_feature(epic_id="EPIC-001", feature_id="FTR-001", title="F1")
        engine.register_feature(epic_id="EPIC-001", feature_id="FTR-002", title="F2")
        engine.update_feature_status("FTR-001", "COMPLETED")

        # Add bugs
        engine.register_bug(bug_id="BUG-001", module="core/foo.py", title="Bug 1")
        engine.register_bug(bug_id="BUG-002", module="core/bar.py", title="Bug 2")
        engine.resolve_bug("BUG-001")

        # Add goals
        engine.register_goal(goal_id="GOAL-001", title="Goal 1", target_value=100.0)
        engine.update_goal_progress("GOAL-001", 80.0)

        report = engine.get_portfolio_report()
        assert isinstance(report, PortfolioReport)
        assert report.n_epics >= 1
        assert report.n_features >= 2
        assert report.n_bugs >= 2
        assert report.n_goals >= 1
        assert report.feature_completion_pct > 0
        assert report.bug_resolution_pct > 0

    def test_get_portfolio_report_empty(self):
        engine = get_portfolio_intelligence()
        report = engine.get_portfolio_report()
        assert report.health in ("HEALTHY", "AT_RISK", "CRITICAL")

    def test_get_epic_details(self):
        engine = get_portfolio_intelligence()
        engine.register_epic(epic_id="EPIC-001", title="Test Epic")
        engine.register_feature(epic_id="EPIC-001", feature_id="FTR-001", title="F1")
        details = engine.get_epic_details("EPIC-001")
        assert details is not None
        assert details["n_features"] >= 1
        assert details["epic"]["title"] == "Test Epic"

    def test_get_epic_details_not_found(self):
        engine = get_portfolio_intelligence()
        details = engine.get_epic_details("EPIC-MISSING")
        assert details is None

    def test_value_ratio(self):
        engine = get_portfolio_intelligence()
        engine.register_epic(epic_id="EPIC-001", title="Test")
        engine.register_feature(
            epic_id="EPIC-001",
            feature_id="FTR-001",
            title="High Value",
            business_value_score=10.0,
            estimated_hours=5.0,
        )
        engine.register_feature(
            epic_id="EPIC-001",
            feature_id="FTR-002",
            title="High Effort",
            business_value_score=2.0,
            estimated_hours=50.0,
        )
        report = engine.get_portfolio_report()
        assert len(report.highest_value_features) >= 2

    def test_health_critical(self):
        engine = get_portfolio_intelligence()
        engine.register_epic(epic_id="EPIC-001", title="Test")
        engine.register_feature(epic_id="EPIC-001", feature_id="FTR-001", title="F1")
        # Many unresolved bugs
        for i in range(5):
            engine.register_bug(bug_id=f"BUG-{i:03d}", module="core/foo.py", title=f"Bug {i}")
        report = engine.get_portfolio_report()
        assert report.health in ("HEALTHY", "AT_RISK", "CRITICAL")

    def test_get_stats(self):
        engine = get_portfolio_intelligence()
        stats = engine.get_stats()
        assert "epics" in stats
        assert "features" in stats
        assert "bugs" in stats
        assert "goals" in stats

    def test_summary_text(self):
        engine = get_portfolio_intelligence()
        engine.register_epic(epic_id="EPIC-001", title="Risk Management")
        engine.register_feature(epic_id="EPIC-001", feature_id="FTR-001", title="Circuit Breaker")
        report = engine.get_portfolio_report()
        summary = report.summary_text()
        assert "ENTERPRISE PORTFOLIO INTELLIGENCE" in summary
        assert "Health" in summary
        assert "Epics" in summary


if __name__ == "__main__":
    pytest.main([__file__])
