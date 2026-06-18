"""
Smoke tests for core.audit_mode - Independent Audit Mode.

Verifies:
- Module imports correctly
- CLI runs without errors
- Full audit report has expected structure
- Individual audit scopes work
"""

from __future__ import annotations

import os
import subprocess
import sys


def _import_audit_mode():
    """Import core.audit_mode with clean module state."""
    for mod in list(sys.modules.keys()):
        if "audit_mode" in mod:
            del sys.modules[mod]
    import core.audit_mode as m
    return m


class TestAuditModeImports:
    """Verify module imports correctly."""

    def test_import(self):
        """Module imports without errors."""
        m = _import_audit_mode()
        assert m is not None
        assert hasattr(m, "Auditor")
        assert hasattr(m, "AuditReport")
        assert hasattr(m, "AuditScope")
        assert hasattr(m, "AuditSeverity")
        assert hasattr(m, "AuditVerdict")
        assert hasattr(m, "AuditFinding")
        assert hasattr(m, "get_auditor")
        assert hasattr(m, "run_audit")

    def test_enums(self):
        """Enum types have expected values."""
        m = _import_audit_mode()
        assert m.AuditScope.ARCHITECTURE.value == "architecture"
        assert m.AuditScope.RISK.value == "risk"
        assert m.AuditScope.STRATEGY.value == "strategy"
        assert m.AuditScope.EXECUTION.value == "execution"
        assert m.AuditScope.SCORING.value == "scoring"
        assert m.AuditScope.SECURITY.value == "security"
        assert m.AuditScope.ALL.value == "all"

        assert m.AuditSeverity.INFO.value == "INFO"
        assert m.AuditSeverity.WARNING.value == "WARNING"
        assert m.AuditSeverity.CRITICAL.value == "CRITICAL"
        assert m.AuditSeverity.BLOCKER.value == "BLOCKER"

        assert m.AuditVerdict.PASS.value == "PASS"
        assert m.AuditVerdict.WARN.value == "WARN"
        assert m.AuditVerdict.FAIL.value == "FAIL"
        assert m.AuditVerdict.CRITICAL.value == "CRITICAL"


class TestAuditReport:
    """Verify AuditReport dataclass."""

    def test_default_values(self):
        """Report initializes with defaults."""
        m = _import_audit_mode()
        r = m.AuditReport(scope=m.AuditScope.ALL)
        assert r.total_checks == 0
        assert r.passed == 0
        assert r.warnings == 0
        assert r.failures == 0
        assert r.criticals == 0
        assert r.score == 0.0
        assert r.verdict == ""

    def test_summary_contains_scope(self):
        """Summary includes scope name."""
        m = _import_audit_mode()
        r = m.AuditReport(scope=m.AuditScope.ALL, total_checks=5, passed=5,
                          score=10.0, verdict="PASS")
        s = r.summary()
        assert "ALL" in s or "all" in s
        assert "PASS" in s
        assert "5" in s

    def test_to_dict_contains_keys(self):
        """to_dict returns all expected keys."""
        m = _import_audit_mode()
        r = m.AuditReport(scope=m.AuditScope.RISK, total_checks=3, passed=3,
                          score=10.0, verdict="PASS")
        d = r.to_dict()
        assert d["scope"] == "risk"
        assert d["total_checks"] == 3
        assert d["passed"] == 3
        assert d["score"] == 10.0
        assert d["verdict"] == "PASS"
        assert "duration_seconds" in d
        assert "findings" in d


class TestAuditor:
    """Verify Auditor functionality."""

    def test_create_auditor(self):
        """Auditor can be created."""
        m = _import_audit_mode()
        a = m.Auditor()
        assert a is not None

    def test_full_audit_runs(self):
        """Full audit completes without error."""
        m = _import_audit_mode()
        a = m.Auditor()
        r = a.run_full_audit()
        assert r.scope == m.AuditScope.ALL
        assert r.total_checks >= 15  # 4 (arch) + 4 (risk) + 3 (strategy) + 3 (exec) + 2 (scoring) + 3 (security) = 19
        assert r.passed >= 15
        assert r.verdict != ""
        assert r.duration_seconds > 0

    def test_audit_architecture(self):
        """Architecture audit runs."""
        m = _import_audit_mode()
        a = m.Auditor()
        r = a.audit_architecture()
        assert r.scope == m.AuditScope.ARCHITECTURE
        assert r.total_checks >= 4
        assert r.passed >= 3

    def test_audit_risk_controls(self):
        """Risk controls audit runs."""
        m = _import_audit_mode()
        a = m.Auditor()
        r = a.audit_risk_controls()
        assert r.scope == m.AuditScope.RISK
        assert r.total_checks >= 4
        assert r.passed >= 3

    def test_audit_strategy(self):
        """Strategy audit runs."""
        m = _import_audit_mode()
        a = m.Auditor()
        r = a.audit_strategy()
        assert r.scope == m.AuditScope.STRATEGY
        assert r.total_checks >= 1

    def test_audit_execution(self):
        """Execution audit runs."""
        m = _import_audit_mode()
        a = m.Auditor()
        r = a.audit_execution()
        assert r.scope == m.AuditScope.EXECUTION
        assert r.total_checks >= 3

    def test_audit_scoring(self):
        """Scoring audit runs."""
        m = _import_audit_mode()
        a = m.Auditor()
        r = a.audit_scoring()
        assert r.scope == m.AuditScope.SCORING
        assert r.total_checks >= 1

    def test_audit_security(self):
        """Security audit runs."""
        m = _import_audit_mode()
        a = m.Auditor()
        r = a.audit_security()
        assert r.scope == m.AuditScope.SECURITY
        assert r.total_checks >= 3


class TestSingletonAndHelpers:
    """Verify module-level singleton and helper functions."""

    def test_get_auditor_singleton(self):
        """get_auditor returns same instance."""
        m = _import_audit_mode()
        a1 = m.get_auditor()
        a2 = m.get_auditor()
        assert a1 is a2

    def test_run_audit_default(self):
        """run_audit with no args runs full audit."""
        import core.audit_mode as m
        r = m.run_audit()
        assert r.scope == m.AuditScope.ALL

    def test_run_audit_scoped(self):
        """run_audit with scope runs that scope."""
        import core.audit_mode as m
        r = m.run_audit(scope="risk")
        assert r.scope == m.AuditScope.RISK

    def test_run_audit_invalid_scope_fallsback_to_all(self):
        """Invalid scope falls back to ALL."""
        import core.audit_mode as m
        r = m.run_audit(scope="nonexistent")
        assert r.scope == m.AuditScope.ALL

    def test_cli_runs(self):
        """CLI entry point runs without crashing (test via Python -m)."""
        result = subprocess.run(
            [sys.executable, "-m", "core.audit_mode", "--json"],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        print(f"CLI stdout: {result.stdout[:500]}")
        print(f"CLI stderr: {result.stderr[:500]}")
        assert result.returncode == 0 or result.returncode == 1
        assert '"score"' in result.stdout or '"verdict"' in result.stdout
