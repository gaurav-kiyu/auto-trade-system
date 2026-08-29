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

import json
import sys
from pathlib import Path
from typing import Any

import pytest

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

    def test_git_history_uses_valid_syntax(self) -> None:
        """The git command must be valid so history is reported accessible.

        Regression: ``git log --oneline=-N`` was an unrecognized argument,
        so check_git_history() always returned False. It must now use
        ``git log -N --oneline`` and succeed inside a real repo.
        """
        pc = import_pre_check()
        result = pc.check_git_history(count=10)
        # Source archives may not contain .git metadata; in that case the
        # helper legitimately returns False. In a checkout it must succeed.
        repo_root = Path(__file__).resolve().parents[1]
        assert result is (repo_root / ".git").exists()

    def test_git_history_mocked_command(self, monkeypatch) -> None:
        """Verify the exact git argument list used (isolated from env)."""
        pc = import_pre_check()
        captured: list[list[str]] = []

        class FakeResult:
            returncode = 0

        def fake_run(cmd, capture_output=False, text=False, cwd=None, timeout=15):
            captured.append(cmd)
            return FakeResult()

        monkeypatch.setattr(pc.subprocess, "run", fake_run)
        assert pc.check_git_history(count=7) is True
        assert captured, "git command should be invoked"
        cmd = captured[0]
        assert cmd[0] == "git"
        assert "-7" in cmd
        assert "--oneline" in cmd
        assert "--oneline=-7" not in cmd


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


# ── Reviewed-change allowlist ────────────────────────────────────────────────


class TestAllowlist:
    def test_load_allowlist_missing_file_returns_empty(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        data = pc.load_allowlist(tmp_path / "missing.json")
        assert data["entries"] == []

    def test_load_allowlist_corrupt_file_returns_empty(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        bad = tmp_path / "bad.json"
        bad.write_text("not json {{{{", encoding="utf-8")
        data = pc.load_allowlist(bad)
        assert data["entries"] == []

    def test_load_allowlist_parses_entries(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        good = tmp_path / "good.json"
        good.write_text(
            json.dumps({"schema_version": 1, "entries": [{"file": "a.py", "pattern": "PAPER_MODE"}]}),
            encoding="utf-8",
        )
        data = pc.load_allowlist(good)
        assert len(data["entries"]) == 1

    def test_is_allowlisted_exact_pair(self) -> None:
        pc = import_pre_check()
        data = {"entries": [{"file": "index_app/index_trader.py", "pattern": "PAPER_MODE"}]}
        assert pc.is_allowlisted("index_app/index_trader.py", "PAPER_MODE", data)
        # Different pattern, same file -> NOT allowed
        assert not pc.is_allowlisted("index_app/index_trader.py", "SL_PCT", data)
        # Different file, same pattern -> NOT allowed
        assert not pc.is_allowlisted("core/foo.py", "PAPER_MODE", data)

    def test_add_allowlist_entry_persists(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        allow_path = tmp_path / "allowlist.json"
        entry = pc.add_allowlist_entry(
            file="core/foo.py",
            pattern="SL_PCT",
            reason="reviewed safe",
            reviewer="tester",
            path=allow_path,
        )
        assert entry["id"] == "ALLOW-0001"
        assert entry["reviewer"] == "tester"
        reloaded = pc.load_allowlist(allow_path)
        assert len(reloaded["entries"]) == 1

    def test_add_allowlist_entry_rejects_unknown_pattern(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        with pytest.raises(ValueError):
            pc.add_allowlist_entry(
                file="core/foo.py",
                pattern="NOT_A_REAL_PATTERN",
                reason="nope",
                path=tmp_path / "allowlist.json",
            )

    def test_add_allowlist_entry_rejects_blocked_file(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        with pytest.raises(ValueError):
            pc.add_allowlist_entry(
                file="tests/test_smoke.py",
                pattern="SL_PCT",
                reason="cannot",
                path=tmp_path / "allowlist.json",
            )

    def test_add_allowlist_entry_dedupes(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        allow_path = tmp_path / "allowlist.json"
        pc.add_allowlist_entry("a.py", "SL_PCT", "first", path=allow_path)
        pc.add_allowlist_entry("a.py", "SL_PCT", "second", path=allow_path)
        reloaded = pc.load_allowlist(allow_path)
        assert len(reloaded["entries"]) == 1
        assert reloaded["entries"][0]["reason"] == "second"

    def test_add_allowlist_entry_id_no_collision_after_dedupe(self, tmp_path: Path) -> None:
        """Re-adding a deduped pair must not mint an id that collides with a
        remaining entry (regression: len(entries)+1 after mid-list dedupe)."""
        pc = import_pre_check()
        allow_path = tmp_path / "allowlist.json"
        pc.add_allowlist_entry("a.py", "SL_PCT", "first", path=allow_path)
        pc.add_allowlist_entry("b.py", "TARGET_PCT", "second", path=allow_path)
        # Re-add a.py/SL_PCT -> dedupe removes ALLOW-0001, new id must be 0003
        # (max existing is 0002), not 0001 again.
        pc.add_allowlist_entry("a.py", "SL_PCT", "third", path=allow_path)
        reloaded = pc.load_allowlist(allow_path)
        ids = [e["id"] for e in reloaded["entries"]]
        assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"
        assert "ALLOW-0003" in ids

    def test_check_risk_controls_skips_allowlisted(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        risky_file = tmp_path / "risky.py"
        risky_file.write_text("PAPER_MODE = True")
        allowlist = {"entries": [{"file": str(risky_file).replace("\\", "/"), "pattern": "PAPER_MODE"}]}
        violations = pc.check_risk_controls([str(risky_file)], allowlist=allowlist)
        assert len(violations) == 0

    def test_check_risk_controls_still_flags_non_allowlisted(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        risky_file = tmp_path / "risky.py"
        risky_file.write_text("MAX_DAILY_LOSS = 500")
        allowlist = {"entries": [{"file": str(risky_file).replace("\\", "/"), "pattern": "PAPER_MODE"}]}
        violations = pc.check_risk_controls([str(risky_file)], allowlist=allowlist)
        assert any("MAX_DAILY_LOSS" in v for v in violations)

    def test_main_list_allowlist(self) -> None:
        pc = import_pre_check()
        exit_code = pc.main(["--list-allowlist"])
        assert exit_code == 0

    def test_main_allow_add_missing_reason(self) -> None:
        pc = import_pre_check()
        exit_code = pc.main(["--allow-add", "core/foo.py", "--pattern", "SL_PCT"])
        assert exit_code == 1

    def test_main_allow_add_rejects_blocked(self, tmp_path: Path) -> None:
        pc = import_pre_check()
        allow_path = tmp_path / "allowlist.json"
        exit_code = pc.main([
            "--allow-add", "tests/test_smoke.py",
            "--pattern", "SL_PCT", "--reason", "nope",
            "--allowlist", str(allow_path),
        ])
        assert exit_code == 1

    def test_default_allowlist_file_exists(self) -> None:
        pc = import_pre_check()
        assert pc.DEFAULT_ALLOWLIST_FILE.exists()
        entries = pc.list_allowlist()
        # The reviewed PAPER_MODE entry for the --paper CLI fix must be present
        assert any(
            e.get("file") == "index_app/index_trader.py" and e.get("pattern") == "PAPER_MODE"
            for e in entries
        )


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
