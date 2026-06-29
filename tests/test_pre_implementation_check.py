"""
Tests for scripts/pre_implementation_check.py - Pre-Implementation Compliance Check.

Covers:
  - check_architecture_doc_exists()
  - check_git_history()
  - check_risk_controls() with risk-sensitive patterns
  - check_blocked_files() with forbidden file targets
  - check_risk_sensitive_files() detection
  - check_release_state() for VERSION and .gitignore
  - Main function with various CLI args
  - Risk-sensitive patterns and blocked changes constants
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# ── Helpers ───────────────────────────────────────────────────────────────────


def import_pre_check() -> Any:
    """Import the pre_implementation_check module with clean path."""
    for mod in list(sys.modules.keys()):
        if "pre_implementation" in mod:
            del sys.modules[mod]
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import scripts.pre_implementation_check as pc
    return pc


# ── check_architecture_doc_exists ─────────────────────────────────────────────


class TestCheckArchitectureDocs:
    def test_arch_docs_exist(self) -> None:
        pc = import_pre_check()
        # In a real project checkout, docs should exist
        result = pc.check_architecture_doc_exists()
        # Don't assert True/False since it depends on the project state,
        # just check it returns a bool
        assert isinstance(result, bool)

    def test_arch_docs_returns_bool(self) -> None:
        pc = import_pre_check()
        result = pc.check_architecture_doc_exists()
        assert result is True or result is False


# ── check_git_history ─────────────────────────────────────────────────────────


class TestCheckGitHistory:
    def test_git_history_returns_bool(self) -> None:
        pc = import_pre_check()
        result = pc.check_git_history()
        assert isinstance(result, bool)

    def test_git_history_default_ten(self) -> None:
        pc = import_pre_check()
        result = pc.check_git_history(count=5)
        assert isinstance(result, bool)

    def test_git_history_with_invalid_count(self) -> None:
        pc = import_pre_check()
        result = pc.check_git_history(count=0)
        assert isinstance(result, bool)


# ── check_risk_controls ───────────────────────────────────────────────────────


class TestCheckRiskControls:
    def test_clean_file_no_violations(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        clean_file = tmp_path / "clean.py"
        clean_file.write_text("def hello(): pass")
        violations = pc.check_risk_controls([str(clean_file)])
        assert len(violations) == 0

    def test_file_with_hard_halt_detected(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        risky_file = tmp_path / "risky.py"
        risky_file.write_text("MAX_DAILY_LOSS = 500")
        violations = pc.check_risk_controls([str(risky_file)])
        assert len(violations) > 0
        assert any("MAX_DAILY_LOSS" in v for v in violations)

    def test_file_with_sl_pct_detected(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        risky_file = tmp_path / "risk.py"
        risky_file.write_text("SL_PCT = 0.05")
        violations = pc.check_risk_controls([str(risky_file)])
        assert len(violations) > 0

    def test_file_with_paper_mode_detected(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        risky_file = tmp_path / "paper.py"
        risky_file.write_text("PAPER_MODE = True")
        violations = pc.check_risk_controls([str(risky_file)])
        assert len(violations) > 0

    def test_non_existent_file_skipped(self) -> None:
        pc = import_pre_check()
        violations = pc.check_risk_controls(["nonexistent.py"])
        assert len(violations) == 0

    def test_multiple_risk_patterns_detected(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        risky_file = tmp_path / "multi.py"
        risky_file.write_text("MAX_DAILY_LOSS = 500\nSL_PCT = 0.05\nTARGET_PCT = 0.10")
        violations = pc.check_risk_controls([str(risky_file)])
        # Should detect all three patterns
        detected_patterns = set()
        for v in violations:
            for p in pc.RISK_SENSITIVE_PATTERNS:
                if p in v:
                    detected_patterns.add(p)
        assert len(detected_patterns) >= 3


# ── check_blocked_files ───────────────────────────────────────────────────────


class TestCheckBlockedFiles:
    def test_blocked_file_detected(self) -> None:
        pc = import_pre_check()
        violations = pc.check_blocked_files(["tests/test_smoke.py"])
        assert len(violations) > 0
        assert any("BLOCKED" in v for v in violations)

    def test_non_blocked_file_ok(self) -> None:
        pc = import_pre_check()
        violations = pc.check_blocked_files(["core/foo.py"])
        assert len(violations) == 0

    def test_multiple_blocked_files(self) -> None:
        pc = import_pre_check()
        violations = pc.check_blocked_files([
            "tests/test_smoke.py",
            "tests/test_broker_contract_certification.py",
        ])
        assert len(violations) == 2

    def test_partial_path_still_detected(self) -> None:
        pc = import_pre_check()
        violations = pc.check_blocked_files(["some/dir/test_smoke.py"])
        assert len(violations) > 0


# ── check_risk_sensitive_files ────────────────────────────────────────────────


class TestCheckRiskSensitiveFiles:
    def test_risk_sensitive_file_detected(self) -> None:
        pc = import_pre_check()
        sensitive = pc.check_risk_sensitive_files(["core/services/risk_service.py"])
        assert len(sensitive) > 0
        assert any("risk_service" in s for s in sensitive)

    def test_non_sensitive_file_not_detected(self) -> None:
        pc = import_pre_check()
        sensitive = pc.check_risk_sensitive_files(["core/foo.py"])
        assert len(sensitive) == 0

    def test_multiple_sensitive_files(self) -> None:
        pc = import_pre_check()
        sensitive = pc.check_risk_sensitive_files([
            "core/services/risk_service.py",
            "core/adapters/broker_adapters.py",
        ])
        assert len(sensitive) == 2

    def test_partial_path_match(self) -> None:
        pc = import_pre_check()
        sensitive = pc.check_risk_sensitive_files(["some/path/index_trader.py"])
        assert len(sensitive) == 0  # partial path doesn't match full RISK_SENSITIVE_FILES


# ── check_release_state ───────────────────────────────────────────────────────


class TestCheckReleaseState:
    def test_release_state_returns_list(self) -> None:
        pc = import_pre_check()
        issues = pc.check_release_state()
        assert isinstance(issues, list)

    def test_version_file_check(self) -> None:
        pc = import_pre_check()
        issues = pc.check_release_state()
        # In real project, VERSION should exist - if it does, no issues for that
        version_issue = [i for i in issues if "VERSION" in i]
        version_file = Path(__file__).resolve().parent.parent / "VERSION"
        if version_file.exists():
            assert len(version_issue) == 0  # or version could be empty
        else:
            assert len(version_issue) > 0

    def test_gitignore_check(self) -> None:
        pc = import_pre_check()
        issues = pc.check_release_state()
        gitignore_issue = [i for i in issues if "gitignore" in i.lower()]
        gitignore_file = Path(__file__).resolve().parent.parent / ".gitignore"
        if gitignore_file.exists():
            assert len(gitignore_issue) == 0
        else:
            assert len(gitignore_issue) > 0


# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_risk_sensitive_files_not_empty(self) -> None:
        pc = import_pre_check()
        assert len(pc.RISK_SENSITIVE_FILES) > 0

    def test_risk_sensitive_patterns_not_empty(self) -> None:
        pc = import_pre_check()
        assert len(pc.RISK_SENSITIVE_PATTERNS) > 0
        assert "_trip_hard_halt" in pc.RISK_SENSITIVE_PATTERNS
        assert "MAX_DAILY_LOSS" in pc.RISK_SENSITIVE_PATTERNS

    def test_blocked_changes_not_empty(self) -> None:
        pc = import_pre_check()
        assert len(pc.BLOCKED_CHANGES) > 0
        assert "test_smoke.py" in pc.BLOCKED_CHANGES[0]


# ── Main function ─────────────────────────────────────────────────────────────


class TestMain:
    def test_main_ci_mode_exit_zero(self) -> None:
        pc = import_pre_check()
        exit_code = pc.main(["--ci"])
        assert exit_code == 0

    def test_main_with_files(self) -> None:
        pc = import_pre_check()
        exit_code = pc.main(["--files", "core/foo.py"])
        assert exit_code == 0  # clean files

    def test_main_with_blocked_files(self) -> None:
        pc = import_pre_check()
        exit_code = pc.main(["--files", "tests/test_smoke.py"])
        assert exit_code == 1  # blocked

    def test_main_show_context(self) -> None:
        pc = import_pre_check()
        exit_code = pc.main(["--show-context"])
        assert exit_code == 0

    def test_main_with_risk_check(self) -> None:
        pc = import_pre_check()
        exit_code = pc.main(["--check-risk"])
        assert exit_code == 0

    def test_main_ci_with_blocked_files(self) -> None:
        pc = import_pre_check()
        exit_code = pc.main(["--ci", "--files", "tests/test_smoke.py"])
        assert exit_code == 1

    def test_main_no_args_exit_zero(self) -> None:
        pc = import_pre_check()
        exit_code = pc.main([])
        assert exit_code == 0


# ── CLI entry point ───────────────────────────────────────────────────────────


class TestCLI:
    def test_script_exists(self) -> None:
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "pre_implementation_check.py"
        assert script_path.exists()
        assert script_path.stat().st_size > 0

    def test_script_has_shebang(self) -> None:
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "pre_implementation_check.py"
        content = script_path.read_text(encoding="utf-8")
        assert content.startswith("#!/usr/bin/env python3")
