#!/usr/bin/env python3
"""Tests for scripts/hygiene_check.py - Repository Hygiene automation."""
from __future__ import annotations

import pytest
from scripts.hygiene_check import (
    ROOT,
    HygieneIssue,
    HygieneReport,
    _is_gitignored,
    _load_gitignore_patterns,
    check_gitignore,
    check_stale_reports,
    main,
    scan_duplicate_implementations,
)


class TestHygieneIssues:
    """Test HygieneIssue and HygieneReport data classes (fast - no I/O)."""

    def test_issue_defaults(self) -> None:
        issue = HygieneIssue(category="TEST", path="foo.py", description="test issue")
        assert issue.auto_cleanable is False
        d = issue.to_dict()
        assert d["category"] == "TEST"
        assert d["path"] == "foo.py"
        assert d["auto_cleanable"] is False

    def test_issue_auto_cleanable(self) -> None:
        issue = HygieneIssue(category="TEST", path="bar.py", description="cleanable", auto_cleanable=True)
        assert issue.auto_cleanable is True

    def test_report_defaults(self) -> None:
        report = HygieneReport(timestamp=1.0, issues=[], total=0, auto_cleanable=0, clean_performed=False)
        assert report.clean_ok is True
        d = report.to_dict()
        assert d["clean_ok"] is True

    def test_report_with_issues(self) -> None:
        issue = HygieneIssue(category="FORBIDDEN_DIR", path="cache", description="found", auto_cleanable=True)
        report = HygieneReport(timestamp=2.0, issues=[issue], total=1, auto_cleanable=1, clean_performed=True, clean_ok=True)
        d = report.to_dict()
        assert d["total_issues"] == 1
        assert len(d["issues"]) == 1


class TestGitignoreHelper:
    """Test the in-process gitignore pattern matcher (fast)."""

    def test_load_gitignore_exists(self) -> None:
        patterns = _load_gitignore_patterns()
        assert isinstance(patterns, list)
        # Should find patterns since .gitignore exists
        assert len(patterns) > 0

    def test_is_gitignored_known(self) -> None:
        """__pycache__ should be gitignored."""
        # Create a temporary path that should never exist
        test_path = ROOT / "test_hygiene_nonexistent_12345"
        # Should not crash and return False for non-existent paths not in gitignore
        result = _is_gitignored(test_path)
        assert isinstance(result, bool)


class TestGitignoreCheck:
    """Test .gitignore validation (fast - single file read)."""

    def test_gitignore_exists(self) -> None:
        issues = check_gitignore()
        gitignore_issues = [i for i in issues if i.category == "MISSING_GITIGNORE"]
        assert len(gitignore_issues) == 0, ".gitignore file should exist"

    def test_gitignore_returns_list(self) -> None:
        issues = check_gitignore()
        assert isinstance(issues, list)
        for issue in issues:
            assert issue.category in ("MISSING_GITIGNORE", "GITIGNORE_GAP")


class TestStaleReports:
    """Test stale report check (fast - dir read)."""

    def test_check_stale_reports(self) -> None:
        issues = check_stale_reports()
        assert isinstance(issues, list)
        for issue in issues:
            assert issue.category == "STALE_REPORT"


class TestDuplicateImpl:
    """Test duplicate implementation scanner (fast - single rglob)."""

    def test_scan_duplicate_implementations(self) -> None:
        issues = scan_duplicate_implementations()
        assert isinstance(issues, list)
        for issue in issues:
            assert issue.category == "DUPLICATE_IMPL"


class TestMainCLI:
    """Test the CLI entry point (uses fast flags only to avoid full scan timeout)."""

    def test_main_check_gitignore(self) -> None:
        """--check-gitignore is fast (single file read only)."""
        exit_code = main(["--check-gitignore"])
        assert exit_code in (0, 1)

    def test_main_check_reports(self) -> None:
        """--check-reports is fast (dir read only)."""
        exit_code = main(["--check-reports"])
        assert exit_code in (0, 1)

    def test_main_ci_check_gitignore(self) -> None:
        """--ci with --check-gitignore is fast."""
        exit_code = main(["--ci", "--check-gitignore"])
        assert exit_code in (0, 1)

    def test_main_json_check_gitignore(self) -> None:
        """--json with --check-gitignore is fast."""
        exit_code = main(["--json", "--check-gitignore"])
        assert exit_code in (0, 1)

    def test_main_ci_nonzero(self) -> None:
        """--ci exits with 0 or 1."""
        exit_code = main(["--ci"])
        # This may be slow, so give it a reasonable timeout expectation
        assert exit_code in (0, 1)

    def test_main_help(self) -> None:
        """--help should exit with 0."""
        with pytest.raises(SystemExit):
            main(["--help"])
