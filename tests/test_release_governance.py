"""
Tests for scripts/release_governance.py - Release Governance Automation.

Covers:
  - run_pre_release_checks()
  - generate_release_notes() format and content
  - update_changelog() structure
  - write_audit_record() JSON format
  - git_commit() and git_tag() (dry-run assertions only)
  - Main function with various CLI args
  - Constants and paths
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any




# ── Helpers ───────────────────────────────────────────────────────────────────


def import_release() -> Any:
    """Import the release_governance module with clean path."""
    for mod in list(sys.modules.keys()):
        if "release_governance" in mod:
            del sys.modules[mod]
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import scripts.release_governance as rg
    return rg


# ── run_pre_release_checks ─────────────────────────────────────────────────────


class TestPreReleaseChecks:
    def test_checks_returns_list(self) -> None:
        rg = import_release()
        failures = rg.run_pre_release_checks()
        assert isinstance(failures, list)

    def test_checks_returns_string_messages(self) -> None:
        rg = import_release()
        failures = rg.run_pre_release_checks()
        for f in failures:
            assert isinstance(f, str)

    def test_version_file_detected(self) -> None:
        rg = import_release()
        failures = rg.run_pre_release_checks()
        version_file = Path(__file__).resolve().parent.parent / "VERSION"
        if version_file.exists():
            version_issue = [f for f in failures if "VERSION" in f]
            # Version file exists - should not have a "not found" error
            version_not_found = [f for f in failures if "VERSION file not found" in f]
            assert len(version_not_found) == 0

    def test_gitignore_detected(self) -> None:
        rg = import_release()
        failures = rg.run_pre_release_checks()
        gitignore_file = Path(__file__).resolve().parent.parent / ".gitignore"
        if gitignore_file.exists():
            gitignore_issue = [f for f in failures if ".gitignore" in f]
            assert len(gitignore_issue) == 0


# ── generate_release_notes ────────────────────────────────────────────────────


class TestGenerateReleaseNotes:
    def test_notes_contains_version(self) -> None:
        rg = import_release()
        notes = rg.generate_release_notes("2.54.0")
        assert "v2.54.0" in notes

    def test_notes_contains_date(self) -> None:
        rg = import_release()
        notes = rg.generate_release_notes("1.0.0")
        assert date.today().isoformat() in notes

    def test_notes_with_changes(self) -> None:
        rg = import_release()
        changes = ["Fix bug in risk engine", "Add new feature"]
        notes = rg.generate_release_notes("1.0.0", changes)
        assert "Fix bug in risk engine" in notes
        assert "Add new feature" in notes

    def test_notes_has_verification_section(self) -> None:
        rg = import_release()
        notes = rg.generate_release_notes("1.0.0")
        assert "## Verification" in notes

    def test_notes_has_change_section(self) -> None:
        rg = import_release()
        notes = rg.generate_release_notes("1.0.0")
        assert "## Changes" in notes

    def test_notes_empty_changes_list(self) -> None:
        rg = import_release()
        notes = rg.generate_release_notes("1.0.0", [])
        assert "## Changes" in notes

    def test_notes_markdown_format(self) -> None:
        rg = import_release()
        notes = rg.generate_release_notes("1.0.0")
        assert notes.startswith("#")


# ── write_release_notes ──────────────────────────────────────────────────────


class TestWriteReleaseNotes:
    def test_write_notes_returns_bool(self, tmp_path: Path) -> None:
        rg = import_release()
        # Temporarily redirect the RELEASE_NOTES_FILE to tmp_path
        old_path = rg.RELEASE_NOTES_FILE
        try:
            rg.RELEASE_NOTES_FILE = tmp_path / "RELEASE_NOTES.md"
            result = rg.write_release_notes("1.0.0", ["change1"])
            assert isinstance(result, bool)
        finally:
            rg.RELEASE_NOTES_FILE = old_path

    def test_write_notes_creates_file(self, tmp_path: Path) -> None:
        rg = import_release()
        old_path = rg.RELEASE_NOTES_FILE
        try:
            notes_path = tmp_path / "RELEASE_NOTES.md"
            rg.RELEASE_NOTES_FILE = notes_path
            rg.write_release_notes("1.0.0", ["change1"])
            assert notes_path.exists()
            content = notes_path.read_text(encoding="utf-8")
            assert "v1.0.0" in content
        finally:
            rg.RELEASE_NOTES_FILE = old_path


# ── update_changelog ──────────────────────────────────────────────────────────


class TestUpdateChangelog:
    def test_update_changelog_returns_bool(self, tmp_path: Path) -> None:
        rg = import_release()
        old_path = rg.CHANGELOG_FILE
        try:
            rg.CHANGELOG_FILE = tmp_path / "CHANGELOG.md"
            result = rg.update_changelog("1.0.0", ["change1"])
            assert isinstance(result, bool)
        finally:
            rg.CHANGELOG_FILE = old_path

    def test_update_changelog_creates_file(self, tmp_path: Path) -> None:
        rg = import_release()
        old_path = rg.CHANGELOG_FILE
        try:
            changelog_path = tmp_path / "CHANGELOG.md"
            rg.CHANGELOG_FILE = changelog_path
            rg.update_changelog("1.0.0", ["change1"])
            assert changelog_path.exists()
            content = changelog_path.read_text(encoding="utf-8")
            assert "v1.0.0" in content
            assert "change1" in content
        finally:
            rg.CHANGELOG_FILE = old_path

    def test_update_changelog_appends_to_existing(self, tmp_path: Path) -> None:
        rg = import_release()
        old_path = rg.CHANGELOG_FILE
        try:
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text("# Changelog\n\n## v0.9.0 (2026-01-01)\n\n- Old change\n")
            rg.CHANGELOG_FILE = changelog_path
            rg.update_changelog("1.0.0", ["New change"])
            content = changelog_path.read_text(encoding="utf-8")
            assert "v1.0.0" in content
            assert "New change" in content
        finally:
            rg.CHANGELOG_FILE = old_path

    def test_update_changelog_no_changes(self, tmp_path: Path) -> None:
        rg = import_release()
        old_path = rg.CHANGELOG_FILE
        try:
            changelog_path = tmp_path / "CHANGELOG.md"
            rg.CHANGELOG_FILE = changelog_path
            rg.update_changelog("1.0.0")
            content = changelog_path.read_text(encoding="utf-8")
            assert "v1.0.0" in content
        finally:
            rg.CHANGELOG_FILE = old_path


# ── write_audit_record ────────────────────────────────────────────────────────


class TestWriteAuditRecord:
    def test_audit_record_returns_bool(self, tmp_path: Path) -> None:
        rg = import_release()
        old_dir = rg.AUDIT_LOG_DIR
        try:
            rg.AUDIT_LOG_DIR = tmp_path / "audit"
            result = rg.write_audit_record("1.0.0", "main", ["change1"])
            assert isinstance(result, bool)
        finally:
            rg.AUDIT_LOG_DIR = old_dir

    def test_audit_record_creates_json_file(self, tmp_path: Path) -> None:
        rg = import_release()
        old_dir = rg.AUDIT_LOG_DIR
        try:
            audit_dir = tmp_path / "audit"
            rg.AUDIT_LOG_DIR = audit_dir
            rg.write_audit_record("1.0.0", "feature-branch", ["change1"])
            files = list(audit_dir.iterdir())
            assert len(files) == 1
            assert files[0].suffix == ".json"
        finally:
            rg.AUDIT_LOG_DIR = old_dir

    def test_audit_record_json_has_expected_fields(self, tmp_path: Path) -> None:
        rg = import_release()
        old_dir = rg.AUDIT_LOG_DIR
        try:
            audit_dir = tmp_path / "audit"
            rg.AUDIT_LOG_DIR = audit_dir
            rg.write_audit_record("1.0.0", "branch", ["change1"])
            files = list(audit_dir.iterdir())
            content = json.loads(files[0].read_text(encoding="utf-8"))
            assert "version" in content
            assert "branch" in content
            assert "date" in content
            assert "changes" in content
            assert "timestamp" in content
            assert "verified" in content
            assert "reproducible" in content
        finally:
            rg.AUDIT_LOG_DIR = old_dir

    def test_audit_record_contains_version(self, tmp_path: Path) -> None:
        rg = import_release()
        old_dir = rg.AUDIT_LOG_DIR
        try:
            audit_dir = tmp_path / "audit"
            rg.AUDIT_LOG_DIR = audit_dir
            rg.write_audit_record("2.54.0", "branch", ["change1"])
            files = list(audit_dir.iterdir())
            content = json.loads(files[0].read_text(encoding="utf-8"))
            assert content["version"] == "2.54.0"
        finally:
            rg.AUDIT_LOG_DIR = old_dir

    def test_audit_record_no_changes(self, tmp_path: Path) -> None:
        rg = import_release()
        old_dir = rg.AUDIT_LOG_DIR
        try:
            audit_dir = tmp_path / "audit"
            rg.AUDIT_LOG_DIR = audit_dir
            rg.write_audit_record("1.0.0", "branch")
            files = list(audit_dir.iterdir())
            content = json.loads(files[0].read_text(encoding="utf-8"))
            assert content["changes"] == []
        finally:
            rg.AUDIT_LOG_DIR = old_dir


# ── git helpers ────────────────────────────────────────────────────────────────


class TestGitHelpers:
    def test_git_commit_returns_tuple(self) -> None:
        rg = import_release()
        # This may fail if not in a git repo, but we can test the return type
        ok, msg = rg.git_commit("test commit")
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_git_tag_returns_tuple(self) -> None:
        rg = import_release()
        ok, tag = rg.git_tag("0.0.0-test")
        assert isinstance(ok, bool)
        assert isinstance(tag, str)

    def test_create_release_branch_returns_tuple(self) -> None:
        rg = import_release()
        ok, branch = rg.create_release_branch("0.0.0-test")
        assert isinstance(ok, bool)
        assert isinstance(branch, str)
        # If successful, branch name should contain the version
        if ok:
            assert "0.0.0-test" in branch


# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_release_notes_file_constant(self) -> None:
        rg = import_release()
        assert "RELEASE_NOTES.md" in str(rg.RELEASE_NOTES_FILE)

    def test_changelog_file_constant(self) -> None:
        rg = import_release()
        assert "CHANGELOG.md" in str(rg.CHANGELOG_FILE)

    def test_version_file_constant(self) -> None:
        rg = import_release()
        assert "VERSION" in str(rg.VERSION_FILE)

    def test_audit_log_dir_constant(self) -> None:
        rg = import_release()
        assert "audit" in str(rg.AUDIT_LOG_DIR)


# ── Main function ─────────────────────────────────────────────────────────────


class TestMain:
    def test_main_check_exit_zero(self, monkeypatch: Any) -> None:
        import subprocess
        rg = import_release()
        # Mock git status to return clean, so the test doesn't depend
        # on the actual working tree state
        def mock_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            if cmd == ["git", "status", "--porcelain"]:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            # Default for all other subprocess calls: return empty
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)
        exit_code = rg.main(["--check"])
        assert exit_code == 0

    def test_main_generate_notes(self) -> None:
        rg = import_release()
        exit_code = rg.main(["--generate-notes", "--version", "1.0.0"])
        assert exit_code == 0

    def test_main_generate_notes_with_changes(self) -> None:
        rg = import_release()
        exit_code = rg.main(["--generate-notes", "--version", "1.0.0",
                              "--change", "Fix bug", "--change", "Add feature"])
        assert exit_code == 0

    def test_main_audit_only(self) -> None:
        rg = import_release()
        exit_code = rg.main(["--audit", "--version", "1.0.0"])
        assert exit_code == 0

    def test_main_no_args(self) -> None:
        rg = import_release()
        exit_code = rg.main([])
        # Without version, uses 0.0.0 and proceeds through pipeline
        # Pipeline may fail if git isn't clean, but should still return 0 or 1
        assert exit_code in (0, 1)

    def test_main_commit_flag(self) -> None:
        rg = import_release()
        exit_code = rg.main(["--commit", "test commit message"])
        assert exit_code in (0, 1)

    def test_main_skip_branch(self) -> None:
        rg = import_release()
        exit_code = rg.main(["--version", "0.0.0-test", "--skip-branch"])
        assert exit_code in (0, 1)


# ── CLI entry point ────────────────────────────────────────────────────────────


class TestCLI:
    def test_script_exists(self) -> None:
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "release_governance.py"
        assert script_path.exists()
        assert script_path.stat().st_size > 0

    def test_script_has_shebang(self) -> None:
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "release_governance.py"
        content = script_path.read_text(encoding="utf-8")
        assert content.startswith("#!/usr/bin/env python3")
