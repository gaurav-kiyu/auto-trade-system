"""Tests for scripts/run_constitution_checks.py — Unified Constitution System Check.

Verifies the script imports correctly, produces valid output,
and properly validates all 15 constitution modules.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def checker_script() -> str:
    """Return the path to the constitution check script."""
    return str(Path(__file__).resolve().parent.parent / "scripts" / "run_constitution_checks.py")


# ── Basic Import Tests ───────────────────────────────────────────────────────


class TestScriptImport:
    def test_script_exists(self, checker_script: str):
        """Verify the script file exists."""
        assert Path(checker_script).exists(), f"Script not found: {checker_script}"

    def test_modules_defined(self):
        """Verify all 15 modules are defined in the registry."""
        import scripts.run_constitution_checks as mod
        assert len(mod.MODULES) == 15, f"Expected 15 modules, got {len(mod.MODULES)}"

    def test_all_modules_have_required_keys(self):
        """Verify every module entry has name, key, import, factory."""
        import scripts.run_constitution_checks as mod
        required = {"name", "key", "import", "factory"}
        for entry in mod.MODULES:
            assert required.issubset(entry.keys()), f"Module {entry.get('name')} missing keys: {required - entry.keys()}"


class TestModuleCheck:
    def test_check_result_dataclass(self):
        """Verify ModuleCheckResult works correctly."""
        import scripts.run_constitution_checks as _chk
        result = _chk.ModuleCheckResult(
            name="Test", key="test", status="PASS", stats={"available": True},
        )
        assert result.name == "Test"
        assert result.status == "PASS"
        d = result.to_dict()
        assert d["status"] == "PASS"
        assert d["stats"]["available"] is True

    def test_check_report_properties(self):
        """Verify CheckReport computes correct stats."""
        import scripts.run_constitution_checks as _chk
        report = _chk.CheckReport()
        report.results = [
            _chk.ModuleCheckResult(name="A", key="a", status="PASS"),
            _chk.ModuleCheckResult(name="B", key="b", status="PASS"),
            _chk.ModuleCheckResult(name="C", key="c", status="FAIL"),
        ]
        report.end_time = report.start_time + 1.0
        assert report.total == 3
        assert report.passed == 2
        assert report.failed == 1
        assert round(report.score_pct, 1) == 66.7
        assert report.duration_sec == 1.0

    def test_report_summary_text(self):
        """Verify summary_text produces readable output."""
        import scripts.run_constitution_checks as _chk
        report = _chk.CheckReport()
        report.results = [
            _chk.ModuleCheckResult(name="AI Security Gate", key="ai_security_gate", status="PASS"),
        ]
        report.end_time = report.start_time + 0.1
        text = report.summary_text()
        assert "CONSTITUTION" in text
        assert "SYSTEM CHECK" in text
        assert "1" in text  # total


class TestRunChecks:
    def test_run_checks_returns_report(self):
        """Verify run_checks returns a valid CheckReport."""
        import scripts.run_constitution_checks as _chk
        report = _chk.run_checks()
        assert isinstance(report, _chk.CheckReport)
        assert report.total == 15  # All modules

    def test_run_checks_all_pass(self):
        """Verify all 10 modules pass when imported in-process."""
        import scripts.run_constitution_checks as _chk
        report = _chk.run_checks()
        assert report.passed == 15, f"Expected 15 passed, got {report.passed}"
        for r in report.results:
            assert r.status == "PASS", f"Module {r.name} failed: {r.error}"

    def test_run_checks_module_filter(self):
        """Verify module filter works correctly."""
        import scripts.run_constitution_checks as _chk
        report = _chk.run_checks(module_filter="ai_security_gate")
        assert report.total == 1
        assert report.results[0].key == "ai_security_gate"

    def test_run_checks_invalid_filter(self):
        """Verify invalid module filter returns no results."""
        import scripts.run_constitution_checks as _chk
        report = _chk.run_checks(module_filter="nonexistent_module")
        assert report.total == 0


class TestReportSerialization:
    def test_to_dict_serializable(self):
        """Verify to_dict produces JSON-serializable output."""
        import scripts.run_constitution_checks as _chk
        report = _chk.run_checks()
        d = report.to_dict()
        json_str = json.dumps(d)
        assert len(json_str) > 0
        loaded = json.loads(json_str)
        assert loaded["total"] == 15
        assert loaded["passed"] >= 0
        assert 0 <= loaded["score_pct"] <= 100
        assert len(loaded["results"]) == 15

    def test_result_to_dict(self):
        """Verify individual result serialization."""
        import scripts.run_constitution_checks as _chk
        result = _chk.ModuleCheckResult(
            name="Test", key="test", status="PASS", duration_ms=12.34, stats={"key": "val"},
        )
        d = result.to_dict()
        assert d["name"] == "Test"
        assert d["duration_ms"] == 12.34


class TestCliIntegration:
    def test_cli_json_output(self, checker_script: str):
        """Verify --json flag produces valid JSON on stdout."""
        result = subprocess.run(
            [sys.executable, checker_script, "--json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total"] == 15
        assert data["passed"] == 15
        assert data["score_pct"] == 100.0

    def test_cli_module_filter(self, checker_script: str):
        """Verify --module filter works."""
        result = subprocess.run(
            [sys.executable, checker_script, "--json", "--module", "ai_security_gate"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total"] == 1
        assert data["results"][0]["key"] == "ai_security_gate"

    def test_cli_quiet_mode(self, checker_script: str):
        """Verify --quiet suppresses output."""
        result = subprocess.run(
            [sys.executable, checker_script, "--quiet"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert len(result.stdout.strip()) == 0


class TestCliGate:
    def test_check_min_passes(self, checker_script: str):
        """Verify --check-min 90 passes when all modules work."""
        result = subprocess.run(
            [sys.executable, checker_script, "--check-min", "90"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_check_min_100_passes(self, checker_script: str):
        """Verify --check-min 100 passes when all modules pass."""
        result = subprocess.run(
            [sys.executable, checker_script, "--check-min", "100"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
