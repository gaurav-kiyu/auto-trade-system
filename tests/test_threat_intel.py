"""Tests for Threat Intelligence module (core/threat_intel.py)."""

from __future__ import annotations

import pytest
from core.threat_intel import CVEAlert, ThreatIntelReport, get_threat_intel, reset_threat_intel


@pytest.fixture(autouse=True)
def reset_intel():
    reset_threat_intel()
    intel = get_threat_intel()
    intel.clear_all()
    yield
    reset_threat_intel()


class TestScanDependencies:
    def test_scan_clean_deps(self, reset_intel):
        intel = get_threat_intel()
        report = intel.scan_dependencies({"requests": "2.31.0"})  # Latest, no CVE
        assert report.total_alerts == 0
        assert report.packages_scanned == 1

    def test_scan_vulnerable_dep(self, reset_intel):
        intel = get_threat_intel()
        report = intel.scan_dependencies({"requests": "2.28.0"})  # Old version
        assert report.total_alerts > 0
        assert any("CVE" in a.cve_id for a in report.alerts)

    def test_scan_multiple_deps(self, reset_intel):
        intel = get_threat_intel()
        report = intel.scan_dependencies({
            "requests": "2.28.0",
            "flask": "2.2.0",
            "pillow": "10.1.0",
        })
        assert report.total_alerts >= 2

    def test_scan_unknown_package(self, reset_intel):
        intel = get_threat_intel()
        report = intel.scan_dependencies({"unknown_package": "1.0.0"})
        assert report.total_alerts == 0

    def test_scan_risk_score_computed(self, reset_intel):
        intel = get_threat_intel()
        report = intel.scan_dependencies({"requests": "2.28.0"})
        assert report.avg_risk_score > 0

    def test_scan_critical_and_high_counted(self, reset_intel):
        intel = get_threat_intel()
        report = intel.scan_dependencies({"cryptography": "38.0.0"})
        # Should find at least one HIGH severity
        assert report.high_count >= 1


class TestScanRequirementsFile:
    def test_scan_missing_file(self, reset_intel):
        intel = get_threat_intel()
        report = intel.scan_requirements_file("nonexistent_file.txt")
        assert report.total_alerts == 0

    def test_scan_real_requirements(self, reset_intel):
        import os
        if os.path.exists("requirements.txt"):
            intel = get_threat_intel()
            report = intel.scan_requirements_file("requirements.txt")
            assert isinstance(report, ThreatIntelReport)
            assert report.packages_scanned >= 0


class TestGetAlerts:
    def test_get_alerts(self, reset_intel):
        intel = get_threat_intel()
        intel.scan_dependencies({"requests": "2.28.0"})
        alerts = intel.get_alerts()
        assert len(alerts) > 0

    def test_get_alerts_filtered_by_severity(self, reset_intel):
        intel = get_threat_intel()
        intel.scan_dependencies({"cryptography": "38.0.0"})
        high = intel.get_alerts(severity="HIGH")
        assert len(high) > 0
        assert all(a.severity == "HIGH" for a in high)

    def test_get_critical_alerts(self, reset_intel):
        intel = get_threat_intel()
        intel.scan_dependencies({"requests": "2.28.0"})
        critical = intel.get_critical_alerts()
        assert isinstance(critical, list)


class TestStats:
    def test_get_stats_empty(self, reset_intel):
        intel = get_threat_intel()
        stats = intel.get_stats()
        assert stats["total_alerts"] == 0

    def test_get_stats_after_scan(self, reset_intel):
        intel = get_threat_intel()
        intel.scan_dependencies({"requests": "2.28.0"})
        stats = intel.get_stats()
        assert stats["total_alerts"] > 0
        assert "by_severity" in stats
        assert stats["packages_in_db"] > 0


class TestAlertModel:
    def test_cve_alert_to_dict(self):
        alert = CVEAlert(cve_id="CVE-2023-0001", package="test", severity="HIGH",
                         cvss_score=7.5, known_exploit=True)
        d = alert.to_dict()
        assert d["cve_id"] == "CVE-2023-0001"
        assert d["severity"] == "HIGH"
        assert d["known_exploit"] is True

    def test_risk_score_critical_with_exploit(self):
        alert = CVEAlert(severity="CRITICAL", known_exploit=True)
        assert alert.risk_score >= 9.0

    def test_risk_score_info(self):
        alert = CVEAlert(severity="INFO", known_exploit=False)
        assert alert.risk_score == 0.0

    def test_report_to_dict(self):
        report = ThreatIntelReport(total_alerts=1, critical_count=1, packages_scanned=5)
        d = report.to_dict()
        assert d["total_alerts"] == 1
        assert d["critical"] == 1
        assert d["packages_scanned"] == 5


class TestSingleton:
    def test_singleton(self):
        i1 = get_threat_intel()
        i2 = get_threat_intel()
        assert i1 is i2

    def test_reset(self):
        i1 = get_threat_intel()
        reset_threat_intel()
        i2 = get_threat_intel()
        assert i1 is not i2
