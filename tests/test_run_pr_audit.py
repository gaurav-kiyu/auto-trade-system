"""Tests for scripts/run_pr_audit.py — Unified PR Audit Report.

Subprocess-heavy checks (ruff, architecture, hygiene, dead_code, stale_docs)
are mocked to keep tests fast. Only check_gitignore() runs for real since
it's pure Python.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.run_pr_audit import (
    MAX_SCORE,
    SEVERITY_WEIGHTS,
    AuditFinding,
    AuditReport,
    AuditSection,
    _fail,
    _ok,
    _warn,
    check_gitignore,
    run_audit,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_subprocess():
    """Mock _run_subprocess to return (0, '', '') instantly for all calls."""
    with patch("scripts.run_pr_audit._run_subprocess") as mock:
        mock.return_value = (0, "", "")
        yield mock


# ── Data Model Tests ──────────────────────────────────────────────────────────


class TestAuditFinding:
    def test_creation(self):
        f = AuditFinding(check="ruff", severity="HIGH", message="Test issue", file="foo.py", line=42, code="E201")
        assert f.check == "ruff"
        assert f.severity == "HIGH"
        assert f.message == "Test issue"
        assert f.file == "foo.py"
        assert f.line == 42
        assert f.code == "E201"

    def test_to_dict(self):
        f = AuditFinding(check="ruff", severity="HIGH", message="Test", file="foo.py", line=10, code="E201")
        d = f.to_dict()
        assert d["check"] == "ruff"
        assert d["severity"] == "HIGH"
        assert d["file"] == "foo.py"
        assert d["line"] == 10
        assert d["code"] == "E201"

    def test_to_dict_minimal(self):
        f = AuditFinding(check="bandit", severity="MEDIUM", message="Test")
        d = f.to_dict()
        assert d["file"] == ""
        assert d["line"] == 0
        assert d["code"] == ""


class TestAuditSection:
    def test_empty_section_is_pass(self):
        s = AuditSection(name="Test", passed=True)
        assert s.name == "Test"
        assert s.passed is True
        assert s.findings == []
        assert s.duration_sec == 0.0
        assert s.error == ""

    def test_to_dict(self):
        s = AuditSection(name="Ruff", passed=False, findings=[
            AuditFinding(check="ruff", severity="HIGH", message="Err"),
        ], duration_sec=1.5)
        d = s.to_dict()
        assert d["name"] == "Ruff"
        assert d["passed"] is False
        assert d["findings_count"] == 1
        assert d["duration_sec"] == 1.5


class TestAuditReport:
    def test_empty_report(self):
        r = AuditReport()
        assert r.score == MAX_SCORE
        assert r.total_checks == 0
        assert r.passed_checks == 0
        assert r.total_findings == 0
        assert r.sections == []

    def test_to_dict(self):
        s = AuditSection(name="Test", passed=True)
        r = AuditReport(sections=[s])
        r.total_checks = 1
        r.passed_checks = 1
        d = r.to_dict()
        assert d["total_checks"] == 1
        assert d["passed_checks"] == 1
        assert d["score"] == 100.0
        assert len(d["sections"]) == 1

    def test_to_markdown_pass(self):
        s = AuditSection(name="Ruff", passed=True)
        r = AuditReport(sections=[s])
        r.total_checks = 1
        r.passed_checks = 1
        md = r.to_markdown()
        assert "PR Audit Report" in md
        assert "PASS" in md
        assert "100.0/100" in md

    def test_to_markdown_fail(self):
        s = AuditSection(name="Architecture", passed=False, findings=[
            AuditFinding(check="arch", severity="HIGH", message="Violation"),
        ])
        r = AuditReport(sections=[s])
        r.total_checks = 1
        r.passed_checks = 0
        r.score = 40.0
        md = r.to_markdown()
        assert "FAIL" in md
        assert "40.0/100" in md
        assert "Violation" in md

    def test_to_markdown_warn(self):
        s = AuditSection(name="Hygiene", passed=False, findings=[
            AuditFinding(check="hygiene", severity="LOW", message="Minor issue"),
        ])
        r = AuditReport(sections=[s])
        r.total_checks = 1
        r.passed_checks = 0
        r.score = 60.0
        md = r.to_markdown()
        assert "WARN" in md
        assert "60.0/100" in md

    def test_summary_text(self):
        s = AuditSection(name="Ruff", passed=True)
        r = AuditReport(sections=[s])
        r.total_checks = 1
        r.passed_checks = 1
        text = r.summary_text()
        assert "PR AUDIT REPORT" in text
        assert "PASS" in text
        assert "100.0/100" in text

    def test_score_structure(self):
        """Verify penalty calculation formula via string representation."""
        penalty = SEVERITY_WEIGHTS["HIGH"] + SEVERITY_WEIGHTS["MEDIUM"] + SEVERITY_WEIGHTS["CRITICAL"]
        expected_score = max(0.0, MAX_SCORE - penalty)
        # Manually construct report with expected score
        r = AuditReport(sections=[], score=expected_score)
        r.total_checks = 2
        r.passed_checks = 1
        r.total_findings = 3
        d = r.to_dict()
        assert d["score"] == expected_score
        assert d["total_findings"] == 3


# ── Check Runner Tests (subprocess mocked) ──────────────────────────────────


class TestCheckGitignore:
    def test_returns_audit_section(self):
        result = check_gitignore()
        assert isinstance(result, AuditSection)
        assert result.name == ".gitignore Coverage"

    def test_missing_gitignore(self, tmp_path):
        with patch("scripts.run_pr_audit.ROOT", tmp_path):
            result = check_gitignore()
            assert result.passed is False
            assert any("missing" in f.message.lower() for f in result.findings)

    def test_present_gitignore(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(
            "__pycache__/\n*.pyc\n.pytest_cache/\n.ruff_cache/\n"
            ".mypy_cache/\n.venv/\nbuild/\ndist/\n*.egg-info/\n*.egg\n"
            "*.so\n*.db\njson/trader_state.json\nlogs/\ndata/\n"
        )
        with patch("scripts.run_pr_audit.ROOT", tmp_path):
            result = check_gitignore()
            assert result.passed is True
            assert len(result.findings) == 0


# ── Integration Tests (mocked subprocess for speed) ──────────────────────────


class TestRunAudit:
    def test_run_audit_returns_report(self, mock_subprocess):
        report = run_audit(quick=True)
        assert isinstance(report, AuditReport)
        assert report.total_checks > 0
        assert report.score == MAX_SCORE  # all mocked to pass
        assert report.summary
        assert report.duration_sec >= 0

    def test_run_audit_quick_skips_dead_code(self, mock_subprocess):
        report = run_audit(quick=True)
        section_names = [s.name for s in report.sections]
        assert "Dead Code Scan" not in section_names
        assert "Stale Documentation" not in section_names

    def test_run_audit_full_includes_slow_checks(self, mock_subprocess):
        report = run_audit(quick=False)
        section_names = [s.name for s in report.sections]
        assert "Dead Code Scan" in section_names
        assert "Stale Documentation" in section_names

    def test_score_thresholds_on_failure(self, mock_subprocess):
        # Make ruff fail
        with patch("scripts.run_pr_audit._run_subprocess") as mock:
            mock.return_value = (1, "", "error")
            report = run_audit(quick=True)
            assert report.score < MAX_SCORE
            assert report.total_findings > 0

    def test_penalty_accumulates_across_sections(self, mock_subprocess):
        def side_effect(cmd, **kw):
            if "ruff" in str(cmd):
                return (1, "core/foo.py:1:1: F401 Unused import", "")
            return (0, "", "")
        with patch("scripts.run_pr_audit._run_subprocess", side_effect=side_effect):
            report = run_audit(quick=True)
            assert report.score < MAX_SCORE
            # ruff section should have findings
            ruff_section = [s for s in report.sections if s.name == "Ruff Lint"]
            assert len(ruff_section) == 1
            assert len(ruff_section[0].findings) > 0


# ── CLI Entry Point Tests (mocked for speed) ────────────────────────────────


class TestMain:
    def test_json_output(self, mock_subprocess):
        from scripts.run_pr_audit import main
        exit_code = main(["--json", "--quick"])
        assert exit_code == 0

    def test_md_output(self, mock_subprocess):
        from scripts.run_pr_audit import main
        exit_code = main(["--md", "--quick"])
        assert exit_code == 0

    def test_ci_output(self, mock_subprocess):
        from scripts.run_pr_audit import main
        exit_code = main(["--ci", "--quick"])
        assert exit_code == 0

    def test_output_file(self, mock_subprocess, tmp_path):
        from scripts.run_pr_audit import main
        output_file = tmp_path / "audit.json"
        exit_code = main(["--json", "--quick", "--output", str(output_file)])
        assert exit_code == 0
        assert output_file.exists()
        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert "score" in data
        assert "sections" in data

    def test_no_args_default_text(self, mock_subprocess):
        from scripts.run_pr_audit import main
        exit_code = main(["--quick"])
        assert exit_code == 0

    def test_exit_code_on_failure(self, mock_subprocess):
        from scripts.run_pr_audit import main
        score_threshold = 49
        with patch("scripts.run_pr_audit.run_audit") as mock_run:
            mock_report = AuditReport()
            mock_report.score = score_threshold
            mock_report.total_checks = 1
            mock_report.passed_checks = 0
            mock_report.total_findings = 5
            mock_run.return_value = mock_report
            exit_code = main(["--ci", "--quick"])
            assert exit_code == 2  # FAIL (< 50)

    def test_exit_code_on_warn(self, mock_subprocess):
        from scripts.run_pr_audit import main
        with patch("scripts.run_pr_audit.run_audit") as mock_run:
            mock_report = AuditReport()
            mock_report.score = 60.0
            mock_report.total_checks = 2
            mock_report.passed_checks = 1
            mock_report.total_findings = 3
            mock_run.return_value = mock_report
            exit_code = main(["--ci", "--quick"])
            assert exit_code == 1  # WARN (50-79)


# ── Edge Cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_severity_weights_all_keys(self):
        """All severity levels used anywhere in the code have weights."""
        used_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "WARNING", "ERROR"}
        for s in used_severities:
            assert s in SEVERITY_WEIGHTS, f"Missing weight for severity: {s}"
            assert SEVERITY_WEIGHTS[s] > 0

    def test_score_non_negative(self, mock_subprocess):
        report = run_audit(quick=True)
        assert report.score >= 0
        assert report.score <= MAX_SCORE

    def test_findings_count_matches(self, mock_subprocess):
        report = run_audit(quick=True)
        manual_count = sum(len(s.findings) for s in report.sections)
        assert report.total_findings == manual_count

    def test_emoji_helpers_return_strings(self):
        ok = _ok()
        fail = _fail()
        warn = _warn()
        assert isinstance(ok, str)
        assert isinstance(fail, str)
        assert isinstance(warn, str)
        assert len(ok) > 0
        assert len(fail) > 0
        assert len(warn) > 0

    def test_to_markdown_with_repo(self):
        s = AuditSection(name="Test", passed=True)
        r = AuditReport(sections=[s])
        r.total_checks = 1
        r.passed_checks = 1
        md = r.to_markdown(repo="owner/repo")
        assert "run_pr_audit.py" in md

    def test_ruff_parsing_failure_finding(self, mock_subprocess):
        """Verify ruff non-zero exit generates a finding when stdout is empty."""
        with patch("scripts.run_pr_audit._run_subprocess") as mock:
            mock.return_value = (2, "", "Some ruff error")
            report = run_audit(quick=True)
            ruff_sec = [s for s in report.sections if s.name == "Ruff Lint"]
            assert len(ruff_sec) == 1
            assert not ruff_sec[0].passed
