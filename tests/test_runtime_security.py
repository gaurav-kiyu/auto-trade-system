"""Tests for Runtime Security module."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.runtime_security import (
    FileIntegrityCheck,
    RuntimeFinding,
    RuntimeSecurityReport,
    get_runtime_security,
    reset_runtime_security,
)


@pytest.fixture(autouse=True)
def reset_sec():
    reset_runtime_security()
    p = Path("json/runtime_security.json")
    if p.exists():
        p.unlink()
    yield
    reset_runtime_security()


class TestFileIntegrity:
    def test_verify_existing_file(self):
        sec = get_runtime_security()
        check = sec.verify_file("core/runtime_security.py")
        assert check is not None
        assert check.file_path == "core/runtime_security.py"
        assert len(check.checksum) > 0
        assert check.size_bytes > 0

    def test_verify_nonexistent_file(self):
        sec = get_runtime_security()
        check = sec.verify_file("nonexistent.py")
        assert check is not None
        assert "not found" in " ".join(check.issues).lower() or len(check.issues) > 0

    def test_file_integrity_baseline(self):
        sec = get_runtime_security()
        sec.verify_file("core/runtime_security.py")
        check2 = sec.verify_file("core/runtime_security.py")
        # Same file, same run → should not show as modified
        assert check2.modified is False

    def test_file_integrity_to_dict(self):
        check = FileIntegrityCheck(file_path="test.py", checksum="abc123", size_bytes=100)
        d = check.to_dict()
        assert d["file_path"] == "test.py"
        assert d["size_bytes"] == 100


class TestRuntimeCheck:
    def test_run_full_check(self):
        sec = get_runtime_security()
        report = sec.run_full_check()
        assert isinstance(report, RuntimeSecurityReport)
        assert report.critical_files_verified > 0
        assert 0.0 <= report.score <= 10.0
        assert report.overall_risk in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    def test_full_check_findings(self):
        sec = get_runtime_security()
        report = sec.run_full_check()
        if report.findings:
            assert all(f.category for f in report.findings)
            assert all(f.severity for f in report.findings)

    def test_full_check_recommendations(self):
        sec = get_runtime_security()
        report = sec.run_full_check()
        assert len(report.recommendations) >= 0

    def test_get_stats(self):
        sec = get_runtime_security()
        sec.run_full_check()
        stats = sec.get_stats()
        assert stats["total_checks"] == 1
        assert stats["files_baselined"] > 0
        assert 0.0 <= stats["last_score"] <= 10.0

    def test_get_stats_initial(self):
        sec = get_runtime_security()
        stats = sec.get_stats()
        assert stats["total_checks"] == 0
        assert stats["last_score"] == 10.0

    def test_clear_baseline(self):
        sec = get_runtime_security()
        sec.run_full_check()
        assert sec.get_stats()["files_baselined"] > 0
        sec.clear_baseline()
        assert sec.get_stats()["files_baselined"] == 0

    def test_report_summary_text(self):
        sec = get_runtime_security()
        report = sec.run_full_check()
        text = report.summary_text()
        assert "RUNTIME SECURITY" in text


class TestRuntimeModels:
    def test_finding_to_dict(self):
        f = RuntimeFinding(category="FILE_INTEGRITY", severity="HIGH", description="test")
        d = f.to_dict()
        assert d["category"] == "FILE_INTEGRITY"
        assert d["severity"] == "HIGH"

    def test_report_to_dict(self):
        r = RuntimeSecurityReport(score=8.5, overall_risk="LOW")
        d = r.to_dict()
        assert d["score"] == 8.5
        assert d["overall_risk"] == "LOW"

    def test_report_summary(self):
        r = RuntimeSecurityReport(score=7.5, overall_risk="MEDIUM", critical_files_verified=10)
        text = r.summary_text()
        assert "7.5" in text
        assert "MEDIUM" in text
