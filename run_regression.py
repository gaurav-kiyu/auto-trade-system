#!/usr/bin/env python3
"""
Targeted subset regression runner.

Usage:
    python run_regression.py                        # All new test files
    python run_regression.py --all                  # Full suite (all tests/)
    python run_regression.py --list                 # List all groups
    python run_regression.py --group core           # Core module tests only
    python run_regression.py --group governance     # Constitution/score/release tests
    python run_regression.py --group equity         # Equity trader tests
    python run_regression.py --group execution      # Execution hardening tests
    python run_regression.py <file1.py> <file2.py>  # Custom list of files
"""

from __future__ import annotations

import subprocess
import sys

TEST_DIR = "tests"

# ── Test groups ────────────────────────────────────────────────────────────
GROUPS: dict[str, list[str]] = {
    "core": [
        "test_simulation_engine",
        "test_orchestrator",
        "test_execution_stack",
        "test_feature_engine",
        "test_tier_engine",
        "test_config_validator",
        "test_morning_checklist",
        "test_walkforward_engine",
        "test_cost_accountant",
        "test_signal_refiner",
        "test_market_warmup",
        "test_time_of_day_filter",
        "test_signal_importer",
        "test_circuit_breaker_detector",
        "test_lot_size_validator",
        "test_equity_trader",
    ],
    "governance": [
        "test_constitution",
        "test_constitution_ai_gate",
        "test_score_system",
        "test_pre_implementation_check",
        "test_release_governance",
        "test_constitution_evidence_data",
        "test_operating_mode",
        "test_mandate_enforcer",
    ],
    "equity": [
        "test_equity_trader",
    ],
    "execution": [
        "test_execution_hardening_integration",
        "test_execution_stack",
    ],
    "new": [  # All newly created test files from recent sessions
        "test_expiry_day_controller",
        "test_system_mode",
        "test_signal_approval_workflow",
        "test_adaptive_behavior_governance",
        "test_component_health_monitor",
        "test_config_validator",
        "test_morning_checklist",
        "test_walkforward_engine",
        "test_cost_accountant",
        "test_execution_hardening_integration",
        "test_signal_refiner",
        "test_market_warmup",
        "test_time_of_day_filter",
        "test_signal_importer",
        "test_circuit_breaker_detector",
        "test_operating_mode",
        "test_mandate_enforcer",
        "test_lot_size_validator",
        "test_constitution_evidence_data",
        "test_equity_trader",
        "test_simulation_engine",
        "test_orchestrator",
        "test_execution_stack",
        "test_feature_engine",
        "test_tier_engine",
    ],
}


def run_tests(test_names: list[str], extra_args: list[str] | None = None) -> int:
    """Run pytest on the given list of test file names."""
    args = extra_args or []
    paths = [f"{TEST_DIR}/{name}.py" for name in test_names]
    cmd = [sys.executable, "-m", "pytest", *paths, "-q", *args]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode


def main() -> None:
    args = sys.argv[1:]
    if not args:
        # Default: run the "new" group
        print("No arguments — running 'new' group. Use --help for options.")
        sys.exit(run_tests(GROUPS["new"]))

    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    if "--list" in args:
        print("Available test groups:")
        for name, tests in sorted(GROUPS.items()):
            print(f"  {name:16s}  ({len(tests)} test files)")
        return

    if "--all" in args:
        cmd = [sys.executable, "-m", "pytest", TEST_DIR, "-q"]
        print(f"Running full suite: {' '.join(cmd)}")
        subprocess.run(cmd)
        return

    if "--group" in args:
        idx = args.index("--group") + 1
        if idx >= len(args):
            print("Error: --group requires a group name")
            sys.exit(1)
        group_name = args[idx]
        if group_name not in GROUPS:
            print(f"Error: unknown group '{group_name}'")
            print(f"Available: {', '.join(sorted(GROUPS.keys()))}")
            sys.exit(1)
        sys.exit(run_tests(GROUPS[group_name]))

    # Otherwise, treat as a list of file paths or test names
    test_names: list[str] = []
    for arg in args:
        if arg.startswith("tests/"):
            arg = arg.replace("tests/", "").replace(".py", "")
        elif arg.endswith(".py"):
            arg = arg.replace(".py", "")
        test_names.append(arg)
    sys.exit(run_tests(test_names))


if __name__ == "__main__":
    main()
