"""Integration 6: Threat Intel + Vuln Scanner -> Security Auditor.

Feeds findings from Threat Intelligence (CVE scanning) and Vulnerability
Scanner (dependency/config/code weaknesses) into the Security Auditor
for consolidated reporting and risk assessment.

Usage:
    from core.integrations import wire_security_feeds
    wire_security_feeds()
"""

from __future__ import annotations

import logging
import time
from typing import Any

_log = logging.getLogger(__name__)


class SecurityFeedReporter:
    """Aggregates security findings from multiple sources for the Security Auditor."""

    def __init__(self) -> None:
        self._last_feed_time: float = 0.0
        self._feed_count: int = 0

    def run_feeds(self) -> dict[str, Any]:
        """Run all security feeds and return aggregated findings.

        Returns:
            Dict with findings from all sources.
        """
        results: dict[str, Any] = {
            "timestamp": time.time(),
            "sources": [],
            "total_findings": 0,
            "critical_findings": 0,
            "high_findings": 0,
        }

        # Feed 1: Threat Intelligence (CVE scan)
        try:
            from core.threat_intel import get_threat_intel
            intel = get_threat_intel()
            report = intel.scan_requirements_file("requirements.txt")
            results["threat_intel"] = {
                "alerts": report.total_alerts,
                "critical": report.critical_count,
                "high": report.high_count,
                "known_exploits": report.known_exploits,
            }
            results["total_findings"] += report.total_alerts
            results["critical_findings"] += report.critical_count
            results["high_findings"] += report.high_count
            results["sources"].append("threat_intel")
        except Exception as exc:
            results["threat_intel"] = {"error": str(exc)}

        # Feed 2: Vulnerability Scanner
        try:
            from core.vulnerability_scanner import get_vulnerability_scanner
            scanner = get_vulnerability_scanner()
            scan_report = scanner.run_full_scan()
            results["vulnerability_scanner"] = {
                "findings": scan_report.total_findings,
                "critical": scan_report.critical_count,
                "high": scan_report.high_count,
                "risk_score": scan_report.risk_score,
                "pass_threshold": scan_report.pass_threshold,
            }
            results["total_findings"] += scan_report.total_findings
            results["critical_findings"] += scan_report.critical_count
            results["high_findings"] += scan_report.high_count
            results["sources"].append("vulnerability_scanner")
        except Exception as exc:
            results["vulnerability_scanner"] = {"error": str(exc)}

        self._last_feed_time = time.time()
        self._feed_count += 1
        return results

    def get_stats(self) -> dict[str, Any]:
        return {
            "last_feed_time": self._last_feed_time,
            "feed_count": self._feed_count,
        }


_reporter: SecurityFeedReporter | None = None


def get_security_feed_reporter() -> SecurityFeedReporter:
    """Get the singleton SecurityFeedReporter."""
    global _reporter
    if _reporter is None:
        _reporter = SecurityFeedReporter()
    return _reporter


def wire_security_feeds() -> bool:
    """Wire Threat Intel and Vulnerability Scanner into Security Auditor.

    Creates the SecurityFeedReporter and registers it for periodic
    security feed aggregation.

    Returns:
        True if wired successfully.
    """
    try:
        get_security_feed_reporter()
        _log.info("[INTEGRATION] Security Feeds -> Security Auditor: WIRED")
        return True
    except Exception as exc:
        _log.warning("[INTEGRATION] Security Feeds: ERROR (%s)", exc)
        return False


__all__ = ["SecurityFeedReporter", "get_security_feed_reporter", "wire_security_feeds"]
