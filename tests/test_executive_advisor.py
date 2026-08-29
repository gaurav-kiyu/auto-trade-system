"""Tests for Executive Advisor module."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.executive_advisor import (
    ExecutiveBriefing,
    MetricHighlight,
    PerformanceBriefing,
    RiskBriefing,
    SystemHealthBriefing,
    get_executive_advisor,
    reset_executive_advisor,
)


@pytest.fixture(autouse=True)
def reset_advisor():
    reset_executive_advisor()
    p = Path("json/executive_briefings.json")
    if p.exists():
        p.unlink()
    yield
    reset_executive_advisor()


class TestBriefingGeneration:
    def test_generate_daily_briefing(self):
        advisor = get_executive_advisor()
        briefing = advisor.generate_daily_briefing()
        assert briefing.title is not None
        assert "Daily Executive Briefing" in briefing.title
        assert len(briefing.summary) > 0
        assert len(briefing.key_metrics) > 0

    def test_briefing_has_risk(self):
        advisor = get_executive_advisor()
        briefing = advisor.generate_daily_briefing()
        assert briefing.risk_briefing.overall_risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    def test_briefing_has_performance(self):
        advisor = get_executive_advisor()
        briefing = advisor.generate_daily_briefing()
        assert briefing.performance_briefing.total_trades >= 0

    def test_briefing_has_system_health(self):
        advisor = get_executive_advisor()
        briefing = advisor.generate_daily_briefing()
        assert briefing.system_health.overall_score >= 0
        assert briefing.system_health.security_score >= 0

    def test_briefing_has_strategic_insights(self):
        advisor = get_executive_advisor()
        briefing = advisor.generate_daily_briefing()
        assert len(briefing.strategic_insights) > 0

    def test_briefing_has_recommendations(self):
        advisor = get_executive_advisor()
        briefing = advisor.generate_daily_briefing()
        assert len(briefing.top_recommendations) > 0

    def test_briefing_summary_text(self):
        advisor = get_executive_advisor()
        briefing = advisor.generate_daily_briefing()
        text = briefing.summary_text()
        assert "EXECUTIVE BRIEFING" in text or "Daily Executive" in text

    def test_key_metrics_generated(self):
        advisor = get_executive_advisor()
        briefing = advisor.generate_daily_briefing()
        names = [m.name for m in briefing.key_metrics]
        assert "System Health" in names
        assert "Win Rate" in names or "Total P&L" in names

    def test_get_latest_briefing(self):
        advisor = get_executive_advisor()
        assert advisor.get_latest_briefing() is None
        briefing = advisor.generate_daily_briefing()
        latest = advisor.get_latest_briefing()
        assert latest is not None
        assert latest.title == briefing.title

    def test_get_stats(self):
        advisor = get_executive_advisor()
        advisor.generate_daily_briefing()
        stats = advisor.get_stats()
        assert stats["total_briefings"] >= 1
        assert len(stats["latest_summary"]) > 0


class TestExecutiveModels:
    def test_metric_highlight_to_dict(self):
        m = MetricHighlight(name="Win Rate", value="75%", status="GOOD")
        d = m.to_dict()
        assert d["name"] == "Win Rate"
        assert d["status"] == "GOOD"

    def test_risk_briefing_to_dict(self):
        r = RiskBriefing(var_95=5000, overall_risk_level="MEDIUM")
        d = r.to_dict()
        assert d["var_95"] == 5000
        assert d["overall_risk_level"] == "MEDIUM"

    def test_performance_briefing_to_dict(self):
        p = PerformanceBriefing(win_rate=65.0, total_trades=100, sharpe_ratio=1.5)
        d = p.to_dict()
        assert d["win_rate"] == 65.0
        assert d["total_trades"] == 100

    def test_system_health_briefing_to_dict(self):
        h = SystemHealthBriefing(overall_score=8.5, broker_health="HEALTHY")
        d = h.to_dict()
        assert d["overall_score"] == 8.5

    def test_briefing_summary_text(self):
        b = ExecutiveBriefing(
            title="Daily Briefing",
            summary="System health: 8.5/10",
            generated_at=1000.0,
        )
        text = b.summary_text()
        assert "Daily Briefing" in text
        assert "8.5" in text
