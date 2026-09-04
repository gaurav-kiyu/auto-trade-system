"""Automated Testing Suite & Benchmark Bridge.

Bridges automated test execution, performance benchmarking, and health scorecarding
into the OPB Super-App platform.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("testing_suite_bridge")
ROOT = Path(__file__).resolve().parent.parent


class AutomatedTestingBridge:
    """Bridge for running automated tests, benchmark checks, and scorecards."""


    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or ROOT

    def run_unit_tests(self) -> dict[str, Any]:
        """Run core unit tests and return pass/fail report."""
        cmd = [sys.executable, "-m", "pytest", "tests/unit/", "-q"]
        start_t = time.monotonic()
        try:
            res = subprocess.run(cmd, cwd=self.root_dir, capture_output=True, text=True, timeout=60)
            elapsed = time.monotonic() - start_t
            passed = res.returncode == 0
            return {
                "suite": "unit_tests",
                "passed": passed,
                "exit_code": res.returncode,
                "elapsed_sec": round(elapsed, 2),
                "summary": res.stdout.splitlines()[-1] if res.stdout else "",
            }
        except Exception as err:
            return {"suite": "unit_tests", "passed": False, "error": str(err)}

    def run_hygiene_and_compliance(self) -> dict[str, Any]:
        """Run architecture and repository hygiene verification scripts."""
        hygiene_cmd = [sys.executable, "scripts/hygiene_check.py"]
        arch_cmd = [sys.executable, "scripts/check_architecture_compliance.py"]

        hygiene_res = subprocess.run(hygiene_cmd, cwd=self.root_dir, capture_output=True, text=True)
        arch_res = subprocess.run(arch_cmd, cwd=self.root_dir, capture_output=True, text=True)

        return {
            "hygiene_passed": hygiene_res.returncode == 0,
            "architecture_passed": arch_res.returncode == 0,
            "overall_pass": hygiene_res.returncode == 0 and arch_res.returncode == 0,
            "hygiene_exit_code": hygiene_res.returncode,
            "architecture_exit_code": arch_res.returncode,
            "hygiene_stdout": hygiene_res.stdout[-4000:] if hygiene_res.stdout else "",
            "hygiene_stderr": hygiene_res.stderr[-4000:] if hygiene_res.stderr else "",
            "architecture_stdout": arch_res.stdout[-4000:] if arch_res.stdout else "",
            "architecture_stderr": arch_res.stderr[-4000:] if arch_res.stderr else "",
        }

    def generate_full_scorecard(self) -> dict[str, Any]:
        """Generate a complete system health, test quality, and compliance scorecard."""
        unit_report = self.run_unit_tests()
        compliance_report = self.run_hygiene_and_compliance()

        score = 100.0
        if not unit_report.get("passed"):
            score -= 40.0
        if not compliance_report.get("hygiene_passed"):
            score -= 30.0
        if not compliance_report.get("architecture_passed"):
            score -= 30.0

        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "health_score": max(0.0, score),
            "status": "EXCELLENT" if score >= 90.0 else ("GOOD" if score >= 70.0 else "NEEDS_ATTENTION"),
            "unit_tests": unit_report,
            "compliance": compliance_report,
        }
