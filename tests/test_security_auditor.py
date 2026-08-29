"""Tests for core/security_auditor.py — Security Auditor module."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest
from core.security_auditor import (
    DependencyVuln,
    InsecureImport,
    SecretFinding,
    SecurityAuditor,
    SecurityReport,
    get_security_auditor,
    reset_security_auditor,
)


class TestSecurityAuditorInit:
    """Tests for SecurityAuditor initialization and singleton."""

    def setup_method(self) -> None:
        reset_security_auditor()

    def test_singleton(self) -> None:
        a1 = get_security_auditor()
        a2 = get_security_auditor()
        assert a1 is a2

    def test_reset(self) -> None:
        a1 = get_security_auditor()
        reset_security_auditor()
        a2 = get_security_auditor()
        assert a1 is not a2

    def test_initial_state(self) -> None:
        auditor = get_security_auditor()
        assert auditor.last_scan is None
        stats = auditor.get_stats()
        assert stats["total_scans"] == 0


class TestSecretFinding:
    """Tests for SecretFinding data class."""

    def test_to_dict(self) -> None:
        finding = SecretFinding(
            file_path="core/foo.py",
            line_number=42,
            pattern_name="API Key",
            severity="HIGH",
            snippet='key = "sk-abc123"',
            line_content='api_key = "sk-abc123"',
        )
        d = finding.to_dict()
        assert d["file_path"] == "core/foo.py"
        assert d["line_number"] == 42
        assert d["pattern_name"] == "API Key"
        assert d["line_content"] == 'api_key = "sk-abc123"'


class TestInsecureImport:
    """Tests for InsecureImport data class."""

    def test_to_dict(self) -> None:
        imp = InsecureImport(
            file_path="core/bar.py",
            line_number=10,
            pattern_name="eval usage",
            severity="CRITICAL",
            line_content="eval(user_input)",
        )
        d = imp.to_dict()
        assert d["pattern_name"] == "eval usage"
        assert d["severity"] == "CRITICAL"


class TestDependencyVuln:
    """Tests for DependencyVuln data class."""

    def test_to_dict(self) -> None:
        vuln = DependencyVuln(
            package_name="requests",
            installed_version="2.31.0",
            affected_versions="<2.32.0",
            description="CVE-2024-35195 (moderate)",
            severity="MEDIUM",
            fix_version="2.32.0",
        )
        d = vuln.to_dict()
        assert d["package_name"] == "requests"
        assert d["severity"] == "MEDIUM"


class TestSecurityReport:
    """Tests for SecurityReport data class."""

    def test_to_dict(self) -> None:
        report = SecurityReport(timestamp=1000.0, total_files_scanned=50)
        report.secrets_found.append(SecretFinding(file_path="x.py"))
        report.insecure_imports.append(InsecureImport(file_path="y.py"))
        report.dependency_vulns.append(DependencyVuln(package_name="pkg"))
        d = report.to_dict()
        assert d["total_files_scanned"] == 50
        assert d["secrets_count"] == 1
        assert d["insecure_imports_count"] == 1
        assert d["dependency_vulns_count"] == 1
        assert d["score"] == 10.0

    def test_summary_text(self) -> None:
        report = SecurityReport(timestamp=1000.0)
        summary = report.summary_text()
        assert "SECURITY AUDIT REPORT" in summary
        assert "Score: 10.0" in summary

    def test_empty_report(self) -> None:
        report = SecurityReport()
        d = report.to_dict()
        assert d["secrets_count"] == 0
        assert d["insecure_imports_count"] == 0

    def test_summary_with_findings(self) -> None:
        report = SecurityReport(timestamp=2000.0)
        report.secrets_found.append(SecretFinding(
            file_path="core/secret.py", line_number=5, pattern_name="API Key", severity="CRITICAL"
        ))
        report.insecure_imports.append(InsecureImport(
            file_path="core/danger.py", line_number=10, pattern_name="eval usage", severity="HIGH"
        ))
        report.dependency_vulns.append(DependencyVuln(
            package_name="urllib3", installed_version="1.26.18", severity="MEDIUM"
        ))
        summary = report.summary_text()
        assert "Secrets/Credentials: 1" in summary
        assert "Insecure Imports" in summary
        assert "Dependency Vulns" in summary


class TestSecurityAuditor:
    """Tests for the SecurityAuditor class."""

    def setup_method(self) -> None:
        reset_security_auditor()

    def test_scan_initialized(self) -> None:
        auditor = get_security_auditor()
        assert auditor is not None

    def test_compute_score_clean(self) -> None:
        report = SecurityReport(timestamp=1000.0)
        score = SecurityAuditor()
        result = score._compute_score(report)
        assert result == 10.0

    def test_compute_score_with_findings(self) -> None:
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.secrets_found.append(SecretFinding(severity="CRITICAL"))
        report.secrets_found.append(SecretFinding(severity="HIGH"))
        report.insecure_imports.append(InsecureImport(severity="CRITICAL"))
        score = auditor._compute_score(report)
        # 10 - 1.5 - 1.0 - 2.0 = 5.5
        assert score == 5.5

    def test_compute_risk_low(self) -> None:
        auditor = SecurityAuditor()
        assert auditor._compute_risk(9.0) == "LOW"

    def test_compute_risk_medium(self) -> None:
        auditor = SecurityAuditor()
        assert auditor._compute_risk(7.0) == "MEDIUM"

    def test_compute_risk_high(self) -> None:
        auditor = SecurityAuditor()
        assert auditor._compute_risk(5.0) == "HIGH"

    def test_compute_risk_critical(self) -> None:
        auditor = SecurityAuditor()
        assert auditor._compute_risk(3.0) == "CRITICAL"

    def test_generate_recommendations_clean(self) -> None:
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        recs = auditor._generate_recommendations(report)
        assert len(recs) > 0
        assert any("No critical security issues" in r for r in recs)

    def test_generate_recommendations_with_secrets(self) -> None:
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.secrets_found.append(SecretFinding(severity="CRITICAL"))
        report.secrets_found.append(SecretFinding(severity="HIGH"))
        recs = auditor._generate_recommendations(report)
        assert any("hardcoded" in r.lower() for r in recs)

    def test_generate_recommendations_with_imports(self) -> None:
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.insecure_imports.append(InsecureImport(pattern_name="eval usage", severity="CRITICAL"))
        report.insecure_imports.append(InsecureImport(pattern_name="subprocess shell", severity="HIGH"))
        recs = auditor._generate_recommendations(report)
        assert any("eval" in r.lower() for r in recs)
        assert any("shell" in r.lower() for r in recs)

    def test_generate_recommendations_with_vulns(self) -> None:
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.dependency_vulns.append(DependencyVuln(
            package_name="requests", fix_version="2.32.0"
        ))
        recs = auditor._generate_recommendations(report)
        assert any("requests" in r for r in recs)

    def test_get_stats_after_scan(self) -> None:
        auditor = SecurityAuditor()
        # Simulate a scan
        report = SecurityReport(timestamp=2000.0)
        report.score = 9.0
        report.secrets_found.append(SecretFinding(file_path="test.py", severity="LOW"))
        report.insecure_imports.append(InsecureImport(file_path="test.py", severity="LOW"))
        auditor._scan_history.append(report)
        auditor._last_scan = report
        auditor._total_scans = 1

        stats = auditor.get_stats()
        assert stats["total_scans"] == 1
        assert stats["last_scan_score"] == 9.0
        assert stats["total_secrets_found"] == 1


class TestSecretDetectionPatterns:
    """Test that the secret detection patterns work."""

    def test_api_key_pattern(self) -> None:
        import re
        pattern = r"(?i)(api[_-]?key|apikey|api_key)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
        assert re.search(pattern, 'api_key = "abcdef1234567890abcd"')
        assert re.search(pattern, 'APIKEY="abcdef1234567890abcd"')
        assert not re.search(pattern, 'api_key = "short"')

    def test_eval_pattern(self) -> None:
        import re
        pattern = r"eval\("
        assert re.search(pattern, "eval(user_input)")
        assert not re.search(pattern, "eval_metric = 42")

    def test_shell_pattern(self) -> None:
        import re
        assert re.search(r"shell=True", "subprocess.run(cmd, shell=True)")
        assert not re.search(r"shell=True", "shellfish = True")


class TestSummaryEdgeCases:
    """Tests for SecurityReport summary_text edge cases."""

    def test_summary_with_recommendations(self) -> None:
        """summary_text includes recommendations section when set."""
        report = SecurityReport(
            timestamp=1000.0,
            recommendations=["Replace eval() calls", "Update urllib3"],
        )
        text = report.summary_text()
        assert "Recommendations" in text
        assert "Replace eval()" in text
        assert "Update urllib3" in text

    def test_summary_with_no_findings(self) -> None:
        """summary_text works with empty report."""
        report = SecurityReport(timestamp=1000.0)
        text = report.summary_text()
        assert "SECURITY AUDIT REPORT" in text
        assert "Score: 10.0" in text
        assert "Recommendations" not in text

    def test_compute_score_low_severity_secret(self) -> None:
        """LOW/MEDIUM severity secret deducts 0.5 (else branch)."""
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.secrets_found.append(SecretFinding(severity="LOW"))
        score = auditor._compute_score(report)
        assert score == 9.5

    def test_compute_score_low_severity_import(self) -> None:
        """LOW severity import deducts 0.2 (else branch)."""
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.insecure_imports.append(InsecureImport(severity="LOW"))
        score = auditor._compute_score(report)
        assert score == 9.8


class TestCoverageGaps:

    """Targeted tests for remaining uncovered code paths in SecurityAuditor."""

    def test_last_scan_property(self) -> None:
        """last_scan returns None before any scan, then the report after."""
        reset_security_auditor()
        auditor = SecurityAuditor()
        assert auditor.last_scan is None
        report = SecurityReport(timestamp=1000.0)
        auditor._last_scan = report
        assert auditor.last_scan is report
        assert auditor.last_scan.timestamp == 1000.0

    def test_get_stats_no_scans(self) -> None:
        """get_stats returns defaults when no scan has run."""
        reset_security_auditor()
        auditor = SecurityAuditor()
        stats = auditor.get_stats()
        assert stats["total_scans"] == 0
        assert stats["last_scan_risk"] == "UNKNOWN"
        assert stats["last_scan_score"] == 0
        assert stats["total_secrets_found"] == 0

    def test_compute_score_medium_severity(self) -> None:
        """MEDIUM severity deducts appropriately."""
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.insecure_imports.append(InsecureImport(severity="MEDIUM"))
        score = auditor._compute_score(report)
        assert score == 9.5  # 10 - 0.5 = 9.5

    def test_compute_score_low_severity(self) -> None:
        """LOW severity deducts 0.2."""
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.insecure_imports.append(InsecureImport(severity="LOW"))
        score = auditor._compute_score(report)
        assert score == 9.8

    def test_compute_score_dependency_high(self) -> None:
        """Dependency vulns with HIGH severity deduct 1.0."""
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.dependency_vulns.append(DependencyVuln(severity="HIGH"))
        score = auditor._compute_score(report)
        assert score == 9.0  # 10 - 1.0 = 9.0

    def test_compute_score_dependency_low(self) -> None:
        """Dependency vulns with non-HIGH/CRITICAL deduct 0.5."""
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.dependency_vulns.append(DependencyVuln(severity="LOW"))
        score = auditor._compute_score(report)
        assert score == 9.5

    def test_compute_score_dependency_critical(self) -> None:
        """Dependency vulns with CRITICAL severity deduct 2.0."""
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.dependency_vulns.append(DependencyVuln(severity="CRITICAL"))
        score = auditor._compute_score(report)
        assert score == 8.0

    def test_compute_risk_boundary_low(self) -> None:
        """Score >= 8.0 returns LOW."""
        auditor = SecurityAuditor()
        assert auditor._compute_risk(8.0) == "LOW"
        assert auditor._compute_risk(8.1) == "LOW"

    def test_compute_risk_boundary_medium(self) -> None:
        """6.0 <= score < 8.0 returns MEDIUM."""
        auditor = SecurityAuditor()
        assert auditor._compute_risk(6.0) == "MEDIUM"
        assert auditor._compute_risk(7.9) == "MEDIUM"

    def test_compute_risk_boundary_high(self) -> None:
        """4.0 <= score < 6.0 returns HIGH."""
        auditor = SecurityAuditor()
        assert auditor._compute_risk(4.0) == "HIGH"
        assert auditor._compute_risk(5.9) == "HIGH"

    def test_generate_recommendations_pickle(self) -> None:
        """pickle findings generate pickle-specific recommendations."""
        auditor = SecurityAuditor()
        report = SecurityReport(timestamp=1000.0)
        report.insecure_imports.append(InsecureImport(pattern_name="pickle deserialize"))
        recs = auditor._generate_recommendations(report)
        assert any("pickle" in r.lower() for r in recs)

    def test_secret_detection_api_key_generic(self) -> None:
        """_scan_directory detects generic API keys in content (uses 'api_key' pattern).
        Creates test file inside project root so relative_to(ROOT) doesn't fail.
        """
        auditor = SecurityAuditor()
        tmp_root = Path(__file__).resolve().parent / "_tmp_sec_test"
        tmp_root.mkdir(parents=True, exist_ok=True)
        try:
            test_file = tmp_root / "test_config.py"
            test_file.write_text('api_key = "abcdef1234567890abcdef1234567890"\n')
            report = SecurityReport(timestamp=1000.0)
            auditor._scan_directory(tmp_root, report)
            assert len(report.secrets_found) > 0
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    def test_secret_detection_password(self) -> None:
        """_scan_directory detects hardcoded passwords.
        Creates test file inside project root so relative_to(ROOT) doesn't fail.
        """
        auditor = SecurityAuditor()
        tmp_root = Path(__file__).resolve().parent / "_tmp_sec_test"
        tmp_root.mkdir(parents=True, exist_ok=True)
        try:
            test_file = tmp_root / "test_pass.py"
            test_file.write_text('password = "SuperSecret123!"\n')
            report = SecurityReport(timestamp=1000.0)
            auditor._scan_directory(tmp_root, report)
            assert len(report.secrets_found) > 0
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    def test_private_key_detection(self) -> None:
        """Private key pattern matches BEGIN PRIVATE KEY header."""
        import re
        pattern = r"-----BEGIN\s+(RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
        assert re.search(pattern, "-----BEGIN RSA PRIVATE KEY-----")
        assert re.search(pattern, "-----BEGIN PRIVATE KEY-----")
        assert not re.search(pattern, "-----BEGIN CERTIFICATE-----")

    def test_summary_with_deps(self) -> None:
        """summary_text includes dependency vulns section when present."""
        report = SecurityReport(timestamp=1000.0)
        report.dependency_vulns.append(DependencyVuln(
            package_name="urllib3", installed_version="1.26.18",
            severity="MEDIUM", description="CVE-2024-37891"
        ))
        summary = report.summary_text()
        assert "Dependency Vulns" in summary
        assert "urllib3" in summary

    def test_persist_creates_file(self) -> None:
        """_persist creates a JSON file with scan history."""
        auditor = SecurityAuditor()
        original_path = auditor._persist_path
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir) / "test_sec_hist.json"
                auditor._persist_path = tmp
                auditor._scan_history.append(SecurityReport(timestamp=1000.0))
                auditor._persist()
                assert tmp.exists()
                data = json.loads(tmp.read_text(encoding="utf-8"))
                assert len(data) == 1
                assert data[0]["timestamp"] == 1000.0
        finally:
            auditor._persist_path = original_path

    @pytest.mark.slow
    def test_run_full_scan_real_codebase(self) -> None:
        """run_full_scan operates on real codebase (slow)."""
        reset_security_auditor()
        auditor = get_security_auditor()
        report = auditor.run_full_scan()
        assert isinstance(report, SecurityReport)
        assert report.total_files_scanned > 0
        assert report.score >= 0.0
        assert report.overall_risk in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
