"""
Tests for audit_mode — Independent Audit Mode for system integrity challenges.

Covers:
- AuditSeverity, AuditScope, AuditVerdict enums
- AuditFinding, AuditReport dataclasses
- Auditor: run_full_audit, individual scope audits (architecture, risk, strategy, execution, scoring, security)
- Singleton factory (get_auditor, run_audit)
- Report summary and dict serialization
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.audit_mode import (
    AuditFinding,
    AuditReport,
    AuditScope,
    AuditSeverity,
    AuditVerdict,
    Auditor,
    get_auditor,
    run_audit,
)


# ── Enums ──────────────────────────────────────────────────────────────────


class TestAuditSeverity:
    def test_values(self):
        assert AuditSeverity.INFO.value == "INFO"
        assert AuditSeverity.WARNING.value == "WARNING"
        assert AuditSeverity.CRITICAL.value == "CRITICAL"
        assert AuditSeverity.BLOCKER.value == "BLOCKER"

    def test_all_severities_present(self):
        expected = {"INFO", "WARNING", "CRITICAL", "BLOCKER"}
        actual = {e.value for e in AuditSeverity}
        assert actual == expected


class TestAuditScope:
    def test_values(self):
        assert AuditScope.ARCHITECTURE.value == "architecture"
        assert AuditScope.ALL.value == "all"

    def test_all_scopes_present(self):
        expected = {"architecture", "risk", "strategy", "execution", "scoring", "security", "all"}
        actual = {e.value for e in AuditScope}
        assert actual == expected


class TestAuditVerdict:
    def test_values(self):
        assert AuditVerdict.PASS.value == "PASS"
        assert AuditVerdict.FAIL.value == "FAIL"
        assert AuditVerdict.CRITICAL.value == "CRITICAL"


# ── AuditFinding Dataclass ────────────────────────────────────────────────


class TestAuditFinding:
    def test_creation(self):
        finding = AuditFinding(
            scope=AuditScope.RISK,
            severity=AuditSeverity.INFO,
            title="Hard Halt Non-Bypassable",
            description="Hard halt cannot be bypassed",
            evidence="core/safety_state.py",
            recommendation="Verify no bypass path",
        )
        assert finding.scope == AuditScope.RISK
        assert finding.title == "Hard Halt Non-Bypassable"
        assert finding.passed is False

    def test_passed_flag(self):
        finding = AuditFinding(
            scope=AuditScope.SECURITY,
            severity=AuditSeverity.INFO,
            title="CSRF Active",
            description="CSRF protection active",
            evidence="core/auth/csrf.py",
            recommendation="Verify on all routes",
            passed=True,
        )
        assert finding.passed is True

    def test_default_passed_false(self):
        finding = AuditFinding(
            scope=AuditScope.ARCHITECTURE,
            severity=AuditSeverity.WARNING,
            title="Test",
            description="Test",
            evidence="test",
            recommendation="fix",
        )
        assert finding.passed is False


# ── AuditReport Dataclass ────────────────────────────────────────────────


class TestAuditReport:
    def test_creation(self):
        report = AuditReport(scope=AuditScope.ALL)
        assert report.scope == AuditScope.ALL
        assert report.total_checks == 0
        assert report.verdict == ""

    def test_summary_contains_key_info(self):
        report = AuditReport(
            scope=AuditScope.RISK,
            total_checks=5,
            passed=4,
            warnings=1,
            failures=0,
            criticals=0,
            score=8.0,
            verdict="WARN",
        )
        summary = report.summary()
        assert "risk" in summary
        assert "5" in summary
        assert "4" in summary
        assert "8.0" in summary
        assert "WARN" in summary

    def test_to_dict_structure(self):
        finding = AuditFinding(
            scope=AuditScope.RISK,
            severity=AuditSeverity.INFO,
            title="Test Finding",
            description="Description",
            evidence="evidence.py",
            recommendation="Fix it",
            passed=True,
        )
        report = AuditReport(
            scope=AuditScope.RISK,
            total_checks=1,
            passed=1,
            warnings=0,
            failures=0,
            criticals=0,
            findings=[finding],
            score=10.0,
            verdict="PASS",
            duration_seconds=0.5,
        )
        d = report.to_dict()
        assert d["scope"] == "risk"
        assert d["total_checks"] == 1
        assert d["score"] == 10.0
        assert d["verdict"] == "PASS"
        assert len(d["findings"]) == 1
        assert d["findings"][0]["title"] == "Test Finding"
        assert d["findings"][0]["passed"] is True

    def test_empty_findings_summary(self):
        report = AuditReport(scope=AuditScope.ALL, total_checks=0, verdict="PASS", score=10.0)
        summary = report.summary()
        assert "0 checks" in summary or "Checks: 0" in summary


# ── Auditor — Architecture ────────────────────────────────────────────────


class TestAuditArchitecture:
    @pytest.fixture
    def auditor(self) -> Auditor:
        return Auditor()

    def test_audit_architecture_returns_report(self, auditor: Auditor):
        report = auditor.audit_architecture()
        assert isinstance(report, AuditReport)
        assert report.scope == AuditScope.ARCHITECTURE
        assert report.total_checks >= 3

    def test_architecture_findings_have_evidence(self, auditor: Auditor):
        report = auditor.audit_architecture()
        for finding in report.findings:
            assert finding.evidence, f"Finding '{finding.title}' missing evidence"
            assert finding.recommendation, f"Finding '{finding.title}' missing recommendation"


# ── Auditor — Risk Controls ────────────────────────────────────────────────


class TestAuditRisk:
    @pytest.fixture
    def auditor(self) -> Auditor:
        return Auditor()

    def test_audit_risk_returns_report(self, auditor: Auditor):
        report = auditor.audit_risk_controls()
        assert isinstance(report, AuditReport)
        assert report.scope == AuditScope.RISK

    def test_risk_findings_cover_key_areas(self, auditor: Auditor):
        report = auditor.audit_risk_controls()
        titles = [f.title for f in report.findings]
        assert any("Hard Halt" in t for t in titles)
        assert any("Daily Loss" in t or "MAX_DAILY_LOSS" in t for t in titles)
        assert any("Position" in t for t in titles)


# ── Auditor — Strategy ────────────────────────────────────────────────────


class TestAuditStrategy:
    @pytest.fixture
    def auditor(self) -> Auditor:
        return Auditor()

    def test_audit_strategy_returns_report(self, auditor: Auditor):
        report = auditor.audit_strategy()
        assert isinstance(report, AuditReport)
        assert report.scope == AuditScope.STRATEGY


# ── Auditor — Execution ──────────────────────────────────────────────────


class TestAuditExecution:
    @pytest.fixture
    def auditor(self) -> Auditor:
        return Auditor()

    def test_audit_execution_returns_report(self, auditor: Auditor):
        report = auditor.audit_execution()
        assert isinstance(report, AuditReport)
        assert report.scope == AuditScope.EXECUTION


# ── Auditor — Scoring ────────────────────────────────────────────────────


class TestAuditScoring:
    @pytest.fixture
    def auditor(self) -> Auditor:
        return Auditor()

    def test_audit_scoring_returns_report(self, auditor: Auditor):
        report = auditor.audit_scoring()
        assert isinstance(report, AuditReport)
        assert report.scope == AuditScope.SCORING


# ── Auditor — Security ────────────────────────────────────────────────────


class TestAuditSecurity:
    @pytest.fixture
    def auditor(self) -> Auditor:
        return Auditor()

    def test_audit_security_returns_report(self, auditor: Auditor):
        report = auditor.audit_security()
        assert isinstance(report, AuditReport)
        assert report.scope == AuditScope.SECURITY
        assert report.total_checks >= 2


# ── Auditor — Full Audit ──────────────────────────────────────────────────


class TestFullAudit:
    @pytest.fixture
    def auditor(self) -> Auditor:
        return Auditor()

    def test_full_audit_returns_combined_report(self, auditor: Auditor):
        report = auditor.run_full_audit()
        assert isinstance(report, AuditReport)
        assert report.scope == AuditScope.ALL
        assert report.total_checks >= 10  # all scopes combined
        assert report.passed >= 0

    def test_full_audit_aggregates_multi_scope(self, auditor: Auditor):
        report = auditor.run_full_audit()
        # Total should be sum of individual scopes
        arch = auditor.audit_architecture()
        risk = auditor.audit_risk_controls()
        expected_min = arch.total_checks + risk.total_checks
        assert report.total_checks >= expected_min

    def test_full_audit_duration_positive(self, auditor: Auditor):
        report = auditor.run_full_audit()
        assert report.duration_seconds > 0

    def test_full_audit_all_findings_have_scope(self, auditor: Auditor):
        report = auditor.run_full_audit()
        for f in report.findings:
            assert isinstance(f.scope, AuditScope)

    def test_full_audit_verdict_is_string(self, auditor: Auditor):
        report = auditor.run_full_audit()
        assert isinstance(report.verdict, str)
        assert report.verdict in ("PASS", "WARN", "FAIL", "CRITICAL - Blocking production release",
                                  "FAIL - Issues must be resolved before production",
                                  "WARN - Non-blocking issues identified",
                                  "PASS - All checks clear")


# ── Singleton Factory ──────────────────────────────────────────────────────


class TestSingleton:
    def test_get_auditor_returns_instance(self):
        auditor = get_auditor()
        assert isinstance(auditor, Auditor)

    def test_get_auditor_singleton(self):
        a1 = get_auditor()
        a2 = get_auditor()
        assert a1 is a2

    def test_run_audit_all_returns_report(self):
        report = run_audit("all")
        assert isinstance(report, AuditReport)
        assert report.scope == AuditScope.ALL

    def test_run_audit_risk_scope(self):
        report = run_audit("risk")
        assert isinstance(report, AuditReport)
        assert report.scope == AuditScope.RISK

    def test_run_audit_invalid_scope_defaults_all(self):
        """Invalid scope name defaults to 'all'."""
        report = run_audit("invalid_scope")
        assert isinstance(report, AuditReport)
        assert report.scope == AuditScope.ALL


# ── CLI Integration ────────────────────────────────────────────────────────


class TestCli:
    def test_module_runnable(self):
        """Check the module can be invoked as __main__."""
        import runpy
        with patch("sys.argv", ["core.audit_mode", "--scope", "risk", "--json"]):
            with patch("builtins.print") as mock_print:
                try:
                    runpy.run_module("core.audit_mode", run_name="__main__")
                except SystemExit:
                    pass
                # Verify print was called (JSON output)
                assert mock_print.called
