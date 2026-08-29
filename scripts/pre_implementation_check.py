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
import json
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.datetime_ist import now_ist

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
    "can_enter_position",
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

# ── Reviewed-change allowlist ────────────────────────────────────────────────
# Suppresses risk-pattern violations for (file, pattern) pairs that were
# explicitly REVIEWED and approved. Entries live in a git-tracked JSON file so
# the approval is auditable and survives fresh clones / CI.
#
# This is NOT a blanket bypass: only the exact (file, pattern) pair is
# allowed, and only for the risk-pattern check (RISK_SENSITIVE_PATTERNS).
# BLOCKED_CHANGES (test certification files) can never be allowlisted.

DEFAULT_ALLOWLIST_FILE = ROOT / "json/pre_implementation_allowlist.json"
_ALLOWLIST_SCHEMA_VERSION = 1


def load_allowlist(path: Path | None = None) -> dict:
    """Load the reviewed-change allowlist JSON (missing/corrupt -> empty)."""
    allow_path = path or DEFAULT_ALLOWLIST_FILE
    try:
        if allow_path.exists():
            data = json.loads(allow_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("entries"), list):
                return data
    except (json.JSONDecodeError, OSError):
        log.warning("Could not read allowlist %s - treating as empty", allow_path)
    return {"schema_version": _ALLOWLIST_SCHEMA_VERSION, "entries": []}


def _allowlist_entry_matches(entry: dict, file: str, pattern: str) -> bool:
    """True when an allowlist entry covers this (file, pattern) pair."""
    if not isinstance(entry, dict):
        return False
    entry_file = str(entry.get("file", "")).replace("\\", "/")
    target_file = file.replace("\\", "/")
    if entry.get("pattern") != pattern:
        return False
    if not entry_file or not target_file:
        return False
    # Exact match or suffix match (robust to ./ prefixes / relative paths)
    return entry_file == target_file or entry_file.endswith("/" + target_file) or target_file.endswith("/" + entry_file)


def is_allowlisted(file: str, pattern: str, allowlist: dict | None = None) -> bool:
    """Return True if (file, pattern) is covered by the reviewed-change allowlist."""
    data = allowlist if allowlist is not None else load_allowlist()
    return any(_allowlist_entry_matches(e, file, pattern) for e in data.get("entries", []))


def add_allowlist_entry(
    file: str,
    pattern: str,
    reason: str,
    reviewer: str = "operator",
    path: Path | None = None,
) -> dict:
    """Append a reviewed-change entry and persist the allowlist JSON.

    Returns the created entry. Raises ValueError if pattern is not a known
    risk-sensitive pattern (guards against typos) or the file is blocked.
    """
    if pattern not in RISK_SENSITIVE_PATTERNS:
        raise ValueError(
            f"Pattern '{pattern}' is not in RISK_SENSITIVE_PATTERNS - "
            "only reviewed risk-pattern changes can be allowlisted"
        )
    for blocked in BLOCKED_CHANGES:
        if blocked in file:
            raise ValueError(
                f"File '{file}' is BLOCKED and can never be allowlisted"
            )

    allow_path = path or DEFAULT_ALLOWLIST_FILE
    data = load_allowlist(allow_path)
    entries = data.setdefault("entries", [])
    # Replace any existing entry for the same (file, pattern) to keep the list clean
    entries = [
        e for e in entries
        if not (_allowlist_entry_matches(e, file, pattern))
    ]
    # Mint the next id from the max existing numeric id (dedupe may have removed
    # an entry, so len(entries)+1 could collide with a remaining id).
    _max_id = 0
    for _e in entries:
        _id_str = str(_e.get("id", ""))
        if _id_str.startswith("ALLOW-") and _id_str[6:].isdigit():
            _max_id = max(_max_id, int(_id_str[6:]))
    entry = {
        "id": f"ALLOW-{_max_id + 1:04d}",
        "file": file.replace("\\", "/"),
        "pattern": pattern,
        "reason": reason,
        "reviewer": reviewer,
        "date": now_ist().strftime("%Y-%m-%d"),
    }
    entries.append(entry)
    data["entries"] = entries
    data["schema_version"] = _ALLOWLIST_SCHEMA_VERSION
    allow_path.parent.mkdir(parents=True, exist_ok=True)
    allow_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    log.warning(
        "[ALLOWLIST] Reviewed change allowed: %s / %s (by %s)",
        entry["file"], entry["pattern"], reviewer,
    )
    return entry


def list_allowlist(path: Path | None = None) -> list[dict]:
    """Return the allowlist entries (empty list if none)."""
    return load_allowlist(path).get("entries", [])


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
    """Check that git history is accessible (Review #2).

    Uses ``git log -N --oneline`` (valid syntax). The previous form
    ``--oneline=-N`` was rejected by git as an unrecognized argument, which
    made the check always report history as inaccessible even inside a repo.
    """
    try:
        result = subprocess.run(
            ["git", "log", f"-{count}", "--oneline"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=15,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        log.warning("Git history check failed (not a git repo or git not available)")
        return False


def check_risk_controls(
    files: list[str],
    allowlist: dict | None = None,
) -> list[str]:
    """Check that risk controls are not being modified (Review #4).

    Uses git diff --cached to only flag ACTUAL changes to risk-sensitive
    patterns, not pre-existing references in the codebase. (file, pattern)
    pairs covered by the reviewed-change allowlist are skipped - they were
    explicitly reviewed and approved.
    """
    violations: list[str] = []
    for f in files:
        file_path = ROOT / f
        if not file_path.exists():
            continue
        try:
            # Get the diff for staged changes only
            # Avoid text=True on Windows (cp1252 encoding issues with git output)
            result = subprocess.run(
                ["git", "diff", "--cached", "-U0", "--", f],
                capture_output=True, text=False, cwd=str(ROOT), timeout=15,
            )
            diff_content = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
            # Fallback: if git diff is empty because file is outside the project
            # worktree (e.g. temp test file), scan full file content directly.
            # We check whether the file path is inside the project root to avoid
            # false positives for tracked files that happen to have no staged changes.
            if not diff_content.strip() and file_path.exists():
                try:
                    file_path.relative_to(ROOT)
                    # File is inside the project — no staged changes, so skip
                    pass
                except ValueError:
                    # File is outside the project — scan full content
                    diff_content = file_path.read_text(encoding="utf-8", errors="ignore")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            # Fallback: check full file content if diff is unavailable
            diff_content = file_path.read_text(encoding="utf-8", errors="ignore")
        for pattern in RISK_SENSITIVE_PATTERNS:
            if pattern in diff_content:
                if is_allowlisted(f, pattern, allowlist):
                    # Auditable: always surface when a risk violation was
                    # suppressed by the reviewed-change allowlist.
                    log.warning(
                        "[ALLOWLIST] Risk violation suppressed for %s / %s "
                        "(reviewed change on file)",
                        f, pattern,
                    )
                    continue
                violations.append(
                    f"RISK: {f} modifies '{pattern}' - confirm this change is safe"
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
        # Allow test/debug branches with pattern release/v0.0.0[-test_*]
        if branch.startswith("release/v0.0.0-test_") or branch in ("release/v0.0.0-test", "release/v0.0.0"):
            pass  # test/debug branch — skip release check
        # Allow legacy date-suffixed branches (migration period)
        elif branch.startswith(f"release/v{version}_"):
            pass  # legacy date-suffixed branch — allow during migration
        elif branch != expected_branch:
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
    ap.add_argument("--verify-analysis", action="store_true",
                    help="Verify Pre-Implementation Analysis Protocol compliance")
    # ── Reviewed-change allowlist management ────────────────────────────
    ap.add_argument("--allowlist", type=str, default=None,
                    help="Path to reviewed-change allowlist JSON (default: pre_implementation_allowlist.json)")
    ap.add_argument("--allow-add", type=str, default=None,
                    help="Add a reviewed-change entry for this FILE (requires --pattern + --reason)")
    ap.add_argument("--pattern", type=str, default=None,
                    help="Risk pattern to allow (must be in RISK_SENSITIVE_PATTERNS)")
    ap.add_argument("--reason", type=str, default="",
                    help="Human-readable reason this change was reviewed and approved")
    ap.add_argument("--reviewer", type=str, default="operator",
                    help="Who reviewed/approved the change (default: operator)")
    ap.add_argument("--list-allowlist", action="store_true",
                    help="Print the reviewed-change allowlist entries")
    args = ap.parse_args(argv)

    allowlist_path = Path(args.allowlist) if args.allowlist else None

    # ── Allowlist management commands (mutually exclusive with checks) ──
    if args.list_allowlist:
        entries = list_allowlist(allowlist_path)
        if not entries:
            print("Allowlist is empty.")
            return 0
        for e in entries:
            print(
                f"{e.get('id')}: {e.get('file')} / {e.get('pattern')} "
                f"[{e.get('date')}] by {e.get('reviewer')} - {e.get('reason', '')}"
            )
        return 0

    if args.allow_add:
        if not args.pattern or not args.reason:
            print("ERROR: --allow-add requires --pattern and --reason")
            return 1
        try:
            entry = add_allowlist_entry(
                file=args.allow_add,
                pattern=args.pattern,
                reason=args.reason,
                reviewer=args.reviewer,
                path=allowlist_path,
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        print(f"OK: allowlisted {entry['id']} {entry['file']} / {entry['pattern']}")
        print(f"    reason: {entry['reason']} (reviewer: {entry['reviewer']})")
        print("    NOTE: commit the allowlist JSON along with your change.")
        return 0

    all_violations: list[str] = []
    all_warnings: list[str] = []

    # ── Check 0: Pre-Implementation Analysis Protocol ──────────────────────
    protocol_doc = ROOT / "docs" / "PRE_IMPLEMENTATION_ANALYSIS_PROTOCOL.md"
    if not protocol_doc.exists():
        all_violations.append(
            "PRE-ANALYSIS PROTOCOL: docs/PRE_IMPLEMENTATION_ANALYSIS_PROTOCOL.md missing"
        )


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
        allowlist_data = load_allowlist(allowlist_path)
        risk_violations = check_risk_controls(args.files, allowlist=allowlist_data)
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

    # ── Check 8: Repository Hygiene & De-duplication ────────────────────
    prohibited_files = [
        ROOT / "start_opbuying_superapp.bat",
        ROOT / "QUICK_START_GUIDE.md",
        ROOT / "SETUP_AND_TRADING_GUIDE.md",
        ROOT / "STEP_BY_STEP_GUIDE.md",
    ]
    for pf in prohibited_files:
        if pf.exists():
            all_violations.append(f"HYGIENE DEDUPLICATION: Prohibited duplicate file found: {pf.name}")

    # Check for stale timestamped pptx files in docs/
    for pptx_file in (ROOT / "docs").glob("*.pptx"):
        if pptx_file.name not in ("STAKEHOLDER_PRESENTATION.pptx", "ARCHITECTURE_PRESENTATION.pptx"):
            all_violations.append(f"HYGIENE DEDUPLICATION: Stale duplicate pptx deck found: docs/{pptx_file.name}")

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
            "  - Verify ExpiryDayController.can_enter_position() is not removed",
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
        print(f"\n  [!] Warnings ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"    - {w}")

    if all_violations:
        print(f"\n  [X] VIOLATIONS ({len(all_violations)}):")
        for v in all_violations:
            print(f"    - {v}")
    else:
        print("\n  [OK] No violations found")

    if context_suggestions:
        print("\n" + "=" * 70)
        for line in context_suggestions:
            print(f"  {line}")

    print("\n" + "=" * 70)
    if all_violations:
        print("  RESULT: BLOCKED - resolve violations before proceeding")
        return 1
    else:
        print("  RESULT: PASSED - pre-implementation checks complete")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
