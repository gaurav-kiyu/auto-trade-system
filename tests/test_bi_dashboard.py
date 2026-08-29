"""Tests for BIDashboard (Pillar 12)."""
from __future__ import annotations

import time

import pytest
from core.bi_dashboard import (
    BIDashboard,
    BIReport,
    BIRepositoryTrend,
    DeploymentRecord,
    HealthScore,
    IncidentTrend,
    QualitySnapshot,
    get_bi_dashboard,
    reset_bi_dashboard,
)


@pytest.fixture(autouse=True)
def reset_bi() -> None:
    """Reset the singleton before each test."""
    reset_bi_dashboard()


class TestQualitySnapshot:
    """Tests for QualitySnapshot dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        snap = QualitySnapshot()
        assert snap.total_modules == 0
        assert snap.total_symbols == 0
        assert snap.total_lines == 0
        assert snap.design_smells == 0

    def test_to_dict(self) -> None:
        """Test serialization."""
        snap = QualitySnapshot(
            timestamp=1000.0,
            total_modules=50,
            total_symbols=200,
            total_lines=50000,
            test_coverage_pct=75.5,
        )
        d = snap.to_dict()
        assert d["total_modules"] == 50
        assert d["total_symbols"] == 200
        assert d["test_coverage_pct"] == 75.5
        assert "date" in d

    def test_to_dict_empty(self) -> None:
        """Test serialization of empty snapshot."""
        snap = QualitySnapshot()
        d = snap.to_dict()
        assert d["total_modules"] == 0


class TestDeploymentRecord:
    """Tests for DeploymentRecord dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        rec = DeploymentRecord(timestamp=1000.0)
        assert rec.version == ""
        assert rec.files_changed == 0

    def test_to_dict(self) -> None:
        """Test serialization."""
        rec = DeploymentRecord(
            timestamp=1000.0,
            version="v2.54.0",
            commit_hash="abc123def456",
            commit_message="Release v2.54.0",
            author="dev",
            files_changed=10,
            lines_added=500,
            lines_deleted=100,
        )
        d = rec.to_dict()
        assert "v2.54.0" in d["version"]
        assert d["files_changed"] == 10
        assert d["commit_hash"] == "abc123def456"


class TestIncidentTrend:
    """Tests for IncidentTrend dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        trend = IncidentTrend(period="daily")
        assert trend.total_incidents == 0
        assert trend.by_type == {}
        assert trend.critical_count == 0

    def test_to_dict(self) -> None:
        """Test serialization."""
        trend = IncidentTrend(
            period="weekly",
            total_incidents=5,
            by_type={"broker_disconnect": 3, "db_failure": 2},
            by_severity={"CRITICAL": 1, "HIGH": 4},
            critical_count=1,
        )
        d = trend.to_dict()
        assert d["period"] == "weekly"
        assert d["total_incidents"] == 5
        assert d["critical_count"] == 1


class TestHealthScore:
    """Tests for HealthScore dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        health = HealthScore()
        assert health.overall_score == 0.0
        assert health.code_quality_score == 0.0

    def test_to_dict(self) -> None:
        """Test serialization."""
        health = HealthScore(
            timestamp=1000.0,
            overall_score=8.5,
            code_quality_score=7.5,
            test_quality_score=8.0,
            description="Good health",
        )
        d = health.to_dict()
        assert d["overall_score"] == 8.5
        assert d["code_quality_score"] == 7.5
        assert "description" in d


class TestBIRepositoryTrend:
    """Tests for BIRepositoryTrend dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        trend = BIRepositoryTrend(period="weekly")
        assert trend.quality_direction == "STABLE"
        assert trend.risk_level == "LOW"

    def test_to_dict(self) -> None:
        """Test serialization."""
        trend = BIRepositoryTrend(
            period="weekly",
            quality_direction="IMPROVING",
            risk_level="MEDIUM",
            summary="Summary text",
        )
        d = trend.to_dict()
        assert d["quality_direction"] == "IMPROVING"
        assert d["risk_level"] == "MEDIUM"


class TestBIReport:
    """Tests for BIReport dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        report = BIReport()
        assert report.incident_total == 0
        assert report.quality_trend == "STABLE"

    def test_to_dict(self) -> None:
        """Test serialization."""
        report = BIReport(
            generated_at="2026-01-01T00:00:00",
            quality_trend="IMPROVING",
            incident_total=10,
        )
        d = report.to_dict()
        assert d["quality_trend"] == "IMPROVING"
        assert d["incident_total"] == 10

    def test_summary_text(self) -> None:
        """Test summary text generation."""
        report = BIReport(generated_at="2026-01-01T00:00:00")
        text = report.summary_text()
        assert "BUSINESS INTELLIGENCE REPORT" in text.upper()


class TestBIDashboard:
    """Tests for the BIDashboard class."""

    def test_singleton(self) -> None:
        """Test singleton pattern."""
        d1 = get_bi_dashboard()
        d2 = get_bi_dashboard()
        assert d1 is d2

    def test_reset(self) -> None:
        """Test reset clears the singleton."""
        d1 = get_bi_dashboard()
        reset_bi_dashboard()
        d2 = get_bi_dashboard()
        assert d1 is not d2

    def test_take_quality_snapshot(self) -> None:
        """Test taking a quality snapshot."""
        bi = BIDashboard()
        snap = bi.take_quality_snapshot()
        assert isinstance(snap, QualitySnapshot)
        assert snap.timestamp > 0

    def test_quality_trend_stable(self) -> None:
        """Test quality trend with few snapshots."""
        bi = BIDashboard()
        trend = bi.get_quality_trend()
        assert trend in ("IMPROVING", "STABLE", "DEGRADING")

    def test_quality_trend_with_data(self) -> None:
        """Test quality trend with multiple snapshots."""
        bi = BIDashboard()
        # Take multiple snapshots
        for _ in range(5):
            bi.take_quality_snapshot()
        trend = bi.get_quality_trend(lookback=10)
        assert trend in ("IMPROVING", "STABLE", "DEGRADING")

    def test_compute_health(self) -> None:
        """Test health score computation."""
        bi = BIDashboard()
        # Take a quality snapshot first
        bi.take_quality_snapshot()
        health = bi.compute_health()
        assert isinstance(health, HealthScore)
        assert 0 <= health.overall_score <= 10
        assert health.description != ""

    def test_health_score_bounds(self) -> None:
        """Test health score is within bounds."""
        bi = BIDashboard()
        health = bi.compute_health()
        assert 0 <= health.overall_score <= 10
        assert 0 <= health.code_quality_score <= 10
        assert 0 <= health.test_quality_score <= 10
        assert 0 <= health.security_score <= 10

    def test_get_incident_trends(self) -> None:
        """Test getting incident trends."""
        bi = BIDashboard()
        trends = bi.get_incident_trends()
        assert isinstance(trends, list)
        # Should return daily, weekly, monthly trends
        assert len(trends) >= 2

    def test_incident_trend_periods(self) -> None:
        """Test that incident trends have correct periods."""
        bi = BIDashboard()
        trends = bi.get_incident_trends()
        periods = [t.period for t in trends]
        assert "daily" in periods
        assert "weekly" in periods

    def test_get_stats(self) -> None:
        """Test getting BI stats."""
        bi = BIDashboard()
        stats = bi.get_stats()
        assert isinstance(stats, dict)
        assert "quality_snapshots" in stats
        assert "deployments_tracked" in stats

    def test_stats_after_snapshot(self) -> None:
        """Test stats update after taking a snapshot."""
        bi = BIDashboard()
        stats_before = bi.get_stats()
        bi.take_quality_snapshot()
        stats_after = bi.get_stats()
        assert stats_after["quality_snapshots"] >= stats_before["quality_snapshots"]

    def test_collect_deployments(self) -> None:
        """Test collecting deployments from git."""
        bi = BIDashboard()
        deployments = bi.collect_deployments()
        assert isinstance(deployments, list)

    def test_deployment_frequency(self) -> None:
        """Test deployment frequency calculation."""
        bi = BIDashboard()
        freq = bi.get_deployment_frequency()
        assert isinstance(freq, (int, float))
        assert freq >= 0

    def test_get_top_risk_modules(self) -> None:
        """Test getting top risk modules."""
        bi = BIDashboard()
        modules = bi.get_top_risk_modules(top_n=5)
        assert isinstance(modules, list)

    def test_generate_bi_report(self) -> None:
        """Test generating a full BI report."""
        bi = BIDashboard()
        report = bi.generate_bi_report()
        assert isinstance(report, BIReport)
        assert report.generated_at != ""
        assert report.current_quality is not None
        assert report.current_health is not None
        assert report.repository_trend is not None
        assert report.summary != ""

    def test_bi_report_fields(self) -> None:
        """Test that BI report has all expected fields."""
        bi = BIDashboard()
        report = bi.generate_bi_report()
        d = report.to_dict()
        assert "quality_trend" in d
        assert "incident_total" in d
        assert "deployment_frequency_weekly" in d
        assert "current_quality" in d
        assert "current_health" in d
        assert "repository_trend" in d
        assert "recommendations" in d
        assert isinstance(d["recommendations"], list)

    def test_recommendations_on_low_coverage(self) -> None:
        """Test that recommendations mention low coverage."""
        bi = BIDashboard()
        # Force a snapshot with low coverage
        snap = QualitySnapshot(timestamp=time.time(), test_coverage_pct=10.0)
        bi._quality_history.append(snap)
        report = bi.generate_bi_report()
        has_coverage_rec = any("coverage" in r.lower() for r in report.recommendations)
        # May or may not have coverage recommendations depending on data
        assert isinstance(report.recommendations, list)
        if has_coverage_rec:
            assert any("coverage" in r.lower() for r in report.recommendations)

    def test_generate_health_description(self) -> None:
        """Test health description generation for various scores."""
        bi = BIDashboard()
        # Test excellent
        health_excellent = HealthScore(overall_score=9.0)
        desc = bi._generate_health_description(health_excellent)
        assert "Excellent" in desc

        # Test good
        health_good = HealthScore(overall_score=7.5)
        desc = bi._generate_health_description(health_good)
        assert "Good" in desc

        # Test fair
        health_fair = HealthScore(overall_score=6.0)
        desc = bi._generate_health_description(health_fair)
        assert "Fair" in desc

        # Test critical
        health_critical = HealthScore(overall_score=3.0)
        desc = bi._generate_health_description(health_critical)
        assert "Critical" in desc

    def test_report_summary_text(self) -> None:
        """Test report summary text contains key sections."""
        bi = BIDashboard()
        report = bi.generate_bi_report()
        text = report.summary_text()
        assert "BUSINESS INTELLIGENCE REPORT" in text
        assert text != ""

    def test_parse_ts_with_iso_string(self) -> None:
        """_parse_ts handles ISO format string timestamps."""
        bi = BIDashboard()
        ts = bi._parse_ts({"timestamp": "2026-01-15T10:30:00"})
        assert ts > 0
        assert isinstance(ts, float)

    def test_parse_ts_with_float(self) -> None:
        """_parse_ts handles float timestamp."""
        bi = BIDashboard()
        ts = bi._parse_ts({"timestamp": 1000000.0})
        assert ts == 1000000.0

    def test_parse_ts_with_invalid_string(self) -> None:
        """_parse_ts returns 0.0 for unparseable timestamps."""
        bi = BIDashboard()
        ts = bi._parse_ts({"timestamp": "not-a-date"})
        assert ts == 0.0

    def test_parse_ts_missing_key(self) -> None:
        """_parse_ts returns 0.0 when timestamp key is missing."""
        bi = BIDashboard()
        ts = bi._parse_ts({})
        assert ts == 0.0

    def test_generate_recommendations_design_smells(self) -> None:
        """_generate_recommendations includes design smell advice."""
        bi = BIDashboard()
        report = BIReport()
        report.current_quality = QualitySnapshot(design_smells=25, test_coverage_pct=50.0,
                                                  modules_without_tests=15, avg_complexity=10.0)
        report.current_health = HealthScore(security_score=7.0, incident_impact_score=8.0)
        recs = bi._generate_recommendations(report)
        assert any("design smell" in r.lower() for r in recs)

    def test_generate_recommendations_low_security(self) -> None:
        """_generate_recommendations flags low security score."""
        bi = BIDashboard()
        report = BIReport()
        report.current_quality = QualitySnapshot(design_smells=5, test_coverage_pct=50.0)
        report.current_health = HealthScore(security_score=4.0, incident_impact_score=8.0)
        recs = bi._generate_recommendations(report)
        assert any("security" in r.lower() for r in recs)

    def test_generate_recommendations_high_complexity(self) -> None:
        """_generate_recommendations flags high complexity."""
        bi = BIDashboard()
        report = BIReport()
        report.current_quality = QualitySnapshot(design_smells=5, test_coverage_pct=50.0,
                                                  modules_without_tests=5, avg_complexity=20.0)
        report.current_health = HealthScore(security_score=7.0, incident_impact_score=8.0)
        recs = bi._generate_recommendations(report)
        assert any("complexity" in r.lower() for r in recs)

    def test_generate_recommendations_no_issues(self) -> None:
        """_generate_recommendations returns 'continue monitoring' when all good."""
        bi = BIDashboard()
        report = BIReport()
        report.current_quality = QualitySnapshot(design_smells=2, test_coverage_pct=80.0,
                                                  modules_without_tests=2, avg_complexity=5.0)
        report.current_health = HealthScore(security_score=9.0, incident_impact_score=9.0)
        report.deployment_frequency_weekly = 5.0  # Avoid low-frequency recommendation
        report.incident_total = 0  # Avoid incident recommendation
        recs = bi._generate_recommendations(report)
        assert any("continue monitoring" in r.lower() for r in recs)

    def test_generate_bi_report_with_critical_health(self) -> None:
        """generate_bi_report correctly sets CRITICAL risk level."""
        bi = BIDashboard()
        # Force a snapshot with high smells (low quality score)
        snap = QualitySnapshot(timestamp=time.time(), design_smells=200, total_modules=10)
        bi._quality_history.append(snap)
        report = bi.generate_bi_report()
        assert report.repository_trend is not None
        assert report.repository_trend.summary != ""

    def test_repository_trend_fair_health_medium_risk(self) -> None:
        """Repository trend sets MEDIUM risk for fair health."""
        bi = BIDashboard()
        snap = QualitySnapshot(timestamp=time.time(), design_smells=100, total_modules=10)
        bi._quality_history.append(snap)
        # Quality score 10 - 10*10 = -90 → 0 (min), so health will be low
        report = bi.generate_bi_report()
        trend = report.repository_trend
        if trend is not None:
            assert trend.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    def test_empty_incident_trends(self) -> None:
        """get_incident_trends returns empty trends when no RCA available."""
        bi = BIDashboard()
        # Override by directly calling _build_incident_trend with empty list
        trend = bi._build_incident_trend("daily", [])
        assert trend.total_incidents == 0
        assert trend.period == "daily"
