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
import subprocess
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
    """
    Tests for run_pre_release_checks().

    Slow internal gate functions (_run_hygiene_gate, _run_architecture_gate,
    _run_slo_gate, _run_certification_checks, _run_register_consistency_gate)
    run subprocesses that scan the entire codebase and can take 10-60+ seconds
    each.  They are patched to no-ops here so the tests focus on the fast
    checks (VERSION, readme, .gitignore, docs, pyproject.toml) that actually
    exercise the function.
    """

    @staticmethod
    def _mock_slow_gates(rg: Any, monkeypatch: Any) -> None:
        """Patch slow internal gate functions to no-ops."""
        monkeypatch.setattr(rg, "_run_hygiene_gate", lambda failures: None)
        monkeypatch.setattr(rg, "_run_architecture_gate", lambda failures: None)
        monkeypatch.setattr(rg, "_run_slo_gate", lambda failures: None)
        monkeypatch.setattr(rg, "_run_certification_checks", lambda failures: None)
        monkeypatch.setattr(rg, "_run_register_consistency_gate", lambda failures: None)

    def test_checks_returns_list(self, monkeypatch: Any) -> None:
        rg = import_release()
        self._mock_slow_gates(rg, monkeypatch)
        failures = rg.run_pre_release_checks()
        assert isinstance(failures, list)

    def test_checks_returns_string_messages(self, monkeypatch: Any) -> None:
        rg = import_release()
        self._mock_slow_gates(rg, monkeypatch)
        failures = rg.run_pre_release_checks()
        for f in failures:
            assert isinstance(f, str)

    def test_version_file_detected(self, monkeypatch: Any) -> None:
        rg = import_release()
        self._mock_slow_gates(rg, monkeypatch)
        failures = rg.run_pre_release_checks()
        version_file = Path(__file__).resolve().parent.parent / "VERSION"
        if version_file.exists():
            version_not_found = [f for f in failures if "VERSION file not found" in f]
            assert len(version_not_found) == 0

    def test_gitignore_detected(self, monkeypatch: Any) -> None:
        rg = import_release()
        self._mock_slow_gates(rg, monkeypatch)
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

    def test_audit_record_trend_snapshot_field_defaults_false(self, tmp_path: Path) -> None:
        rg = import_release()
        old_dir = rg.AUDIT_LOG_DIR
        try:
            audit_dir = tmp_path / "audit"
            rg.AUDIT_LOG_DIR = audit_dir
            rg.write_audit_record("1.0.0", "branch")
            files = list(audit_dir.iterdir())
            content = json.loads(files[0].read_text(encoding="utf-8"))
            assert content["trend_snapshot_captured"] is False
        finally:
            rg.AUDIT_LOG_DIR = old_dir

    def test_audit_record_trend_snapshot_field_true(self, tmp_path: Path) -> None:
        rg = import_release()
        old_dir = rg.AUDIT_LOG_DIR
        try:
            audit_dir = tmp_path / "audit"
            rg.AUDIT_LOG_DIR = audit_dir
            rg.write_audit_record("1.0.0", "branch", trend_snapshot_captured=True)
            files = list(audit_dir.iterdir())
            content = json.loads(files[0].read_text(encoding="utf-8"))
            assert content["trend_snapshot_captured"] is True
        finally:
            rg.AUDIT_LOG_DIR = old_dir

    def test_audit_record_register_gate_fields_written(self, tmp_path: Path) -> None:
        rg = import_release()
        old_dir = rg.AUDIT_LOG_DIR
        try:
            audit_dir = tmp_path / "audit"
            rg.AUDIT_LOG_DIR = audit_dir
            rg.write_audit_record("1.0.0", "branch",
                                  register_gate_passed=True,
                                  register_gate_status="aligned")
            files = list(audit_dir.iterdir())
            content = json.loads(files[0].read_text(encoding="utf-8"))
            assert content["register_gate_passed"] is True
            assert content["register_gate_status"] == "aligned"
        finally:
            rg.AUDIT_LOG_DIR = old_dir

    def test_audit_record_register_gate_defaults_unknown(self, tmp_path: Path) -> None:
        """Without a gate run, the record defaults to unknown/None."""
        rg = import_release()
        old_dir = rg.AUDIT_LOG_DIR
        try:
            audit_dir = tmp_path / "audit"
            rg.AUDIT_LOG_DIR = audit_dir
            rg.write_audit_record("1.0.0", "standalone")
            files = list(audit_dir.iterdir())
            content = json.loads(files[0].read_text(encoding="utf-8"))
            assert content["register_gate_passed"] is None
            assert content["register_gate_status"] == "unknown"
        finally:
            rg.AUDIT_LOG_DIR = old_dir

    def test_audit_record_register_gate_drift_failure(self, tmp_path: Path) -> None:
        rg = import_release()
        old_dir = rg.AUDIT_LOG_DIR
        try:
            audit_dir = tmp_path / "audit"
            rg.AUDIT_LOG_DIR = audit_dir
            rg.write_audit_record("1.0.0", "branch",
                                  register_gate_passed=False,
                                  register_gate_status="drift")
            files = list(audit_dir.iterdir())
            content = json.loads(files[0].read_text(encoding="utf-8"))
            assert content["register_gate_passed"] is False
            assert content["register_gate_status"] == "drift"
        finally:
            rg.AUDIT_LOG_DIR = old_dir


# ── capture_trend_snapshot ────────────────────────────────────────────────────


class TestCaptureTrendSnapshot:
    def test_returns_true_on_success(self, monkeypatch: Any) -> None:
        rg = import_release()

        class _Result:
            returncode = 0
            stdout = "Captured snapshot"
            stderr = ""

        monkeypatch.setattr(rg.subprocess, "run", lambda *a, **k: _Result())
        assert rg.capture_trend_snapshot("2.58.0") is True

    def test_returns_false_on_nonzero(self, monkeypatch: Any) -> None:
        rg = import_release()

        class _Result:
            returncode = 1
            stdout = ""
            stderr = "boom"

        monkeypatch.setattr(rg.subprocess, "run", lambda *a, **k: _Result())
        assert rg.capture_trend_snapshot("2.58.0") is False

    def test_returns_false_on_exception(self, monkeypatch: Any) -> None:
        rg = import_release()

        def _raise(*a, **k):
            raise subprocess.TimeoutExpired(cmd="x", timeout=5)

        monkeypatch.setattr(rg.subprocess, "run", _raise)
        assert rg.capture_trend_snapshot("2.58.0") is False

    def test_passes_release_label(self, monkeypatch: Any) -> None:
        rg = import_release()
        captured: list[list[str]] = []

        class _Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def _run(cmd: list[str], *a, **k):
            captured.append(cmd)
            return _Result()

        monkeypatch.setattr(rg.subprocess, "run", _run)
        rg.capture_trend_snapshot("2.58.0")
        assert captured
        args = captured[0]
        assert "--capture" in args
        assert "--release" in args
        assert "v2.58.0" in args

    def test_cli_capture_trend_flag(self, monkeypatch: Any) -> None:
        """--capture-trend runs the capture helper and exits 0."""
        rg = import_release()

        class _Result:
            returncode = 0
            stdout = "Captured snapshot"
            stderr = ""

        monkeypatch.setattr(rg.subprocess, "run", lambda *a, **k: _Result())
        rc = rg.main(["--capture-trend", "--version", "2.58.0"])
        assert rc == 0

    def test_cli_capture_trend_failure_exits_nonzero(self, monkeypatch: Any) -> None:
        rg = import_release()

        class _Result:
            returncode = 2
            stdout = ""
            stderr = "nope"

        monkeypatch.setattr(rg.subprocess, "run", lambda *a, **k: _Result())
        rc = rg.main(["--capture-trend", "--version", "2.58.0"])
        assert rc == 1


# ── register consistency gate ──────────────────────────────────────────────────


class TestRegisterConsistencyGate:
    """Tests for the blocking register-pattern consistency gate."""

    @staticmethod
    def _result(returncode: int) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=["python", "-m", "core.success_metrics_trend", "--check-registers"],
            returncode=returncode, stdout="", stderr="" if returncode == 0 else "drift!",
        )

    def test_gate_appends_failure_on_drift(self, monkeypatch: Any) -> None:
        """A non-zero --check-registers exit (drift) must block the release."""
        rg = import_release()
        monkeypatch.setattr(
            rg.subprocess, "run", lambda *a, **k: self._result(returncode=1),
        )
        failures: list[str] = ["pre-existing"]
        rg._run_register_consistency_gate(failures)
        assert len(failures) == 2
        assert "Register consistency gate" in failures[1]
        assert "drifted" in failures[1]

    def test_gate_no_failure_when_aligned(self, monkeypatch: Any) -> None:
        """A clean --check-registers exit (aligned) must not block the release."""
        rg = import_release()
        monkeypatch.setattr(
            rg.subprocess, "run", lambda *a, **k: self._result(returncode=0),
        )
        failures: list[str] = ["pre-existing"]
        rg._run_register_consistency_gate(failures)
        assert len(failures) == 1

    def test_gate_appends_failure_on_timeout(self, monkeypatch: Any) -> None:
        """A timeout must also block the release."""
        rg = import_release()

        def _raise(*a, **k):
            raise subprocess.TimeoutExpired(cmd="x", timeout=5)

        monkeypatch.setattr(rg.subprocess, "run", _raise)
        failures: list[str] = []
        rg._run_register_consistency_gate(failures)
        assert len(failures) == 1
        assert "timed out" in failures[0]

    def test_gate_skips_when_module_missing(self, monkeypatch: Any) -> None:
        """A missing module (FileNotFoundError) must skip gracefully."""
        rg = import_release()

        def _raise(*a, **k):
            raise FileNotFoundError("python not found")

        monkeypatch.setattr(rg.subprocess, "run", _raise)
        failures: list[str] = []
        rg._run_register_consistency_gate(failures)
        assert failures == []

    def test_gate_passes_module_and_cwd(self, monkeypatch: Any) -> None:
        """The gate must invoke the trend module's --check-registers flag."""
        rg = import_release()
        captured: dict[str, Any] = {}

        def _run(cmd: list[str], *a, **k):
            captured["cmd"] = cmd
            captured["cwd"] = k.get("cwd")
            return self._result(returncode=0)

        monkeypatch.setattr(rg.subprocess, "run", _run)
        rg._run_register_consistency_gate([])
        assert "-m" in captured["cmd"]
        assert "core.success_metrics_trend" in captured["cmd"]
        assert "--check-registers" in captured["cmd"]
        assert captured["cwd"] == str(rg.ROOT)

    def test_gate_returns_aligned_verdict(self, monkeypatch: Any) -> None:
        """A clean gate run returns an aligned (passed) verdict dict."""
        rg = import_release()
        monkeypatch.setattr(
            rg.subprocess, "run", lambda *a, **k: self._result(returncode=0),
        )
        verdict = rg._run_register_consistency_gate([])
        assert verdict == {"passed": True, "status": "aligned", "drifted_registers": []}

    def test_gate_returns_drift_verdict(self, monkeypatch: Any) -> None:
        """A non-zero gate exit returns a drift (failed) verdict dict."""
        rg = import_release()
        monkeypatch.setattr(
            rg.subprocess, "run", lambda *a, **k: self._result(returncode=1),
        )
        verdict = rg._run_register_consistency_gate([])
        assert verdict == {"passed": False, "status": "drift", "drifted_registers": []}

    def test_gate_returns_skipped_verdict_on_missing_interpreter(self, monkeypatch: Any) -> None:
        """A missing interpreter returns a skipped (not-verified) verdict."""
        rg = import_release()

        def _raise(*a, **k):
            raise FileNotFoundError("python not found")

        monkeypatch.setattr(rg.subprocess, "run", _raise)
        verdict = rg._run_register_consistency_gate([])
        assert verdict == {"passed": None, "status": "skipped", "drifted_registers": []}

    def test_gate_returns_unavailable_verdict_on_timeout(self, monkeypatch: Any) -> None:
        """A timed-out gate returns an unavailable (failed) verdict."""
        rg = import_release()

        def _raise(*a, **k):
            raise subprocess.TimeoutExpired(cmd="x", timeout=5)

        monkeypatch.setattr(rg.subprocess, "run", _raise)
        verdict = rg._run_register_consistency_gate([])
        assert verdict == {"passed": False, "status": "unavailable", "drifted_registers": []}

    def test_pre_release_checks_captures_gate_verdict(self, monkeypatch: Any) -> None:
        """run_pre_release_checks() must store the gate verdict for the audit record."""
        rg = import_release()
        class _Res:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(rg.subprocess, "run", lambda *a, **k: _Res())
        monkeypatch.setattr(rg, "_run_hygiene_gate", lambda failures: None)
        monkeypatch.setattr(rg, "_run_architecture_gate", lambda failures: None)
        monkeypatch.setattr(rg, "_run_slo_gate", lambda failures: None)
        monkeypatch.setattr(rg, "_run_certification_checks", lambda failures: None)
        monkeypatch.setattr(
            rg, "_run_register_consistency_gate",
            lambda failures: {"passed": False, "status": "drift",
                              "drifted_registers": ["docs/config_drift_register.md"]},
        )
        rg.run_pre_release_checks(skip_certifications=True)
        assert rg._LAST_REGISTER_GATE_VERDICT == {
            "passed": False, "status": "drift",
            "drifted_registers": ["docs/config_drift_register.md"],
        }

    def test_pre_release_checks_runs_register_gate(self, monkeypatch: Any) -> None:
        """run_pre_release_checks() must invoke the register consistency gate."""
        rg = import_release()
        # Patch slow gates + git status so only the wiring under test matters.
        class _Res:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(rg.subprocess, "run", lambda *a, **k: _Res())
        monkeypatch.setattr(rg, "_run_hygiene_gate", lambda failures: None)
        monkeypatch.setattr(rg, "_run_architecture_gate", lambda failures: None)
        monkeypatch.setattr(rg, "_run_slo_gate", lambda failures: None)
        monkeypatch.setattr(rg, "_run_certification_checks", lambda failures: None)
        calls: list[str] = []
        monkeypatch.setattr(
            rg, "_run_register_consistency_gate",
            lambda failures: calls.append("gate"),
        )
        rg.run_pre_release_checks(skip_certifications=True)
        assert calls == ["gate"]


# ── git helpers ────────────────────────────────────────────────────────────────


class TestGitHelpers:
    """Git-helper tests MUST NOT mutate the real repository.

    ``git_commit()`` runs ``git add -A`` + ``git commit`` against the actual
    repo ROOT, so an unmocked call creates real commits and sweeps in whatever
    is staged/unstaged (previously produced junk "test commit" entries in the
    reflog and clobbered CHANGELOG.md/RELEASE_NOTES.md). All git subprocess
    calls are therefore mocked to return success without touching the repo.
    """

    @staticmethod
    def _fake_success_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    def test_git_commit_returns_tuple(self, monkeypatch: Any) -> None:
        rg = import_release()
        monkeypatch.setattr(rg.subprocess, "run", self._fake_success_run)
        ok, msg = rg.git_commit("test commit")
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_git_tag_returns_tuple(self, monkeypatch: Any) -> None:
        rg = import_release()
        monkeypatch.setattr(rg.subprocess, "run", self._fake_success_run)
        ok, tag = rg.git_tag("0.0.0-test")
        assert isinstance(ok, bool)
        assert isinstance(tag, str)

    def test_create_release_branch_returns_tuple(self, monkeypatch: Any) -> None:
        rg = import_release()
        monkeypatch.setattr(rg.subprocess, "run", self._fake_success_run)
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
        rg = import_release()
        # Mock git status to return clean, so the test doesn't depend
        # on the actual working tree state
        def mock_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            if cmd == ["git", "status", "--porcelain"]:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            # Default for all other subprocess calls: return empty
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)
        # Use --skip-cert to avoid SLO gating (requires live trading data to pass)
        exit_code = rg.main(["--check", "--skip-cert"])
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

    def test_main_audit_only(self, tmp_path: Path) -> None:
        rg = import_release()
        # Redirect the audit log dir so the CLI test doesn't write into the
        # real logs/audit directory (test isolation).
        old_audit = rg.AUDIT_LOG_DIR
        try:
            rg.AUDIT_LOG_DIR = tmp_path / "audit"
            exit_code = rg.main(["--audit", "--version", "1.0.0"])
            assert exit_code == 0
        finally:
            rg.AUDIT_LOG_DIR = old_audit

    def test_main_no_args(self, monkeypatch: Any, tmp_path: Path) -> None:
        rg = import_release()

        def mock_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        # Redirect file outputs so the full pipeline CLI test does NOT
        # overwrite the real RELEASE_NOTES.md / CHANGELOG.md / audit records.
        old_notes, old_changelog, old_audit = (
            rg.RELEASE_NOTES_FILE, rg.CHANGELOG_FILE, rg.AUDIT_LOG_DIR,
        )
        try:
            rg.RELEASE_NOTES_FILE = tmp_path / "RELEASE_NOTES.md"
            rg.CHANGELOG_FILE = tmp_path / "CHANGELOG.md"
            rg.AUDIT_LOG_DIR = tmp_path / "audit"
            exit_code = rg.main([])
            assert exit_code in (0, 1)
        finally:
            rg.RELEASE_NOTES_FILE, rg.CHANGELOG_FILE, rg.AUDIT_LOG_DIR = (
                old_notes, old_changelog, old_audit,
            )

    def test_main_commit_flag(self, monkeypatch: Any) -> None:
        rg = import_release()

        def mock_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        exit_code = rg.main(["--commit", "test commit message"])
        assert exit_code in (0, 1)

    def test_main_skip_branch(self, monkeypatch: Any, tmp_path: Path) -> None:
        rg = import_release()

        def mock_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        # Redirect file outputs so the full pipeline CLI test does NOT
        # overwrite the real RELEASE_NOTES.md / CHANGELOG.md / audit records
        # (previously clobbered them with the placeholder v0.0.0-test content).
        old_notes, old_changelog, old_audit = (
            rg.RELEASE_NOTES_FILE, rg.CHANGELOG_FILE, rg.AUDIT_LOG_DIR,
        )
        try:
            rg.RELEASE_NOTES_FILE = tmp_path / "RELEASE_NOTES.md"
            rg.CHANGELOG_FILE = tmp_path / "CHANGELOG.md"
            rg.AUDIT_LOG_DIR = tmp_path / "audit"
            exit_code = rg.main(["--version", "0.0.0-test", "--skip-branch"])
            assert exit_code in (0, 1)
        finally:
            rg.RELEASE_NOTES_FILE, rg.CHANGELOG_FILE, rg.AUDIT_LOG_DIR = (
                old_notes, old_changelog, old_audit,
            )

    def test_main_pipeline_audit_records_register_gate(self, monkeypatch: Any,
                                                       tmp_path: Path) -> None:
        """The full pipeline writes the captured gate verdict into the audit JSON."""
        rg = import_release()
        old_audit, old_notes, old_changelog = (
            rg.AUDIT_LOG_DIR, rg.RELEASE_NOTES_FILE, rg.CHANGELOG_FILE,
        )
        try:
            rg.AUDIT_LOG_DIR = tmp_path / "audit"
            rg.RELEASE_NOTES_FILE = tmp_path / "RELEASE_NOTES.md"
            rg.CHANGELOG_FILE = tmp_path / "CHANGELOG.md"

            class _Res:
                returncode = 0
                stdout = ""
                stderr = ""

            monkeypatch.setattr(rg.subprocess, "run", lambda *a, **k: _Res())
            monkeypatch.setattr(rg, "_run_hygiene_gate", lambda failures: None)
            monkeypatch.setattr(rg, "_run_architecture_gate", lambda failures: None)
            monkeypatch.setattr(rg, "_run_slo_gate", lambda failures: None)
            monkeypatch.setattr(rg, "_run_certification_checks", lambda failures: None)
            monkeypatch.setattr(
                rg, "_run_register_consistency_gate",
                lambda failures: {"passed": True, "status": "aligned",
                                  "drifted_registers": []},
            )
            exit_code = rg.main(["--version", "0.0.0-test", "--skip-branch"])
            assert exit_code == 0

            files = list((tmp_path / "audit").iterdir())
            assert len(files) == 1
            content = json.loads(files[0].read_text(encoding="utf-8"))
            assert content["register_gate_passed"] is True
            assert content["register_gate_status"] == "aligned"
        finally:
            rg.AUDIT_LOG_DIR, rg.RELEASE_NOTES_FILE, rg.CHANGELOG_FILE = (
                old_audit, old_notes, old_changelog,
            )


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
