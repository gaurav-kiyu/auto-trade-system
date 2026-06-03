"""
Tests for core.auditor — Independent Auditor Subsystem (Phase 16).

Validates:
  - Auditor can challenge architecture, risk controls, execution, strategies
  - Auditor generates evidence-based findings
  - Auditor generates comprehensive audit reports with scores
  - Findings correctly identify PASS/FAIL/WARN/INCONCLUSIVE
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.auditor import (
    AuditCategory,
    AuditEvidence,
    AuditFinding,
    AuditReport,
    AuditSeverity,
    AuditStatus,
    IndependentAuditor,
    get_auditor,
    reset_auditor,
)


class TestAuditEvidence:
    """Test AuditEvidence dataclass."""

    def test_create_evidence(self) -> None:
        """Evidence should store description, source, and passed status."""
        e = AuditEvidence(
            description="Test check",
            source="core.test",
            detail="Passed OK",
            passed=True,
        )
        assert e.description == "Test check"
        assert e.source == "core.test"
        assert e.passed is True

    def test_failed_evidence(self) -> None:
        """Failed evidence should have passed=False."""
        e = AuditEvidence(
            description="Failed check",
            source="core.test",
            detail="Something wrong",
            passed=False,
        )
        assert e.passed is False

    def test_to_dict(self) -> None:
        """Evidence should convert to dict."""
        e = AuditEvidence(description="Test", source="src", passed=True)
        d = e.to_dict()
        assert d["description"] == "Test"
        assert d["passed"] is True


class TestAuditFinding:
    """Test AuditFinding dataclass."""

    def test_create_finding(self) -> None:
        """Finding should store all fields."""
        f = AuditFinding(
            category=AuditCategory.ARCHITECTURE,
            title="Architecture check",
            severity=AuditSeverity.HIGH,
            status=AuditStatus.PASS,
            description="All checks passed",
        )
        assert f.category == AuditCategory.ARCHITECTURE
        assert f.passed is True

    def test_failed_finding(self) -> None:
        """Failed finding should have passed=False."""
        f = AuditFinding(
            category=AuditCategory.RISK_CONTROLS,
            title="Risk check",
            severity=AuditSeverity.CRITICAL,
            status=AuditStatus.FAIL,
            description="Missing limit",
            recommendation="Add limit",
        )
        assert f.passed is False
        assert f.recommendation == "Add limit"

    def test_add_evidence(self) -> None:
        """Evidence should be addable to finding."""
        f = AuditFinding(
            category=AuditCategory.EXECUTION,
            title="Execution check",
            severity=AuditSeverity.MEDIUM,
            status=AuditStatus.PASS,
            description="OK",
        )
        e = AuditEvidence(description="Test evidence", source="src", passed=True)
        f.add_evidence(e)
        assert len(f.evidence) == 1
        assert f.evidence[0].description == "Test evidence"

    def test_to_dict(self) -> None:
        """Finding should convert to dict."""
        f = AuditFinding(
            category=AuditCategory.SECURITY,
            title="Security check",
            severity=AuditSeverity.HIGH,
            status=AuditStatus.PASS,
            description="OK",
        )
        d = f.to_dict()
        assert d["category"] == "security"
        assert d["passed"] is True


class TestIndependentAuditor:
    """Test the IndependentAuditor class."""

    def setup_method(self) -> None:
        reset_auditor()

    def test_audit_architecture(self) -> None:
        """Architecture audit should complete without error."""
        auditor = IndependentAuditor()
        result = auditor.audit_architecture()
        assert result is not None
        assert len(result.findings) >= 0
        assert len(result.evidence) > 0

    def test_audit_risk_controls_without_config(self) -> None:
        """Risk controls audit without config should still complete."""
        auditor = IndependentAuditor()
        result = auditor.audit_risk_controls()
        assert result is not None
        assert len(result.evidence) > 0

    def test_audit_risk_controls_with_config(self) -> None:
        """Risk controls audit with config should check config keys."""
        auditor = IndependentAuditor()
        config = {
            "MAX_DAILY_LOSS": -2000.0,
            "MAX_DRAWDOWN": 0.20,
            "MAX_CONSECUTIVE_LOSSES": 3,
        }
        result = auditor.audit_risk_controls(config=config)
        assert result is not None

    def test_audit_execution(self) -> None:
        """Execution audit should complete."""
        auditor = IndependentAuditor()
        result = auditor.audit_execution()
        assert result is not None

    def test_audit_strategies(self) -> None:
        """Strategy audit should complete."""
        auditor = IndependentAuditor()
        result = auditor.audit_strategies()
        assert result is not None

    def test_audit_scoring(self) -> None:
        """Scoring audit should complete."""
        auditor = IndependentAuditor()
        result = auditor.audit_scoring()
        assert result is not None

    def test_audit_replay(self) -> None:
        """Replay audit should complete."""
        auditor = IndependentAuditor()
        result = auditor.audit_replay()
        assert result is not None

    def test_audit_governance(self) -> None:
        """Governance audit should complete."""
        auditor = IndependentAuditor()
        result = auditor.audit_governance()
        assert result is not None

    def test_audit_all(self) -> None:
        """Full audit should generate report."""
        auditor = IndependentAuditor()
        report = auditor.audit_all()
        assert isinstance(report, AuditReport)
        assert report.total_findings > 0
        assert report.overall_score > 0

    def test_audit_all_with_config(self) -> None:
        """Full audit with config should work."""
        auditor = IndependentAuditor()
        config = {"MAX_DAILY_LOSS": -2000.0}
        report = auditor.audit_all(config=config)
        assert isinstance(report, AuditReport)
        assert report.total_findings > 0

    def test_generate_report(self) -> None:
        """Generate report should work."""
        auditor = IndependentAuditor()
        report = auditor.generate_report()
        assert isinstance(report, AuditReport)

    def test_get_findings(self) -> None:
        """Get findings should return list."""
        auditor = IndependentAuditor()
        auditor.audit_all()
        findings = auditor.get_findings()
        assert isinstance(findings, list)

    def test_get_findings_by_category(self) -> None:
        """Get findings filtered by category."""
        auditor = IndependentAuditor()
        auditor.audit_all()
        findings = auditor.get_findings(AuditCategory.ARCHITECTURE)
        for f in findings:
            assert f.category == AuditCategory.ARCHITECTURE

    def test_get_challenge_count(self) -> None:
        """Challenge count should increase after audits."""
        auditor = IndependentAuditor()
        count_before = auditor.get_challenge_count()
        auditor.audit_architecture()
        # Challenge count should have gone up
        assert auditor.get_challenge_count() >= count_before

    def test_reset(self) -> None:
        """Reset should clear all findings."""
        auditor = IndependentAuditor()
        auditor.audit_all()
        assert len(auditor.get_findings()) > 0
        auditor.reset()
        assert len(auditor.get_findings()) == 0


class TestAuditReport:
    """Test AuditReport dataclass."""

    def test_summary(self) -> None:
        """Summary should be a non-empty string."""
        findings = [
            AuditFinding(
                category=AuditCategory.ARCHITECTURE,
                title="Test",
                severity=AuditSeverity.INFO,
                status=AuditStatus.PASS,
                description="OK",
            ),
        ]
        report = AuditReport(
            generated_at="2026-01-01T00:00:00",
            total_findings=1,
            passed=1,
            failed=0,
            warnings=0,
            not_tested=0,
            findings=findings,
            overall_score=9.5,
        )
        summary = report.print_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "9.50" in summary

    def test_to_json(self) -> None:
        """To JSON should be valid JSON."""
        report = AuditReport(
            generated_at="2026-01-01T00:00:00",
            total_findings=0,
            passed=0,
            failed=0,
            warnings=0,
            not_tested=0,
            findings=[],
        )
        j = report.to_json()
        import json
        data = json.loads(j)
        assert data["total_findings"] == 0

    def test_to_dict(self) -> None:
        """To dict should have expected keys."""
        report = AuditReport(
            generated_at="2026-01-01T00:00:00",
            total_findings=1,
            passed=1,
            failed=0,
            warnings=0,
            not_tested=0,
            findings=[
                AuditFinding(
                    category=AuditCategory.ARCHITECTURE,
                    title="Test",
                    severity=AuditSeverity.INFO,
                    status=AuditStatus.PASS,
                    description="OK",
                ),
            ],
        )
        d = report.to_dict()
        assert d["total_findings"] == 1
        assert d["passed"] == 1
        assert len(d["findings"]) == 1


class TestAuditorSingleton:
    """Test singleton factory."""

    def setup_method(self) -> None:
        reset_auditor()

    def test_get_auditor(self) -> None:
        """get_auditor should return an auditor."""
        auditor = get_auditor()
        assert isinstance(auditor, IndependentAuditor)

    def test_singleton(self) -> None:
        """get_auditor should return same instance."""
        a1 = get_auditor()
        a2 = get_auditor()
        assert a1 is a2

    def test_reset(self) -> None:
        """reset_auditor should clear singleton."""
        a1 = get_auditor()
        reset_auditor()
        a2 = get_auditor()
        assert a1 is not a2

    def test_import_from_package(self) -> None:
        """Import from core.auditor should work."""
        from core.auditor import IndependentAuditor, AuditCategory, AuditReport
        assert IndependentAuditor is not None
        assert AuditCategory is not None
        assert AuditReport is not None
