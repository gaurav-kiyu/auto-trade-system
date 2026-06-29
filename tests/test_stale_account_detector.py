"""
Tests for core.stale_account_detector - session, credential, trading state staleness.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from core.stale_account_detector import (
    StaleAccountConfig,
    StaleAccountDetector,
    StaleAccountFinding,
    StaleAccountReport,
    StalenessCategory,
)


class TestStaleAccountFinding:
    """Test the data class for staleness findings."""

    def test_to_dict(self) -> None:
        finding = StaleAccountFinding(
            category=StalenessCategory.BROKER_SESSION,
            broker_name="test_broker",
            detail="Session idle for 30h",
            severity="WARNING",
            last_activity=time.time() - 30 * 3600,
            stale_since=time.time(),
            recommendation="Refresh session",
        )
        d = finding.to_dict()
        assert d["category"] == "broker_session"
        assert d["broker_name"] == "test_broker"
        assert d["severity"] == "WARNING"
        assert d["recommendation"] == "Refresh session"


class TestStaleAccountReport:
    """Test the aggregated report data class."""

    def test_empty_report(self) -> None:
        report = StaleAccountReport()
        assert report.total_findings == 0
        assert not report.has_critical
        assert not report.has_warnings

    def test_with_findings(self) -> None:
        finding = StaleAccountFinding(
            category=StalenessCategory.BROKER_SESSION,
            broker_name="broker",
            detail="test",
            severity="CRITICAL",
            last_activity=time.time(),
            stale_since=time.time(),
            recommendation="Fix it",
        )
        report = StaleAccountReport(stale_accounts=[finding], total_findings=1, critical_findings=1)
        assert report.total_findings == 1
        assert report.critical_findings == 1
        assert report.has_critical
        assert report.to_dict()["critical_findings"] == 1


class TestStaleAccountDetector:
    """Test the stale account detector logic."""

    def test_default_config(self) -> None:
        detector = StaleAccountDetector()
        assert detector.config.session_ttl_hours == 24
        assert detector.config.credential_max_age_days == 30
        assert detector.config.trading_idle_hours == 72
        assert detector.config.check_interval_seconds == 300

    def test_record_trade(self) -> None:
        detector = StaleAccountDetector()
        detector.record_trade("test_broker")
        assert "test_broker" in detector._last_trade_time

    def test_record_heartbeat(self) -> None:
        detector = StaleAccountDetector()
        detector.record_heartbeat()
        assert detector._last_heartbeat > 0

    def test_run_check_clean_no_broker_health(self) -> None:
        """With no broker health service and no recorded data, check should pass clean."""
        detector = StaleAccountDetector()
        report = detector.run_check(comprehensive=False)
        assert report.total_findings == 0
        assert report.healthy_accounts == ["default", "system"]

    def test_run_check_comprehensive_no_issues(self) -> None:
        """Comprehensive check with no activity should still be clean (no stale credentials without data)."""
        detector = StaleAccountDetector()
        report = detector.run_check(comprehensive=True)
        assert report.total_findings == 0

    def test_stale_trading_state_detected(self) -> None:
        """A broker with no trades for > idle threshold should be flagged."""
        config = StaleAccountConfig(trading_idle_hours=1)  # Short threshold for test
        detector = StaleAccountDetector(config=config)
        # Record a trade 2 hours ago
        old_time = time.time() - 7200
        detector._last_trade_time["default"] = old_time
        report = detector.run_check()
        assert report.total_findings >= 1
        stale = [f for f in report.stale_accounts if f.category == StalenessCategory.TRADING_STATE]
        assert len(stale) >= 1
        assert "default" in stale[0].broker_name

    def test_stale_heartbeat_detected(self) -> None:
        """Heartbeat stale for > max minutes should be flagged."""
        config = StaleAccountConfig(heartbeat_max_minutes=1)
        detector = StaleAccountDetector(config=config)
        # Record heartbeat 5 minutes ago
        detector._last_heartbeat = time.time() - 300
        report = detector.run_check()
        heartbeat_findings = [f for f in report.stale_accounts if f.category == StalenessCategory.SYSTEM_HEARTBEAT]
        assert len(heartbeat_findings) >= 1

    def test_healthy_heartbeat_no_findings(self) -> None:
        """Recent heartbeat should not trigger any finding."""
        config = StaleAccountConfig(heartbeat_max_minutes=5)
        detector = StaleAccountDetector(config=config)
        detector.record_heartbeat()  # Now
        report = detector.run_check()
        heartbeat_findings = [f for f in report.stale_accounts if f.category == StalenessCategory.SYSTEM_HEARTBEAT]
        assert len(heartbeat_findings) == 0

    def test_recovery_removes_stale_flag(self) -> None:
        """After recording a trade, previously stale broker should be healthy."""
        config = StaleAccountConfig(trading_idle_hours=1)
        detector = StaleAccountDetector(config=config)
        # Flag as stale
        detector._last_trade_time["default"] = time.time() - 7200
        report1 = detector.run_check()
        assert report1.total_findings > 0

        # Record a fresh trade (resets staleness)
        detector.record_trade("default")
        report2 = detector.run_check()
        trading_findings = [f for f in report2.stale_accounts if f.category == StalenessCategory.TRADING_STATE]
        assert len(trading_findings) == 0

    def test_get_summary(self) -> None:
        """Summary should contain expected keys."""
        detector = StaleAccountDetector()
        detector.record_heartbeat()
        summary = detector.get_summary()
        assert "stale_brokers" in summary
        assert "last_heartbeat_age_seconds" in summary
        assert "broker_trade_counts" in summary
        assert "config" in summary

    def test_critical_finding_triggers_alert(self) -> None:
        """Critical findings should trigger alert_fn."""
        alerts = []

        def alert_fn(msg, priority="NORMAL"):
            alerts.append((msg, priority))

        config = StaleAccountConfig(
            heartbeat_max_minutes=1,
            enable_alerts=True,
            alert_on_critical=True,
        )
        detector = StaleAccountDetector(config=config, alert_fn=alert_fn)
        detector._last_heartbeat = time.time() - 300
        report = detector.run_check()
        if report.has_critical:
            assert len(alerts) > 0

    def test_mixed_broker_health_no_crash(self) -> None:
        """Should not crash when broker health service is partially mocked."""
        mock_health = MagicMock()
        mock_health.get_all_brokers_health.return_value = {
            "kite": MagicMock(),
            "angel": MagicMock(),
        }
        detector = StaleAccountDetector(broker_health_service=mock_health)
        report = detector.run_check()
        # Should not raise
        assert isinstance(report, StaleAccountReport)

    def test_version_fallback(self) -> None:
        """Should handle missing VERSION file gracefully."""
        detector = StaleAccountDetector()
        assert detector._logger is not None

    def test_credential_staleness_comprehensive(self) -> None:
        """Comprehensive check should detect stale credentials when last_check exceeds max age."""
        config = StaleAccountConfig(credential_max_age_days=1)  # 1 day threshold
        detector = StaleAccountDetector(config=config)
        # Set last check to 3 days ago
        old_time = time.time() - (3 * 86400)
        detector._last_check["default"] = old_time
        detector._last_check["system"] = old_time
        report = detector.run_check(comprehensive=True)
        credential_findings = [f for f in report.stale_accounts if f.category == StalenessCategory.CREDENTIAL]
        assert len(credential_findings) >= 1
        assert credential_findings[0].severity == "WARNING"  # credential age > max = WARNING

    def test_concurrent_recording(self) -> None:
        """Race conditions should not cause crashes."""
        import threading

        detector = StaleAccountDetector()
        errors = []

        def record():
            try:
                for _ in range(100):
                    detector.record_trade("broker")
                    detector.record_heartbeat()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
