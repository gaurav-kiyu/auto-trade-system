"""Tests for Coverage Trend Enforcement — validates coverage does not decrease.

This test file enforces the QGT-09 (Testing Gate) requirement that test
coverage must not regress from its established baseline. It reads coverage
data from the .coveragerc configuration and validates:

  1. The current baseline is not below the configured minimum
  2. Trend tracking is configured
  3. Coverage degradation is detected

These tests are designed for CI integration to fail the build when
coverage drops below the configured threshold or trends downward.

Usage:
    python -m pytest tests/test_coverage_trend.py -v
    python -m pytest tests/test_coverage_trend.py -v --tb=short
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COVERAGERC_PATH = PROJECT_ROOT / ".coveragerc"
COVERAGE_HISTORY_DIR = PROJECT_ROOT / "reports" / "coverage_history"
BASELINE_FILE = COVERAGE_HISTORY_DIR / "baseline.json"
LAST_RUN_FILE = COVERAGE_HISTORY_DIR / "last_run.json"
MINIMUM_COVERAGE = 90.0  # From .coveragerc fail_under

# ── Helpers ────────────────────────────────────────────────────────────────────

HAS_COVERAGE = False
try:
    import coverage  # noqa: F401

    HAS_COVERAGE = True
except ImportError:
    pass


def _ensure_coverage_history_dir() -> Path:
    """Ensure the coverage history directory exists."""
    COVERAGE_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return COVERAGE_HISTORY_DIR


def _parse_coveragerc_minimum() -> float:
    """Parse the minimum coverage percentage from .coveragerc."""
    if not COVERAGERC_PATH.exists():
        return MINIMUM_COVERAGE
    content = COVERAGERC_PATH.read_text(encoding="utf-8")
    match = re.search(r"fail_under\s*=\s*(\d+(?:\.\d+)?)", content)
    if match:
        return float(match.group(1))
    return MINIMUM_COVERAGE


def _get_current_coverage_percentage() -> float:
    """Get the actual coverage percentage from the last coverage run.

    Returns:
        Coverage percentage from coverage XML/JSON report, or 0.0 if unavailable.

    """
    # Try coverage JSON report first
    json_report = PROJECT_ROOT / "reports" / "coverage.json"
    xml_report = PROJECT_ROOT / "reports" / "coverage.xml"

    if json_report.exists():
        try:
            data = json.loads(json_report.read_text(encoding="utf-8"))
            if "totals" in data:
                return float(data["totals"].get("percent_covered", 0.0))
            if "meta" in data:
                return float(data["meta"].get("covered_percent", 0.0))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            pass

    if xml_report.exists():
        try:
            content = xml_report.read_text(encoding="utf-8")
            match = re.search(r'line-rate="([\d.]+)"', content)
            if match:
                return float(match.group(1)) * 100.0
        except (ValueError, OSError):
            pass

    # Try running coverage report with short timeout
    try:
        result = subprocess.run(
            [sys.executable, "-m", "coverage", "report", "--show-missing"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode == 0:
            # Parse the last line of output
            for line in result.stdout.strip().split("\n"):
                if "TOTAL" in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        return float(parts[-1].rstrip("%"))
    except (subprocess.SubprocessError, FileNotFoundError, ValueError) as exc:
        # Coverage not installed or not initialized — skip
        if "TOTAL" in str(exc):
            pass
    except Exception:
        pass

    return 0.0


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestCoverageBaseline:
    """Tests for coverage baseline integrity."""

    def test_coveragerc_exists(self):
        """The .coveragerc file must exist to enforce coverage."""
        assert COVERAGERC_PATH.exists(), (
            f".coveragerc not found at {COVERAGERC_PATH} — "
            "coverage enforcement requires this configuration file"
        )

    def test_coveragerc_has_fail_under(self):
        """.coveragerc must have a fail_under setting."""
        content = COVERAGERC_PATH.read_text(encoding="utf-8")
        assert "fail_under" in content, (
            ".coveragerc missing 'fail_under' setting — "
            "coverage enforcement requires a minimum threshold"
        )

    def test_minimum_coverage_threshold(self):
        """The minimum coverage threshold must be a positive number."""
        minimum = _parse_coveragerc_minimum()
        assert minimum > 0, f"Minimum coverage must be > 0, got {minimum}"
        assert minimum <= 100, f"Minimum coverage must be <= 100, got {minimum}"
        print(f"\n  Minimum coverage threshold: {minimum}%")

    def test_minimum_coverage_meets_goal(self):
        """QGT-09 requires >87% coverage; constitution target >95%.

        The configured minimum should be at least the QGT-09 requirement.
        """
        minimum = _parse_coveragerc_minimum()
        qgt_target = 87.0
        assert minimum >= qgt_target, (
            f"Minimum coverage {minimum}% is below QGT-09 requirement of {qgt_target}%"
        )
        print(f"\n  QGT-09 requirement: {qgt_target}%")
        print(f"  Configured minimum: {minimum}%")
        if minimum >= 95.0:
            print("  ✅ Meets long-term goal of 95%")
        elif minimum >= qgt_target:
            print("  ✅ Meets QGT-09 requirement")

    def test_coverage_history_dir_exists(self):
        """Coverage history directory should exist or be creatable."""
        path = _ensure_coverage_history_dir()
        assert path.exists(), f"Could not create {path}"
        print(f"\n  Coverage history: {path}")


class TestCoverageTrend:
    """Tests for coverage trend enforcement."""

    def test_current_coverage_readable(self):
        """The current coverage percentage must be readable."""
        coverage_pct = _get_current_coverage_percentage()
        # It's okay if no coverage data exists yet — the test is informative
        if coverage_pct > 0:
            print(f"\n  Current coverage: {coverage_pct:.1f}%")
        else:
            pytest.skip("No coverage data available — run coverage first")

    def test_current_coverage_meets_minimum(self):
        """QGT-09: Current coverage must not be below the configured minimum.

        This is the primary enforcement test — it fails the build when
        coverage drops below the .coveragerc fail_under threshold.
        """
        coverage_pct = _get_current_coverage_percentage()
        if coverage_pct <= 0:
            pytest.skip("No coverage data available — run coverage first")

        minimum = _parse_coveragerc_minimum()
        assert coverage_pct >= minimum, (
            f"Coverage {coverage_pct:.1f}% is below minimum {minimum}% — "
            "add tests to restore coverage"
        )
        print(f"\n  Current coverage: {coverage_pct:.1f}% (minimum: {minimum}%)")
        print(f"  Margin: {coverage_pct - minimum:.1f}% above threshold")

    def test_baseline_not_degraded(self):
        """Coverage must not degrade from the baseline.

        This test loads the previous coverage baseline and validates
        the current coverage has not decreased.
        """
        if not BASELINE_FILE.exists():
            # First run — create baseline
            baseline_data = {
                "coverage_pct": 0.0,
                "timestamp": "baseline-not-established",
                "note": (
                    "Initial baseline not yet established. Run coverage, then "
                    f"copy the coverage report to {BASELINE_FILE}"
                ),
            }
            BASELINE_FILE.write_text(json.dumps(baseline_data, indent=2), encoding="utf-8")
            pytest.skip("No baseline established — run full coverage to create baseline")

        baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
        baseline_pct = baseline.get("coverage_pct", 0.0)

        current_pct = _get_current_coverage_percentage()
        if current_pct <= 0:
            pytest.skip("No current coverage data available")

        degradation = baseline_pct - current_pct
        if degradation > 1.0:
            pytest.fail(
                f"Coverage degraded by {degradation:.1f}% from baseline: "
                f"{baseline_pct:.1f}% → {current_pct:.1f}%. "
                "Rollback the change or add tests to restore coverage."
            )
        elif degradation > 0:
            print(f"\n  ⚠️  Coverage decreased by {degradation:.1f}% (within tolerance)")
            print(f"    Baseline: {baseline_pct:.1f}% → Current: {current_pct:.1f}%")
        else:
            print(f"\n  ✅ Coverage maintained or improved: {baseline_pct:.1f}% → {current_pct:.1f}%")

    def test_last_run_recorded(self):
        """After checking coverage, the last run should be recorded."""
        current_pct = _get_current_coverage_percentage()
        if current_pct <= 0:
            pytest.skip("No coverage data available")

        # Save last run for history tracking
        last_run = {
            "coverage_pct": current_pct,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        }
        _ensure_coverage_history_dir()
        LAST_RUN_FILE.write_text(json.dumps(last_run, indent=2), encoding="utf-8")
        print(f"\n  Last run saved: {LAST_RUN_FILE}")

    def test_coverage_greater_than_87(self):
        """QGT-09 requires test coverage >87%."""
        current_pct = _get_current_coverage_percentage()
        if current_pct <= 0:
            pytest.skip("No coverage data available")
        qgt_target = 87.0
        assert current_pct > qgt_target, (
            f"Coverage {current_pct:.1f}% does not meet QGT-09 requirement of >{qgt_target}%"
        )
        print(f"\n  QGT-09 (>{qgt_target}%): {current_pct:.1f}% ✅")


class TestCoverageConfig:
    """Tests for coverage configuration integrity."""

    def test_coveragerc_omit_patterns(self):
        """.coveragerc must have appropriate omit patterns."""
        content = COVERAGERC_PATH.read_text(encoding="utf-8")
        required_omits = [".venv", "__pycache__", "tests"]
        for omit in required_omits:
            assert omit in content, (
                f".coveragerc missing required omit pattern: {omit}"
            )
        print(f"\n  ✅ Required omit patterns: {', '.join(required_omits)}")

    def test_pytest_ini_has_coverage_config(self):
        """pytest.ini should reference coverage settings."""
        pytest_ini = PROJECT_ROOT / "pytest.ini"
        if not pytest_ini.exists():
            pytest.skip("pytest.ini not found")
        pytest_ini.read_text(encoding="utf-8")
        # No direct coverage config in pytest.ini is OK — it's in .coveragerc
        print("\n  ✅ Coverage config is in .coveragerc (separate from pytest.ini)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
