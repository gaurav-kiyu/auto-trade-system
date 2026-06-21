"""Unit tests for capacity_planning.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.capacity_planning import (
    CapacityPlanner,
    GrowthForecast,
    ResourceMetric,
)


class TestResourceMetric:
    """ResourceMetric dataclass tests."""

    def test_basic_creation(self):
        m = ResourceMetric(resource="disk", current_value=10.0, unit="GB",
                          status="OK", threshold=5.0)
        assert m.resource == "disk"
        assert m.current_value == 10.0
        assert m.status == "OK"

    def test_default_message_empty(self):
        m = ResourceMetric(resource="cpu", current_value=50.0, unit="%",
                          status="WARN", threshold=80.0)
        assert m.message == ""


class TestGrowthForecast:
    """GrowthForecast dataclass tests."""

    def test_basic_creation(self):
        f = GrowthForecast(
            resource="trades.db", current_size_mb=100.0,
            daily_growth_mb=1.0, forecast_30d_mb=130.0,
            forecast_90d_mb=190.0, days_until_capacity=900,
        )
        assert f.resource == "trades.db"
        assert f.current_size_mb == 100.0
        assert f.status == "OK"

    def test_to_dict_includes_all_fields(self):
        f = GrowthForecast(
            resource="test.db", current_size_mb=50.0,
            daily_growth_mb=0.5, forecast_30d_mb=65.0,
            forecast_90d_mb=95.0, days_until_capacity=1900,
        )
        d = f.to_dict()
        assert d["resource"] == "test.db"
        assert d["current_size_mb"] == 50.0
        assert d["daily_growth_mb"] == 0.5
        assert d["forecast_90d_mb"] == 95.0


class TestCapacityPlanner:
    """CapacityPlanner tests."""

    def test_init_defaults(self):
        planner = CapacityPlanner()
        assert planner._cfg == {}

    def test_init_with_config(self):
        planner = CapacityPlanner({"capacity_warn_disk_gb": 10.0})
        assert planner._cfg["capacity_warn_disk_gb"] == 10.0

    def test_analyze_returns_report(self):
        """analyze() runs and returns a CapacityReport without error."""
        planner = CapacityPlanner()
        report = planner.analyze()
        assert report is not None
        assert report.overall_status in ("OK", "WARN", "CRITICAL")
        assert len(report.metrics) >= 3  # disk, logs, memory at minimum

    def test_analyze_includes_trade_check(self):
        """analyze() includes trade_throughput metric even without DB."""
        planner = CapacityPlanner()
        report = planner.analyze()
        throughputs = [m for m in report.metrics if m.resource == "trade_throughput"]
        assert len(throughputs) >= 1

    def test_analyze_includes_disk_check(self):
        """analyze() includes disk_free_space metric."""
        planner = CapacityPlanner()
        report = planner.analyze()
        disks = [m for m in report.metrics if m.resource == "disk_free_space"]
        assert len(disks) >= 1

    def test_analyze_includes_log_check(self):
        """analyze() includes log_directory_size metric."""
        planner = CapacityPlanner()
        report = planner.analyze()
        logs = [m for m in report.metrics
                if m.resource == "log_directory_size"]
        # May be 0 if logs dir doesn't exist — that's fine, just check it's present
        assert len(logs) >= 1

    def test_analyze_includes_memory_check(self):
        """analyze() includes process_memory metric."""
        planner = CapacityPlanner()
        report = planner.analyze()
        mems = [m for m in report.metrics if m.resource == "process_memory"]
        assert len(mems) >= 1

    @patch("core.capacity_planning.Path.is_file")
    def test_estimate_db_growth_no_db(self, mock_is_file):
        mock_is_file.return_value = False
        planner = CapacityPlanner()
        result = planner.estimate_db_growth("nonexistent.db")
        assert result is None

    def test_ok_count_property(self):
        report = CapacityPlanner().analyze()
        assert report.ok_count >= 0
        assert report.ok_count == sum(1 for m in report.metrics if m.status == "OK")

    def test_warn_count_property(self):
        report = CapacityPlanner().analyze()
        assert report.warn_count >= 0

    def test_critical_count_property(self):
        report = CapacityPlanner().analyze()
        assert report.critical_count >= 0

    def test_summary_text_output(self):
        """summary_text() returns a non-empty string."""
        planner = CapacityPlanner()
        report = planner.analyze()
        text = report.summary_text()
        assert isinstance(text, str)
        assert len(text) > 20

    def test_to_dict_output(self):
        """to_dict() returns a dict with expected keys."""
        planner = CapacityPlanner()
        report = planner.analyze()
        d = report.to_dict()
        assert "timestamp" in d
        assert "overall_status" in d
        assert "metrics" in d
        assert "forecasts" in d
        assert "summary" in d

    @patch("core.capacity_planning.CapacityPlanner._check_databases")
    def test_no_db_does_not_crash(self, mock_dbs):
        """Even with empty DB results, analyze() doesn't crash."""
        mock_dbs.return_value = None
        planner = CapacityPlanner()
        report = planner.analyze()
        assert report is not None

    def test_file_age_days_positive(self):
        """_file_age_days returns a positive value for existing files."""
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test")
            fname = f.name
        try:
            from pathlib import Path
            planner = CapacityPlanner()
            age = planner._file_age_days(Path(fname))
            assert age >= 0.0
        finally:
            os.unlink(fname)
