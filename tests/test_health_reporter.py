"""Tests for core.health_reporter - weekly system health audit."""

from __future__ import annotations

import tempfile
from pathlib import Path

from core.health_reporter import HealthReporter, HealthScore


class TestHealthScore:
    """Tests for HealthScore dataclass."""

    def test_defaults(self) -> None:
        score = HealthScore(overall=85.0, db_health="PASS", ml_drift="STABLE", api_stability="GOOD", recommendation="OK")
        assert score.overall == 85.0
        assert score.db_health == "PASS"


class TestHealthReporter:
    """Tests for HealthReporter - weekly audit runner."""

    def setup_method(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            self.db_path = f.name
        # Create a valid SQLite DB
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY)")
        conn.close()
        self.reporter = HealthReporter({}, self.db_path)

    def teardown_method(self) -> None:
        Path(self.db_path).unlink(missing_ok=True)

    def test_init(self) -> None:
        assert self.reporter.cfg == {}
        assert self.reporter.db_path == self.db_path

    def test_db_check_passes(self) -> None:
        result = self.reporter._check_db()
        assert result == "PASS"

    def test_db_check_fails_with_nonexistent_db(self) -> None:
        reporter = HealthReporter({}, "/nonexistent/db.sqlite")
        result = reporter._check_db()
        assert result == "FAIL"

    def test_run_weekly_audit_success(self) -> None:
        score = self.reporter.run_weekly_audit()
        assert score.overall == 100.0
        assert score.db_health == "PASS"
        assert score.ml_drift == "STABLE"
        assert score.api_stability == "GOOD"

    def test_run_weekly_audit_failure(self) -> None:
        reporter = HealthReporter({}, "/nonexistent/db.sqlite")
        score = reporter.run_weekly_audit()
        # DB check returns FAIL but the weighted audit formula still produces a
        # non-zero score (base 70 × 0.4 + data-quality + invariants + governance).
        # Full 0.0 only occurs on crash / exception path.
        assert 0.0 < score.overall < 100.0
        assert score.overall > 70.0
        assert score.db_health == "FAIL"
        assert "Urgent" not in score.recommendation

    def test_format_telegram_report(self) -> None:
        score = HealthScore(
            overall=85.5, db_health="PASS", ml_drift="STABLE", api_stability="GOOD",
            recommendation="Proceed",
        )
        report = self.reporter.format_telegram_report(score)
        assert "85.5%" in report
        assert "PASS" in report
        assert "STABLE" in report
        assert "SUNDAY" in report

    def test_format_telegram_report_str_dq_score_does_not_crash(self) -> None:
        """data_quality_score arriving as a string must not crash the report."""
        score = HealthScore(
            overall=85.5, db_health="PASS", ml_drift="STABLE", api_stability="GOOD",
            data_quality_score="N/A",  # defensive: non-float value
        )
        report = self.reporter.format_telegram_report(score)
        assert "85.5%" in report
        assert "Data Quality" in report
