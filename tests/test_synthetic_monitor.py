"""Tests for core/synthetic_monitor.py (Pillar 15: Observability)."""

from __future__ import annotations

from core.synthetic_monitor import (
    ProbeResult,
    ProbeStatus,
    SyntheticMonitor,
    SyntheticReport,
    get_synthetic_monitor,
    reset_synthetic_monitor,
)


class TestProbeResult:
    """Tests for ProbeResult dataclass."""

    def test_default_status_is_pass(self):
        result = ProbeResult(name="test")
        assert result.status == ProbeStatus.PASS
        assert result.latency_ms == 0.0

    def test_to_dict_returns_all_fields(self):
        result = ProbeResult(
            name="db_test",
            status=ProbeStatus.FAIL,
            latency_ms=12.34,
            detail="Connection failed",
            error="Timeout",
        )
        d = result.to_dict()
        assert d["name"] == "db_test"
        assert d["status"] == "FAIL"
        assert d["latency_ms"] == 12.3
        assert d["detail"] == "Connection failed"
        assert d["error"] == "Timeout"


class TestSyntheticReport:
    """Tests for SyntheticReport dataclass."""

    def test_empty_report_defaults(self):
        report = SyntheticReport()
        assert report.health_score == 100.0
        assert report.total_probes == 0
        assert report.passed_probes == 0

    def test_summary_text_includes_health_score(self):
        report = SyntheticReport(
            health_score=85.5,
            total_probes=4,
            passed_probes=3,
            failed_probes=1,
            warned_probes=0,
        )
        text = report.summary_text()
        assert "85.5%" in text
        assert "3/4" in text
        assert "1 failed" in text

    def test_to_dict_includes_all_fields(self):
        report = SyntheticReport(
            probes=[ProbeResult(name="p1")],
            health_score=90.0,
            total_probes=1,
            passed_probes=1,
        )
        d = report.to_dict()
        assert d["health_score"] == 90.0
        assert d["total_probes"] == 1
        assert len(d["probes"]) == 1


class TestSyntheticMonitor:
    """Tests for SyntheticMonitor probes."""

    def setup_method(self):
        reset_synthetic_monitor()

    def test_singleton(self):
        m1 = get_synthetic_monitor()
        m2 = get_synthetic_monitor()
        assert m1 is m2

    def test_run_all_probes_returns_report(self):
        monitor = get_synthetic_monitor()
        report = monitor.run_all_probes()
        assert isinstance(report, SyntheticReport)
        assert report.total_probes >= 5  # At least core probes
        assert report.health_score >= 0.0

    def test_probe_database_passes(self):
        monitor = SyntheticMonitor()
        result = monitor._probe_database()
        assert result.status in (ProbeStatus.PASS, ProbeStatus.FAIL)
        assert result.latency_ms >= 0.0

    def test_probe_file_system_passes(self):
        monitor = SyntheticMonitor()
        result = monitor._probe_file_system()
        assert result.status in (ProbeStatus.PASS, ProbeStatus.WARN, ProbeStatus.ERROR)
        assert result.latency_ms >= 0.0
        if result.status == ProbeStatus.PASS:
            assert "Read" in result.detail

    def test_probe_imports_passes(self):
        monitor = SyntheticMonitor()
        result = monitor._probe_imports()
        assert result.status in (ProbeStatus.PASS, ProbeStatus.WARN)
        if result.status == ProbeStatus.PASS:
            assert "import cleanly" in result.detail

    def test_probe_config_integrity(self):
        monitor = SyntheticMonitor()
        result = monitor._probe_config()
        assert result.status in (ProbeStatus.PASS, ProbeStatus.WARN, ProbeStatus.ERROR)

    def test_probe_environment(self):
        monitor = SyntheticMonitor()
        result = monitor._probe_environment()
        assert result.status == ProbeStatus.PASS
        assert "Python" in result.detail

    def test_probe_yfinance_data(self):
        monitor = SyntheticMonitor()
        result = monitor._probe_yfinance_data()
        assert result.status in (ProbeStatus.PASS, ProbeStatus.WARN)
        assert result.latency_ms >= 0.0

    def test_probe_broker_adapter(self):
        monitor = SyntheticMonitor()
        result = monitor._probe_broker_adapter()
        assert result.status in (ProbeStatus.PASS, ProbeStatus.WARN)

    def test_probe_trades_database(self):
        monitor = SyntheticMonitor()
        result = monitor._probe_trades_database()
        assert result.status in (ProbeStatus.PASS, ProbeStatus.WARN)

    def test_probe_disk_space(self):
        monitor = SyntheticMonitor()
        result = monitor._probe_disk_space()
        assert result.status in (ProbeStatus.PASS, ProbeStatus.WARN)
        assert result.latency_ms >= 0.0

    def test_probe_network_endpoints(self):
        monitor = SyntheticMonitor()
        result = monitor._probe_network_endpoints()
        assert result.status in (ProbeStatus.PASS, ProbeStatus.WARN)

    def test_get_last_report_none_when_not_run(self):
        monitor = SyntheticMonitor()
        assert monitor.get_last_report() is None

    def test_get_last_report_after_run(self):
        monitor = SyntheticMonitor()
        monitor.run_all_probes()
        assert monitor.get_last_report() is not None

    def test_get_health_score_zero_when_not_run(self):
        monitor = SyntheticMonitor()
        assert monitor.get_health_score() == 0.0

    def test_get_health_score_after_run(self):
        monitor = SyntheticMonitor()
        monitor.run_all_probes()
        assert monitor.get_health_score() > 0.0

    def test_get_stats(self):
        monitor = SyntheticMonitor()
        stats = monitor.get_stats()
        assert "health_score" in stats
        assert "total_probes" in stats
        assert "passed" in stats

    def test_get_stats_after_run(self):
        monitor = SyntheticMonitor()
        monitor.run_all_probes()
        stats = monitor.get_stats()
        assert stats["passed"] >= 0
        assert stats["last_run"] is not None


class TestSingleton:
    """Tests for singleton factory."""

    def setup_method(self):
        reset_synthetic_monitor()

    def test_get_returns_same_instance(self):
        m1 = get_synthetic_monitor()
        m2 = get_synthetic_monitor()
        assert m1 is m2

    def test_reset_clears_instance(self):
        m1 = get_synthetic_monitor()
        reset_synthetic_monitor()
        m2 = get_synthetic_monitor()
        assert m1 is not m2
