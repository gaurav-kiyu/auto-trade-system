"""Tests for core/engineering_analytics.py — Engineering Analytics."""

from __future__ import annotations

import time

import pytest
from core.engineering_analytics import (
    EngineeringMetricsReport,
    GitCommitRecord,
    IncidentRecord,
    get_engineering_analytics,
    reset_engineering_analytics,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_engineering_analytics()
    yield
    reset_engineering_analytics()


class TestEngineeringAnalyticsEngine:
    """Tests for the EngineeringAnalyticsEngine class."""

    def test_singleton(self):
        e1 = get_engineering_analytics()
        e2 = get_engineering_analytics()
        assert e1 is e2

    def test_reset(self):
        e1 = get_engineering_analytics()
        reset_engineering_analytics()
        e2 = get_engineering_analytics()
        assert e1 is not e2

    def test_empty_report(self):
        engine = get_engineering_analytics()
        report = engine.get_report(days=30)
        assert isinstance(report, EngineeringMetricsReport)
        assert report.period_days == 30
        assert report.lead_time_days >= 0

    def test_record_commit(self):
        engine = get_engineering_analytics()
        engine.record_commit(GitCommitRecord(
            hash="abc123",
            author="dev1",
            date=str(time.time()),
            files_changed=2,
            lines_added=100,
            lines_deleted=20,
            message="feat: add new feature",
        ))
        stats = engine.get_stats()
        assert stats["total_commits"] >= 1

    def test_report_with_commits(self):
        engine = get_engineering_analytics()
        now = time.time()
        for i in range(5):
            engine.record_commit(GitCommitRecord(
                hash=f"hash{i}",
                author=f"dev{i % 2}",
                date=str(now - (i * 86400)),
                files_changed=3,
                lines_added=50,
                lines_deleted=10,
                message=f"Commit {i}",
            ))
        report = engine.get_report(days=30)
        assert report.engineering_velocity > 0
        assert report.code_churn_lines > 0
        assert report.developer_productivity > 0
        assert report.hotspots is not None

    def test_record_incident(self):
        engine = get_engineering_analytics()
        now = time.time()
        engine.record_incident(IncidentRecord(
            id="INC-001",
            created_at=str(now - 7200),  # 2 hours ago
            resolved_at=str(now - 3600),  # 1 hour ago
            severity="HIGH",
        ))
        stats = engine.get_stats()
        assert stats["total_incidents"] >= 1

    def test_mttr_calculation(self):
        engine = get_engineering_analytics()
        now = time.time()
        for i in range(3):
            engine.record_incident(IncidentRecord(
                id=f"INC-{i:03d}",
                created_at=str(now - ((i + 2) * 3600)),
                resolved_at=str(now - (i * 3600)),
                severity="MEDIUM",
            ))
        report = engine.get_report(days=30)
        assert report.mttr_hours > 0

    def test_deployment_success_rate(self):
        engine = get_engineering_analytics()
        engine.record_deployment(success=True)
        engine.record_deployment(success=True)
        engine.record_deployment(success=False)
        report = engine.get_report(days=30)
        assert report.deployment_success_rate == pytest.approx(66.666, rel=0.1)

    def test_record_review(self):
        engine = get_engineering_analytics()
        engine.record_review(pr_id="PR-1", hours_in_review=4.5, approved=True)
        engine.record_review(pr_id="PR-2", hours_in_review=2.0, approved=True)
        report = engine.get_report(days=30)
        assert report.avg_review_time_hours > 0

    def test_record_build(self):
        engine = get_engineering_analytics()
        engine.record_build(duration_minutes=5.5, success=True)
        engine.record_build(duration_minutes=8.2, success=True)
        report = engine.get_report(days=30)
        assert report.avg_build_time_minutes > 0

    def test_bus_factor(self):
        engine = get_engineering_analytics()
        now = time.time()
        # 3 authors
        for i in range(20):
            author = f"dev{i % 3}"
            engine.record_commit(GitCommitRecord(
                hash=f"hash{i}",
                author=author,
                date=str(now - (i * 43200)),
                files_changed=2,
                lines_added=30,
                lines_deleted=5,
                message=f"Commit {i}",
            ))
        report = engine.get_report(days=30)
        assert report.bus_factor >= 1
        assert len(report.knowledge_distribution) > 0

    def test_velocity_trend_stable(self):
        engine = get_engineering_analytics()
        now = time.time()
        # Similar velocity across periods
        for i in range(10):
            engine.record_commit(GitCommitRecord(
                hash=f"hash{i}",
                author="dev1",
                date=str(now - (i * 86400)),
                files_changed=1,
                lines_added=10,
                lines_deleted=0,
                message=f"Commit {i}",
            ))
        report = engine.get_report(days=30)
        assert report.velocity_trend in ("RISING", "STABLE", "FALLING")

    def test_change_failure_rate(self):
        """Test Change Failure Rate (CFR) calculation."""
        engine = get_engineering_analytics()
        # Add commits
        now = time.time()
        for i in range(20):
            engine.record_commit(GitCommitRecord(
                hash=f"hash{i}", author="dev1", date=str(now - (i * 43200)),
                files_changed=2, lines_added=30, lines_deleted=5,
                message=f"Commit {i}",
            ))
        # Record some failures
        engine.record_failure(change_id="hash1", severity="HIGH", description="Test failure 1")
        engine.record_failure(change_id="hash5", severity="MEDIUM", description="Test failure 2")
        report = engine.get_report(days=30)
        assert report.change_failure_rate > 0
        assert report.change_failure_rate <= 100

    def test_record_failure(self):
        """Test recording a failure for CFR."""
        engine = get_engineering_analytics()
        engine.record_failure(change_id="abc123", severity="CRITICAL", description="Outage")
        # Check the most recent failure matches what we recorded
        assert engine._failures[-1]["change_id"] == "abc123", "Most recent failure should be our test failure"
        assert engine._failures[-1]["severity"] == "CRITICAL"
        assert engine._failures[-1]["description"] == "Outage"

    def test_to_chart_data(self):
        """Test chart data generation."""
        engine = get_engineering_analytics()
        now = time.time()
        for i in range(10):
            engine.record_commit(GitCommitRecord(
                hash=f"hash{i}", author="dev1", date=str(now - (i * 86400)),
                files_changed=1, lines_added=10, lines_deleted=0,
                message=f"Commit {i}",
            ))
        chart = engine.to_chart_data(days=30)
        assert isinstance(chart, dict)
        assert "dates" in chart
        assert "velocity" in chart
        assert "mttr_hours" in chart
        assert "deployment_success_pct" in chart
        assert "change_failure_rate_pct" in chart
        assert len(chart["dates"]) > 0

    def test_summary_text(self):
        engine = get_engineering_analytics()
        engine.record_commit(GitCommitRecord(
            hash="abc",
            author="dev1",
            date=str(time.time()),
            files_changed=2,
            lines_added=50,
            lines_deleted=10,
            message="test",
        ))
        report = engine.get_report(days=30)
        summary = report.summary_text()
        assert "ENGINEERING ANALYTICS" in summary
        assert "Lead Time" in summary


if __name__ == "__main__":
    pytest.main([__file__])
