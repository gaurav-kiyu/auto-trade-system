#!/usr/bin/env python3
"""
Pre-Implementation Compliance Check - Mandatory before ANY code change.

Enforces the Constitution's Mandatory Pre-Implementation Review:
  1. Review architecture
  2. Review historical versions
  3. Review audit reports
  4. Review risk controls
  5. Review security controls
  6. Review current implementation
  7. Review release state

Usage:
    python scripts/pre_implementation_check.py --files core/foo.py core/bar.py
    python scripts/pre_implementation_check.py --ci
    python scripts/pre_implementation_check.py --check-risk
    python scripts/pre_implementation_check.py --files core/foo.py --show-context

Exit code:
    0 = all checks pass
    1 = violations found (blocks implementation)
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
log = logging.getLogger("pre_implementation_check")


# ── Risk-sensitive file patterns ─────────────────────────────────────────────

RISK_SENSITIVE_FILES = [
    "core/services/risk_service.py",
    "index_app/index_trader.py",
    "core/adapters/broker_adapters.py",
    "core/config_bootstrap.py",
    "core/environment.py",
    "core/datetime_ist.py",
]

RISK_SENSITIVE_PATTERNS = [
    "_trip_hard_halt",
    "MAX_DAILY_LOSS",
    "MAX_DRAWDOWN",
    "SL_PCT",
    "TARGET_PCT",
    "TRAIL_PCT",
    "PORTFOLIO_MAX_SL_RISK_PCT",
    "expiry_entry_allowed",
    "get_position_size",
    "PAPER_MODE",
    "PaperBrokerAdapter",
    "datetime.now()",
]

BLOCKED_CHANGES = [
    "test_smoke.py",
    "test_broker_contract_certification.py",
    "test_exactly_once_certification.py",
]


# ── Checks ────────────────────────────────────────────────────────────────────


def check_architecture_doc_exists() -> bool:
    """Check that architecture documents exist (Review #1)."""
    docs_dir = ROOT / "docs"
    adr_dir = docs_dir / "adr"
    required_docs = [
        docs_dir / "ownership_matrix.md",
        docs_dir / "technical_debt.md",
        docs_dir / "REMEDIATION_REPORT.md",
        adr_dir / "0010-architecture-governance.md",
    ]
    missing = [str(d.relative_to(ROOT)) for d in required_docs if not d.exists()]
    if missing:
        log.warning("Architecture docs missing: %s", ", ".join(missing))
        return False
    return True


def check_git_history(count: int = 10) -> bool:
    """Check that git history is accessible (Review #2)."""
    try:
        result = subprocess.run(
            ["git", "log", f"--oneline=-{count}"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=15,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        log.warning("Git history check failed (not a git repo or git not available)")
        return False


def check_risk_controls(files: list[str]) -> list[str]:
    """Check that risk controls are not being modified (Review #4)."""
    violations: list[str] = []
    for f in files:
        file_path = ROOT / f
        if not file_path.exists():
            continue
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        for pattern in RISK_SENSITIVE_PATTERNS:
            if pattern in content:
                violations.append(
                    f"RISK: {f} contains '{pattern}' - verify risk control is not being modified"
                )
    return violations


def check_blocked_files(files: list[str]) -> list[str]:
    """Check that no blocked files are being modified."""
    violations: list[str] = []
    for f in files:
        for blocked in BLOCKED_CHANGES:
            if blocked in f:
                violations.append(
                    f"BLOCKED: {f} - '{blocked}' requires explicit human approval"
                )
    return violations


def check_risk_sensitive_files(files: list[str]) -> list[str]:
    """Check if any risk-sensitive files are being modified."""
    sensitive_touched: list[str] = []
    for f in files:
        for sensitive in RISK_SENSITIVE_FILES:
            if sensitive in f:
                sensitive_touched.append(f)
    return sensitive_touched


def _get_current_branch() -> str | None:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def check_release_state() -> list[str]:
    """Check release state and branch naming (Review #7)."""
    issues: list[str] = []
    version_file = ROOT / "VERSION"
    if not version_file.exists():
        issues.append("VERSION file not found")
    else:
        version = version_file.read_text(encoding="utf-8").strip()
        if not version:
            issues.append("VERSION file is empty")

    gitignore = ROOT / ".gitignore"
    if not gitignore.exists():
        issues.append(".gitignore not found")

    # ── Branch naming convention check (GAP-15) ──────────────────────
    branch = _get_current_branch()
    if branch and branch.startswith("release/") and version:
        expected_branch = f"release/v{version}"
        if branch != expected_branch:
            issues.append(
                f"BRANCH NAMING: Current branch '{branch}' does not match VERSION "
                f"'{version}'. Expected: '{expected_branch}'. "
                f"See docs/BRANCHING_CONVENTION.md"
            )

    return issues


# ── Main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--files", "-f", nargs="*", default=[],
                    help="Files to be modified (for impact analysis)")
    ap.add_argument("--ci", action="store_true",
                    help="CI mode (quiet, exit code only)")
    ap.add_argument("--check-risk", action="store_true",
                    help="Run detailed risk control check")
    ap.add_argument("--show-context", action="store_true",
                    help="Show context-gathering suggestions")
    args = ap.parse_args(argv)

    all_violations: list[str] = []
    all_warnings: list[str] = []

    # ── Check 1: Architecture documents ──────────────────────────────────
    arch_ok = check_architecture_doc_exists()
    if not arch_ok:
        all_warnings.append(
            "Architecture documents incomplete - review docs/ownership_matrix.md, "
            "docs/technical_debt.md, docs/adr/0010-architecture-governance.md"
        )

    # ── Check 2: Git history ─────────────────────────────────────────────
    git_ok = check_git_history()
    if not git_ok:
        all_warnings.append(
            "Git history not accessible - historical version review not possible"
        )

    # ── Check 4 & 5: Risk and security controls ──────────────────────────
    if args.files:
        risk_violations = check_risk_controls(args.files)
        all_violations.extend(risk_violations)

        blocked = check_blocked_files(args.files)
        all_violations.extend(blocked)

        sensitive = check_risk_sensitive_files(args.files)
        if sensitive:
            all_warnings.append(
                f"Risk-sensitive files modified: {', '.join(sensitive)} - "
                "review impact thoroughly"
            )

    # ── Check 7: Release state ───────────────────────────────────────────
    release_issues = check_release_state()
    all_violations.extend(
        f"RELEASE: {issue}" for issue in release_issues
    )

    # ── Context gathering suggestions ────────────────────────────────────
    context_suggestions: list[str] = []
    if args.show_context or args.files:
        context_suggestions = [
            "# Pre-Implementation Context Gathering",
            "# Review these files before implementing:",
        ]
        if args.files:
            for f in args.files:
                file_path = ROOT / f
                if file_path.exists():
                    context_suggestions.append(f"  - {f}  (to be modified)")
                    # Find related test files
                    test_path = ROOT / "tests" / f"test_{Path(f).name}"
                    if test_path.exists():
                        context_suggestions.append(f"  - tests/test_{Path(f).name}  (related test)")
                elif not file_path.exists():
                    context_suggestions.append(f"  - {f}  (NEW file - will be created)")

        # Always suggested readings
        context_suggestions.extend([
            "",
            "# Mandatory readings:",
            "  - CLAUDE.md",
            "  - docs/constitution_scoring_framework.md",
            "  - docs/technical_debt.md",
            "  - docs/ownership_matrix.md",
            "  - docs/REMEDIATION_REPORT.md",
            "",
            "# Safety checks:",
            "  - Verify MAX_DAILY_LOSS, MAX_DRAWDOWN, SL_PCT are not modified",
            "  - Verify _trip_hard_halt() is not bypassed",
            "  - Verify expiry_entry_allowed() is not removed",
            "  - Verify PaperBrokerAdapter invariant is not broken",
        ])

    # ── Output ───────────────────────────────────────────────────────────
    if args.ci:
        return 1 if all_violations else 0

    print("=" * 70)
    print("  PRE-IMPLEMENTATION COMPLIANCE CHECK")
    print("=" * 70)

    print(f"\n  Files to modify: {len(args.files) if args.files else 0}")
    for f in (args.files or []):
        print(f"    - {f}")

    print("\n  [1] Architecture documents: %s" % ("PRESENT" if arch_ok else "INCOMPLETE"))
    print("  [2] Git history: %s" % ("ACCESSIBLE" if git_ok else "NOT ACCESSIBLE"))
    print("  [7] Release state: %s" % ("OK" if not release_issues else "ISSUES"))

    if all_warnings:
        print("\n  [!] Warnings (%d):" % len(all_warnings))
        for w in all_warnings:
            print("    - %s" % w)

    if all_violations:
        print("\n  [X] VIOLATIONS (%d):" % len(all_violations))
        for v in all_violations:
            print("    - %s" % v)
    else:
        print("\n  [OK] No violations found")

    if context_suggestions:
        print("\n" + "=" * 70)
        for line in context_suggestions:
            print("  %s" % line)

    print("\n" + "=" * 70)
    if all_violations:
        print("  RESULT: BLOCKED - resolve violations before proceeding")
        return 1
    else:
        print("  RESULT: PASSED - pre-implementation checks complete")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
