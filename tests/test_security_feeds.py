"""Tests for core/integrations/security_feeds.py — Security Feed Reporter.

Covers:
- SecurityFeedReporter.run_feeds() with available sources
- Graceful degradation when sources are missing
- Error handling during feed collection
- Singleton reporter instance
- wire_security_feeds() function
- Edge cases (no sources, empty results)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.integrations.security_feeds import (
    SecurityFeedReporter,
    get_security_feed_reporter,
    wire_security_feeds,
)


class TestSecurityFeedReporter:
    """Tests for SecurityFeedReporter class."""

    def test_run_feeds_with_both_sources(self):
        """Both threat intel and vuln scanner should be called."""
        reporter = SecurityFeedReporter()

        with patch("core.threat_intel.get_threat_intel") as mock_get_intel:
            with patch("core.vulnerability_scanner.get_vulnerability_scanner") as mock_get_scanner:
                # Mock threat intel
                mock_intel = MagicMock()
                mock_report = MagicMock()
                mock_report.total_alerts = 5
                mock_report.critical_count = 1
                mock_report.high_count = 2
                mock_report.known_exploits = ["CVE-2024-0001"]
                mock_intel.scan_requirements_file.return_value = mock_report
                mock_get_intel.return_value = mock_intel

                # Mock vulnerability scanner
                mock_scanner = MagicMock()
                mock_scan = MagicMock()
                mock_scan.total_findings = 3
                mock_scan.critical_count = 0
                mock_scan.high_count = 1
                mock_scan.risk_score = 42.5
                mock_scan.pass_threshold = True
                mock_scanner.run_full_scan.return_value = mock_scan
                mock_get_scanner.return_value = mock_scanner

                results = reporter.run_feeds()

                assert results["total_findings"] == 8  # 5 + 3
                assert results["critical_findings"] == 1
                assert results["high_findings"] == 3  # 2 + 1
                assert results["threat_intel"]["alerts"] == 5
                assert results["vulnerability_scanner"]["findings"] == 3
                assert "threat_intel" in results["sources"]
                assert "vulnerability_scanner" in results["sources"]

    def test_run_feeds_threat_intel_fails(self):
        """When threat intel fails, vuln scanner should still run."""
        reporter = SecurityFeedReporter()

        with patch("core.threat_intel.get_threat_intel") as mock_get_intel:
            with patch("core.vulnerability_scanner.get_vulnerability_scanner") as mock_get_scanner:
                mock_get_intel.side_effect = ImportError("No threat intel")

                mock_scanner = MagicMock()
                mock_scan = MagicMock()
                mock_scan.total_findings = 2
                mock_scan.critical_count = 0
                mock_scan.high_count = 0
                mock_scan.risk_score = 10.0
                mock_scan.pass_threshold = True
                mock_scanner.run_full_scan.return_value = mock_scan
                mock_get_scanner.return_value = mock_scanner

                results = reporter.run_feeds()

                assert results["total_findings"] == 2
                assert "error" in results["threat_intel"]
                assert results["vulnerability_scanner"]["findings"] == 2

    def test_run_feeds_both_fail(self):
        """When both sources fail, results should contain error entries."""
        reporter = SecurityFeedReporter()

        with patch("core.threat_intel.get_threat_intel") as mock_get_intel:
            with patch("core.vulnerability_scanner.get_vulnerability_scanner") as mock_get_scanner:
                mock_get_intel.side_effect = Exception("Intel down")
                mock_get_scanner.side_effect = Exception("Scanner down")

                results = reporter.run_feeds()

                assert results["total_findings"] == 0
                assert results["critical_findings"] == 0
                assert "error" in results["threat_intel"]
                assert "error" in results["vulnerability_scanner"]

    def test_stats_tracking(self):
        """Stats should track last feed time and count."""
        reporter = SecurityFeedReporter()

        with patch("core.threat_intel.get_threat_intel") as mock_get_intel:
            with patch("core.vulnerability_scanner.get_vulnerability_scanner") as mock_get_scanner:
                mock_get_intel.side_effect = Exception("N/A")
                mock_get_scanner.side_effect = Exception("N/A")

                reporter.run_feeds()
                reporter.run_feeds()

                stats = reporter.get_stats()
                assert stats["feed_count"] == 2
                assert stats["last_feed_time"] > 0


class TestGetSecurityFeedReporter:
    """Tests for singleton reporter access."""

    def test_singleton(self):
        """get_security_feed_reporter should return the same instance."""
        r1 = get_security_feed_reporter()
        r2 = get_security_feed_reporter()
        assert r1 is r2

    def test_reporter_is_instance(self):
        """Returned object should be SecurityFeedReporter."""
        reporter = get_security_feed_reporter()
        assert isinstance(reporter, SecurityFeedReporter)


class TestWireSecurityFeeds:
    """Tests for wire_security_feeds function."""

    def test_wire_success(self):
        """Wiring should return True."""
        result = wire_security_feeds()
        assert result is True

    def test_wire_creates_reporter(self):
        """Wiring should create the singleton reporter."""
        # Reset the module state by getting a fresh reference
        from core.integrations import security_feeds as sf_module
        # Clear any cached reporter
        with patch.object(sf_module, "_reporter", None):
            result = wire_security_feeds()
            assert result is True

    def test_exception_during_wire(self):
        """Exception during wiring should return False."""
        with patch("core.integrations.security_feeds.get_security_feed_reporter") as mock_get:
            mock_get.side_effect = RuntimeError("Init failed")
            result = wire_security_feeds()
            assert result is False


class TestSecurityFeedReporterEdgeCases:
    """Tests for edge cases."""

    def test_empty_results_structure(self):
        """Results dict should have all expected keys."""
        reporter = SecurityFeedReporter()
        with patch("core.threat_intel.get_threat_intel") as mock_get_intel:
            with patch("core.vulnerability_scanner.get_vulnerability_scanner") as mock_get_scanner:
                mock_get_intel.side_effect = Exception("N/A")
                mock_get_scanner.side_effect = Exception("N/A")

                results = reporter.run_feeds()

                assert "timestamp" in results
                assert "sources" in results
                assert results["sources"] == []  # No sources succeeded
                assert "threat_intel" in results
                assert "vulnerability_scanner" in results

    def test_consecutive_calls(self):
        """Multiple consecutive calls should not leak state."""
        reporter = SecurityFeedReporter()

        with patch("core.threat_intel.get_threat_intel") as mock_get_intel:
            with patch("core.vulnerability_scanner.get_vulnerability_scanner") as mock_get_scanner:
                # First call setup - both fail
                mock_intel_ok = MagicMock()
                mock_report_ok = MagicMock()
                mock_report_ok.total_alerts = 3
                mock_report_ok.critical_count = 0
                mock_report_ok.high_count = 1
                mock_intel_ok.scan_requirements_file.return_value = mock_report_ok

                mock_scanner_ok = MagicMock()
                mock_scan_ok = MagicMock()
                mock_scan_ok.total_findings = 2
                mock_scan_ok.critical_count = 0
                mock_scan_ok.high_count = 0
                mock_scan_ok.risk_score = 15.0
                mock_scan_ok.pass_threshold = True
                mock_scanner_ok.run_full_scan.return_value = mock_scan_ok

                mock_get_intel.side_effect = [Exception("down"), mock_intel_ok]
                mock_get_scanner.side_effect = [Exception("down"), mock_scanner_ok]

                # First call - both fail
                r1 = reporter.run_feeds()
                assert r1["total_findings"] == 0

                # Second call - both succeed
                r2 = reporter.run_feeds()
                assert r2["total_findings"] == 5  # 3 + 2
