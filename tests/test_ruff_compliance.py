"""Regression tests for ruff lint compliance in core/ and scripts/.

These tests verify that previously auto-fixed ruff rule categories
remain clean, preventing re-introduction of the same lint issues.

Cleaned categories:
  - F541   f-string-missing-placeholders    (35 fixed)
  - I001   unsorted-imports                 (12 fixed)
  - UP032  f-string-conversion               (1 fixed)
  - RUF100 unused-noqa                      (13 fixed Round 2)
  - F401   unused-import                   (22 fixed Round 3)
  - F841   unused-variable                 (15 fixed Round 4)

Known remaining issues (manual fix needed):
  - E701  multiple-statements-on-one-line   (6 remaining)
  - E741  ambiguous-variable-name           (3 remaining)
  - W291  trailing-whitespace              (2 remaining, in docstrings)
  - W293  blank-line-with-whitespace       (1 remaining, in docstring)

Not tracked (no auto-fix available):
  - E731  lambda-assignment                (1, in event_system.py)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ruff rule codes that were fully cleaned in the 2026-07-28 auto-fix session.
# These should remain at zero errors. Any violation means a regression.
_CLEANED_RULES = [
    "F541",  # f-string-missing-placeholders
    "I001",  # unsorted-imports
    "UP032",  # f-string (old % formatting)
    "RUF100",  # unused-noqa (cleaned Round 2)
    "F401",  # unused-import (cleaned Round 3)
    "F841",  # unused-variable (cleaned Round 4)
]

# Directories to scan for lint regression
_SCAN_DIRS = ["core", "scripts"]

# ── Known remaining issues (not expected to trigger failures) ────────────
# These are documented here so that if they're ever fixed, they can be
# promoted to _CLEANED_RULES above.
_KNOWN_REMAINING: dict[str, int] = {
    "E701": 0,  # multiple-statements-on-one-line-colon — all fixed
    "E741": 0,  # ambiguous-variable-name — all fixed
    "W291": 0,  # trailing-whitespace — all fixed
    "W293": 0,  # blank-line-with-whitespace — all fixed
}


def _run_ruff_select(rules: list[str], targets: list[str]) -> tuple[int, str]:
    """Run ``ruff check`` scoped to specific rules.

    Returns ``(exit_code, stdout)``.
    """
    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        f"--select={','.join(rules)}",
        *targets,
        "--statistics",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode, result.stdout


# ── Tests ─────────────────────────────────────────────────────────────────


class TestRuffCleanedRules:
    """Previously cleaned ruff rule categories should have zero violations.

    If any of these tests fail, it means a lint issue was re-introduced.
    Run ``python -m ruff check core/ scripts/ --fix`` to auto-correct.
    """

    @pytest.mark.parametrize("rule", _CLEANED_RULES, ids=_CLEANED_RULES)
    def test_cleaned_rule_has_zero_errors(self, rule: str) -> None:
        """Rule ``{rule}`` should have zero violations across core/ and scripts/."""
        exit_code, stdout = _run_ruff_select([rule], _SCAN_DIRS)
        # Parse the summary line from --statistics output
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        violations = 0
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1].startswith(rule):
                violations = int(parts[0])
                break
        assert violations == 0, (
            f"Rule {rule} has {violations} violation(s) — "
            f"a regression from the cleaned state. "
            f"Run `python -m ruff check core/ scripts/ --fix` to resolve.\n"
            f"{stdout}"
        )
        assert exit_code == 0, (
            f"ruff crashed on rule {rule}:\n{stdout}"
        )

    def test_all_cleaned_rules_summary(self) -> None:
        """Aggregate check: all cleaned rules combined should have zero violations."""
        exit_code, stdout = _run_ruff_select(_CLEANED_RULES, _SCAN_DIRS)
        violations = 0
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 2 and any(
                parts[1].startswith(r) for r in _CLEANED_RULES
            ):
                violations += int(parts[0])

        assert violations == 0, (
            f"{violations} total violation(s) across cleaned rules "
            f"({', '.join(_CLEANED_RULES)}).\n"
            f"Run `python -m ruff check core/ scripts/ --fix` to resolve.\n"
            f"{stdout}"
        )
        assert exit_code in (0, 1), (
            f"ruff exited with code {exit_code}:\n{stdout}"
        )


class TestRuffKnownRemaining:
    """Track known remaining lint issues — warn if count changes.

    These tests document the current state of unresolved lint issues.
    If the count decreases (good), the fix should be celebrated and this
    test updated. If the count increases (bad), new issues were introduced.
    """

    @pytest.mark.parametrize(
        "rule,expected",
        list(_KNOWN_REMAINING.items()),
        ids=list(_KNOWN_REMAINING.keys()),
    )
    def test_known_remaining_count(self, rule: str, expected: int) -> None:
        """Rule ``{rule}`` should have exactly ``{expected}`` violations."""
        exit_code, stdout = _run_ruff_select([rule], _SCAN_DIRS)
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        actual = 0
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1].startswith(rule):
                actual = int(parts[0])
                break

        assert actual == expected, (
            f"Rule {rule} violation count changed: "
            f"expected {expected}, got {actual}. "
            f"{'🎉 Fewer violations — update _KNOWN_REMAINING!' if actual < expected else '⚠️ More violations — new issues introduced!'}"
        )


