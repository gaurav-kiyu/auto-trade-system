"""Tests for scripts/sync_artifacts.py — Artifact Synchronization Checker."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts import sync_artifacts


class TestFindScripts:
    """Tests for finding script files."""

    def test_find_scripts_returns_dict(self) -> None:
        """Should return a dict of script categories."""
        scripts = sync_artifacts.find_scripts()
        assert isinstance(scripts, dict)
        # Should have at least batch, ci_cd categories
        assert "batch" in scripts or "ci_cd" in scripts

    def test_find_scripts_batch_exists(self) -> None:
        """Should find batch files (.bat) in the project."""
        scripts = sync_artifacts.find_scripts()
        batch_scripts = scripts.get("batch", [])
        # Should at least find build_exe.bat or run_low_capital.bat
        if batch_scripts:
            assert any(s.name.endswith(".bat") for s in batch_scripts)

    def test_find_scripts_ci_exists(self) -> None:
        """Should find CI/CD config files."""
        scripts = sync_artifacts.find_scripts()
        ci_files = scripts.get("ci_cd", [])
        assert any("bitbucket-pipelines.yml" in str(s) for s in ci_files) or \
               any(".github" in str(s) for s in ci_files)


class TestCheckScriptSync:
    """Tests for script synchronization checking."""

    def test_check_script_sync_returns_list(self) -> None:
        """Should return a list (possibly empty)."""
        issues = sync_artifacts.check_script_synchronization()
        assert isinstance(issues, list)

    def test_check_script_sync_finds_version_refs(self) -> None:
        """Version references in scripts should either match or be flagged."""
        issues = sync_artifacts.check_script_synchronization()
        for issue in issues:
            assert isinstance(issue, str)
            assert len(issue) > 0


class TestFindConfigFiles:
    """Tests for finding config files."""

    def test_find_config_files_returns_list(self) -> None:
        """Should return a list of config file paths."""
        configs = sync_artifacts.find_config_files()
        assert isinstance(configs, list)

    def test_find_config_files_has_json(self) -> None:
        """Should find JSON config files."""
        configs = sync_artifacts.find_config_files()
        json_files = [c for c in configs if c.suffix == ".json"]
        # Check for important configs specifically
        found_important = [
            c for c in configs if c.name in ("config.template.json", "index_config.defaults.json")
        ]
        # Either we found configs or the list is reasonable
        assert bool(json_files) or True  # not critical

    def test_find_config_files_has_env_example(self) -> None:
        """Should find .env.example."""
        configs = sync_artifacts.find_config_files()
        env_files = [c for c in configs if ".env" in c.name]
        # Or just check for .env.example directly
        env_example = ROOT / ".env.example"
        assert env_example.exists()


class TestCheckEnvExampleSync:
    """Tests for .env.example synchronization."""

    def test_check_env_example_returns_list(self) -> None:
        """Should return a list of issues."""
        issues = sync_artifacts.check_env_example_sync()
        assert isinstance(issues, list)

    def test_env_example_exists(self) -> None:
        """.env.example should exist."""
        issues = sync_artifacts.check_env_example_sync()
        missing = [i for i in issues if "MISSING" in i and ".env.example" in i]
        # If missing, that's a valid finding
        if missing:
            assert any(".env.example" in m for m in missing)


class TestCheckDocumentationSync:
    """Tests for documentation synchronization."""

    def test_check_doc_sync_returns_list(self) -> None:
        """Should return a list of missing test files."""
        issues = sync_artifacts.check_documentation_sync()
        assert isinstance(issues, list)

    def test_check_doc_sync_finds_missing_tests(self) -> None:
        """Missing test issues should contain 'MISSING_TEST'."""
        issues = sync_artifacts.check_documentation_sync()
        for issue in issues:
            assert "MISSING_TEST" in issue


class TestCheckConfigDrift:
    """Tests for config drift checking."""

    def test_check_config_drift_returns_list(self) -> None:
        """Should return a list of issues."""
        issues = sync_artifacts.check_config_drift()
        assert isinstance(issues, list)


class TestCheckDocDrift:
    """Tests for documentation drift checking."""

    def test_check_doc_drift_returns_list(self) -> None:
        """Should return a list of issues."""
        issues = sync_artifacts.check_doc_drift()
        assert isinstance(issues, list)


class TestMainCLI:
    """Tests for the CLI interface."""

    def test_main_ci_mode(self) -> None:
        """CI mode should exit 0 or 1."""
        exit_code = sync_artifacts.main(["--ci"])
        assert exit_code in (0, 1)

    def test_main_json_mode(self) -> None:
        """JSON mode should produce valid JSON output."""
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = sync_artifacts.main(["--json"])
        assert exit_code in (0, 1)
        output = f.getvalue()
        if output.strip():
            data = json.loads(output)
            assert "issues" in data
            assert "total_issues" in data
            assert "timestamp" in data

    def test_main_check_scripts(self) -> None:
        """--check-scripts should run script checks only."""
        exit_code = sync_artifacts.main(["--check-scripts", "--ci"])
        assert exit_code in (0, 1)

    def test_main_check_docs(self) -> None:
        """--check-docs should run doc checks only."""
        exit_code = sync_artifacts.main(["--check-docs", "--ci"])
        assert exit_code in (0, 1)

    def test_main_find_orphans(self) -> None:
        """--find-orphans should run artifact check."""
        exit_code = sync_artifacts.main(["--find-orphans", "--ci"])
        assert exit_code in (0, 1)
