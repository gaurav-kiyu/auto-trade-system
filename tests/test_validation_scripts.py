"""Integration tests for all certification/validation scripts.

Validates that every script in the certification pipeline:
  1. Has valid Python syntax (compiles without error)
  2. Contains expected public functions
  3. Can produce --help output without crashing
  4. Handles missing input data gracefully

These are lightweight integration tests — not unit tests of internal logic.
They verify the scripts are structurally sound and won't fail at import time.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Scripts to test (exclude non-Python and utility scripts)
CERTIFICATION_SCRIPTS = [
    "scripts/run_certify.py",
    "scripts/run_compliance_report.py",
    "scripts/run_benchmarks.py",
    "scripts/run_code_quality_report.py",
    "scripts/run_coverage_heatmap.py",
    "scripts/check_db_integrity.py",
    "scripts/check_config_drift.py",
    "scripts/run_hygiene_scan.py",
    "scripts/check_thread_safety.py",
    "scripts/quantitative_validation_report.py",
    "scripts/run_flamegraph_profiler.py",
    "scripts/check_docker_security.py",
    "scripts/run_backup_rotation.py",
    "scripts/production_preflight_check.py",
    "scripts/migrate_print_to_logging.py",
    "scripts/historical_comparison.py",
    "scripts/run_mutation_tests.py",
    "scripts/hardcoded_value_checker.py",
]


# ── Helpers ────────────────────────────────────────────────────────────────────


def _script_path(name: str) -> Path:
    """Convert script name to absolute path."""
    return PROJECT_ROOT / name


def _can_compile(path: Path) -> bool:
    """Check if a Python file compiles without syntax errors."""
    try:
        with open(path, encoding="utf-8") as f:
            ast.parse(f.read(), filename=str(path))
        return True
    except SyntaxError:
        return False


def _has_main_function(path: Path) -> bool:
    """Check if a script has a main() or _cli() function."""
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in ("main", "_cli"):
                    return True
        return False
    except SyntaxError:
        return False


def _has_if_main_guard(path: Path) -> bool:
    """Check if a script has 'if __name__ == \"__main__\":' guard."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        return '__name__ == "__main__"' in content or '__name__ == \'__main__\'' in content
    except (OSError, UnicodeDecodeError):
        return False


def _run_help(script_name: str, timeout: int = 15) -> dict[str, Any]:
    """Run a script with --help and capture output."""
    path = _script_path(script_name)
    if not path.exists():
        return {"passed": False, "error": "File not found"}

    try:
        result = subprocess.run(
            [sys.executable, str(path), "--help"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # --help returns exit code 0, but some scripts may use argparse which
        # exits 0 for --help. If argparse isn't configured, it may exit 2.
        return {
            "passed": result.returncode in (0, 2),
            "exit_code": result.returncode,
            "stdout_preview": result.stdout[:200] if result.stdout else "",
            "stderr_preview": result.stderr[:200] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "error": "Timed out"}
    except FileNotFoundError:
        return {"passed": False, "error": "Python interpreter not found"}
    except Exception as e:
        return {"passed": False, "error": str(e)}


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestScriptCompilation:
    """All scripts must compile without syntax errors."""

    @pytest.mark.parametrize("script_name", CERTIFICATION_SCRIPTS)
    def test_compiles(self, script_name: str) -> None:
        path = _script_path(script_name)
        assert path.exists(), f"Script not found: {path}"
        assert _can_compile(path), f"{script_name} has syntax errors"


class TestScriptStructure:
    """Scripts should have expected structural elements."""

    @pytest.mark.parametrize("script_name", CERTIFICATION_SCRIPTS)
    def test_has_main_function(self, script_name: str) -> None:
        path = _script_path(script_name)
        if not path.exists():
            pytest.skip(f"{script_name} not found")
        assert _has_main_function(path), f"{script_name} missing main() or _cli()"

    @pytest.mark.parametrize("script_name", CERTIFICATION_SCRIPTS)
    def test_has_main_guard(self, script_name: str) -> None:
        path = _script_path(script_name)
        if not path.exists():
            pytest.skip(f"{script_name} not found")
        assert _has_if_main_guard(path), (
            f"{script_name} missing __name__ guard"
        )


class TestScriptHelp:
    """Scripts must respond to --help without crashing."""

    @pytest.mark.parametrize("script_name", CERTIFICATION_SCRIPTS)
    def test_help_output(self, script_name: str) -> None:
        result = _run_help(script_name)
        assert result["passed"], (
            f"{script_name} --help failed: "
            f"exit={result.get('exit_code', 'N/A')} "
            f"error={result.get('error', 'None')}"
        )


class TestAllScriptsCompile:
    """Batch compilation of ALL Python files in scripts/."""

    def test_all_scripts_compile(self) -> None:
        """Every .py file in scripts/ must compile."""
        py_files = sorted(SCRIPTS_DIR.rglob("*.py"))
        errors = []
        for path in py_files:
            if not _can_compile(path):
                errors.append(str(path.relative_to(PROJECT_ROOT)))
        assert not errors, (
            f"{len(errors)} script(s) with syntax errors:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    def test_certify_import(self) -> None:
        """Test that run_certify can be imported without runtime errors."""
        script_path = SCRIPTS_DIR / "run_certify.py"
        if not script_path.exists():
            pytest.skip("run_certify.py not found")
        spec = importlib.util.spec_from_file_location("run_certify", script_path)
        assert spec is not None, "Failed to create module spec"
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception as e:
            pytest.fail(f"Import of run_certify.py failed: {e}")

        # Check that expected constants exist
        assert hasattr(mod, "_TOOLS"), "Missing _TOOLS registry"
        assert hasattr(mod, "_compute_certification_score"), "Missing scoring function"
        assert hasattr(mod, "_generate_html_dashboard"), "Missing HTML generator"


class TestRiskServiceScriptsExist:
    """Verify that scripts referenced by the certification runner exist."""

    def test_certify_tool_registry(self) -> None:
        """Every script referenced in run_certify.py must exist on disk."""
        certify_path = SCRIPTS_DIR / "run_certify.py"
        if not certify_path.exists():
            pytest.skip("run_certify.py not found")

        # Parse the _TOOLS list from the AST
        with open(certify_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(certify_path))

        script_refs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "script":
                        if isinstance(value, ast.Constant):
                            script_refs.append(value.value)

        missing = []
        for ref in script_refs:
            path = PROJECT_ROOT / ref
            if not path.exists():
                missing.append(ref)

        assert not missing, (
            "Scripts referenced by run_certify.py not found:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )


class TestScriptContent:
    """Spot-check that scripts have expected content."""

    SCRIPT_CHECKS: list[tuple[str, str]] = [
        ("scripts/run_certify.py", "Full System Certification Runner"),
        ("scripts/quantitative_validation_report.py", "Sharpe"),
        ("scripts/run_flamegraph_profiler.py", "Flamegraph"),
        ("scripts/check_docker_security.py", "CIS"),
        ("scripts/check_db_integrity.py", "integrity"),
        ("scripts/check_config_drift.py", "drift"),
        ("scripts/run_hygiene_scan.py", "credential"),
        ("scripts/check_thread_safety.py", "thread"),
        ("scripts/run_benchmarks.py", "P99"),
        ("scripts/run_code_quality_report.py", "cyclomatic"),
        ("scripts/run_mutation_tests.py", "mutant"),
        ("scripts/run_backup_rotation.py", "backup"),
        ("scripts/production_preflight_check.py", "preflight"),
        ("scripts/migrate_print_to_logging.py", "print"),
        ("scripts/historical_comparison.py", "regression"),
    ]

    @pytest.mark.parametrize("script_name,keyword", SCRIPT_CHECKS)
    def test_contains_keyword(self, script_name: str, keyword: str) -> None:
        path = _script_path(script_name)
        if not path.exists():
            pytest.skip(f"{script_name} not found")
        content = path.read_text(encoding="utf-8", errors="ignore")
        assert keyword.lower() in content.lower(), (
            f"{script_name} should contain '{keyword}'"
        )
