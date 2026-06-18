#!/usr/bin/env python3
"""
Repository Hygiene Checker - Enforces the Constitution's Mandatory Repository Hygiene.

The Constitution mandates:
  Release artifacts MUST NOT contain:
    .venv, __pycache__, .pytest_cache, .ruff_cache, build residue,
    temporary files, stale reports, orphaned assets, duplicate implementations

  Repository must remain pristine.

Usage:
    python scripts/hygiene_check.py                        # Scan only (report)
    python scripts/hygiene_check.py --clean                # Scan + remove artifacts
    python scripts/hygiene_check.py --json                 # JSON output
    python scripts/hygiene_check.py --ci                   # CI mode (exit code only)
    python scripts/hygiene_check.py --check-gitignore      # Verify .gitignore coverage
    python scripts/hygiene_check.py --check-reports        # Check for stale reports

Exit code:
    0 = no issues found
    1 = issues found (or --clean had failures)
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
log = logging.getLogger("hygiene_check")

# ── Forbidden artifact patterns ──────────────────────────────────────────────

FORBIDDEN_DIRS: list[str] = [
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".hypothesis",
    ".venv",
    "venv",
    "env",
    ".nox",
    ".tox",
    "build",
    "dist",
    "*.egg-info",
    ".eggs",
]

FORBIDDEN_FILES: list[str] = [
    "*.pyc",
    "*.pyo",
    "*.egg",
    "*.so",
    "*.dll",
    "*.spec",
]

STALE_PATTERNS: dict[str, list[str]] = {
    "temp_files": ["*.tmp", "*.temp", "*.log.bak", "*.bak", "*.swp"],
    "stale_reports": ["reports/*.html", "reports/*.xml", "reports/*.json"],
    "ide_files": [".vscode/", ".idea/", "*.iml", ".DS_Store", "Thumbs.db"],
}

# .gitignore entries that should exist
REQUIRED_GITIGNORE_ENTRIES: list[str] = [
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".hypothesis/",
    ".venv/",
    "venv/",
    "build/",
    "dist/",
    "*.egg-info/",
    ".eggs/",
    "*.egg",
    "*.so",
    "*.spec",
    ".env",
    ".env.local",
    "*.db",
    "trader_state.json",
    "OPBuying_INDEX_Launcher.exe",
    "logs/",
    "data/",
    "reports/",
]


@dataclass
class HygieneIssue:
    category: str
    path: str
    description: str
    auto_cleanable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "path": self.path,
            "description": self.description,
            "auto_cleanable": self.auto_cleanable,
        }


@dataclass
class HygieneReport:
    timestamp: float
    issues: list[HygieneIssue]
    total: int
    auto_cleanable: int
    clean_performed: bool
    clean_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_issues": self.total,
            "auto_cleanable": self.auto_cleanable,
            "clean_performed": self.clean_performed,
            "clean_ok": self.clean_ok,
            "issues": [i.to_dict() for i in self.issues],
        }


# ── Scanners ─────────────────────────────────────────────────────────────────


def scan_forbidden_dirs() -> list[HygieneIssue]:
    """Scan for forbidden directories in the tree."""
    issues: list[HygieneIssue] = []
    for pattern in FORBIDDEN_DIRS:
        # rglob for directory patterns (handle globs)
        if pattern.startswith("*."):
            # Extension-based directory pattern (e.g., *.egg-info)
            ext = pattern.lstrip("*.")
            for path in ROOT.rglob(f"*.{ext}"):
                if path.is_dir() and not _is_gitignored(path):
                    issues.append(HygieneIssue(
                        category="FORBIDDEN_DIR",
                        path=str(path.relative_to(ROOT)),
                        description=f"Forbidden directory: {pattern}",
                        auto_cleanable=True,
                    ))
        else:
            for path in ROOT.rglob(pattern):
                if path.is_dir() and not _is_gitignored(path):
                    issues.append(HygieneIssue(
                        category="FORBIDDEN_DIR",
                        path=str(path.relative_to(ROOT)),
                        description=f"Forbidden directory: {pattern}",
                        auto_cleanable=True,
                    ))
    return issues


def scan_forbidden_files() -> list[HygieneIssue]:
    """Scan for forbidden file patterns."""
    issues: list[HygieneIssue] = []
    for pattern in FORBIDDEN_FILES:
        for path in ROOT.rglob(pattern):
            if path.is_file() and not _is_gitignored(path):
                issues.append(HygieneIssue(
                    category="FORBIDDEN_FILE",
                    path=str(path.relative_to(ROOT)),
                    description=f"Forbidden file: {pattern}",
                    auto_cleanable=True,
                ))
    return issues


def scan_stale_artifacts() -> list[HygieneIssue]:
    """Scan for stale/leftover artifacts."""
    issues: list[HygieneIssue] = []
    for category, patterns in STALE_PATTERNS.items():
        for pattern in patterns:
            if pattern.endswith("/"):
                # Directory pattern
                dir_name = pattern.rstrip("/")
                for path in ROOT.rglob(dir_name):
                    if path.is_dir() and not _is_gitignored(path):
                        issues.append(HygieneIssue(
                            category=category.upper(),
                            path=str(path.relative_to(ROOT)),
                            description=f"Stale artifact directory: {pattern}",
                            auto_cleanable=True,
                        ))
            else:
                for path in ROOT.rglob(pattern):
                    if path.is_file() and not _is_gitignored(path):
                        issues.append(HygieneIssue(
                            category=category.upper(),
                            path=str(path.relative_to(ROOT)),
                            description=f"Stale artifact: {pattern}",
                            auto_cleanable=True,
                        ))

    # Check for built executable artifacts
    built_exes = [
        ROOT / "OPBuying_INDEX_Launcher.exe",
        ROOT / "dist" / "OPBuying_INDEX_Launcher.exe",
    ]
    for exe_path in built_exes:
        if exe_path.exists() and not _is_gitignored(exe_path):
            issues.append(HygieneIssue(
                category="BUILT_ARTIFACT",
                path=str(exe_path.relative_to(ROOT)),
                description="Built executable not in .gitignore",
                auto_cleanable=True,
            ))

    return issues


def scan_duplicate_implementations() -> list[HygieneIssue]:
    """Scan for left-over backup files and orphaned copies (.py.bak, .py.orig)."""
    issues: list[HygieneIssue] = []

    # Scan for .py.bak or .py.orig files (backups left in tree)
    for path in ROOT.rglob("*.py.*"):
        if path.suffix in (".bak", ".orig", ".backup", ".old"):
            if not _is_gitignored(path):
                issues.append(HygieneIssue(
                    category="DUPLICATE_IMPL",
                    path=str(path.relative_to(ROOT)),
                    description=f"Backup file left in tree: {path.name}",
                    auto_cleanable=True,
                ))

    return issues


def check_gitignore() -> list[HygieneIssue]:
    """Verify .gitignore covers all required entries."""
    issues: list[HygieneIssue] = []
    gitignore_path = ROOT / ".gitignore"
    if not gitignore_path.exists():
        issues.append(HygieneIssue(
            category="MISSING_GITIGNORE",
            path=".gitignore",
            description=".gitignore file is missing",
        ))
        return issues

    content = gitignore_path.read_text(encoding="utf-8")
    for entry in REQUIRED_GITIGNORE_ENTRIES:
        if entry not in content:
            issues.append(HygieneIssue(
                category="GITIGNORE_GAP",
                path=".gitignore",
                description=f"Missing .gitignore entry: {entry}",
                auto_cleanable=False,
            ))

    return issues


def check_stale_reports() -> list[HygieneIssue]:
    """Check for stale or oversized report files."""
    issues: list[HygieneIssue] = []
    reports_dir = ROOT / "reports"
    if not reports_dir.is_dir():
        return issues

    for report_file in reports_dir.rglob("*"):
        if report_file.is_file():
            # Flag files older than 30 days as stale
            age_days = (time.time() - report_file.stat().st_mtime) / 86400
            if age_days > 30:
                issues.append(HygieneIssue(
                    category="STALE_REPORT",
                    path=str(report_file.relative_to(ROOT)),
                    description=f"Stale report ({age_days:.0f} days old)",
                    auto_cleanable=True,
                ))

    return issues


# ── Helpers ──────────────────────────────────────────────────────────────────


_GITIGNORED_PATTERNS: list[str] | None = None


def _load_gitignore_patterns() -> list[str]:
    """Cache .gitignore patterns for fast in-process matching.

    Reads the gitignore once and caches the patterns so we can
    check paths without spawning a subprocess per path.
    """
    global _GITIGNORED_PATTERNS
    if _GITIGNORED_PATTERNS is not None:
        return _GITIGNORED_PATTERNS

    gitignore_path = ROOT / ".gitignore"
    if not gitignore_path.exists():
        _GITIGNORED_PATTERNS = []
        return _GITIGNORED_PATTERNS

    patterns: list[str] = []
    for line in gitignore_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    _GITIGNORED_PATTERNS = patterns
    return patterns


def _is_gitignored(path: Path) -> bool:
    """Check if a path is gitignored using cached .gitignore patterns.

    Uses prefix/suffix/glob matching against cached patterns.
    Handles:
      - Simple names:  __pycache__/
      - Recursive:    **/__pycache__/
      - Glob:         *.pyc, *.so
      - Directory:    logs/, builds/
    """
    import fnmatch

    patterns = _load_gitignore_patterns()
    if not patterns:
        return False

    rel = str(path.relative_to(ROOT)).replace("\\", "/")

    for pattern in patterns:
        # Strip leading ./ if present
        p = pattern[2:] if pattern.startswith("./") else pattern

        # Strip leading **/ for recursive matching, then check name-only
        raw_name = p
        if p.startswith("**/"):
            raw_name = p[3:]

        # Always try matching just the filename first (handles **/ patterns)
        if fnmatch.fnmatch(path.name, raw_name):
            return True

        # Directory-only patterns (end with /)
        if raw_name.endswith("/"):
            base = raw_name.rstrip("/")
            # Check if any part of the path matches
            rel_parts = rel.split("/")
            if base in rel_parts:
                return True
            if fnmatch.fnmatch(rel, raw_name) or fnmatch.fnmatch(rel, f"{base}/*"):
                return True
            continue

        # Glob patterns
        if "*" in p:
            if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(path.name, p):
                return True
            # Also check if any path segment matches the glob
            if any(fnmatch.fnmatch(part, p) for part in rel.split("/")):
                return True
            continue

        # Exact match or prefix match (directory prefix)
        if rel == p or rel.startswith(p + "/"):
            return True

        # Check if the name appears as any path component
        if p.rstrip("/") in rel.split("/"):
            return True

    return False


def clean_issues(issues: list[HygieneIssue]) -> list[tuple[HygieneIssue, bool]]:
    """Remove auto-cleanable artifacts. Returns (issue, success) pairs."""
    results: list[tuple[HygieneIssue, bool]] = []
    for issue in issues:
        if not issue.auto_cleanable:
            results.append((issue, False))
            continue

        full_path = ROOT / issue.path
        try:
            if full_path.is_dir():
                shutil.rmtree(full_path)
                results.append((issue, True))
            elif full_path.is_file():
                full_path.unlink()
                results.append((issue, True))
            else:
                # Try glob-based removal
                parent = full_path.parent
                pattern = full_path.name
                for matched in parent.rglob(pattern):
                    if matched.is_dir():
                        shutil.rmtree(matched)
                    else:
                        matched.unlink()
                results.append((issue, True))
        except (OSError, PermissionError, shutil.Error) as e:
            log.warning("Failed to clean %s: %s", issue.path, e)
            results.append((issue, False))

    return results


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clean", action="store_true", help="Remove auto-cleanable artifacts")
    ap.add_argument("--json", "-j", action="store_true", help="JSON output")
    ap.add_argument("--ci", action="store_true", help="CI mode (exit code only)")
    ap.add_argument("--check-gitignore", action="store_true", help="Verify .gitignore only")
    ap.add_argument("--check-reports", action="store_true", help="Check stale reports only")
    args = ap.parse_args(argv)

    all_issues: list[HygieneIssue] = []

    if args.check_gitignore:
        all_issues = check_gitignore()
    elif args.check_reports:
        all_issues = check_stale_reports()
    else:
        # Full scan
        all_issues.extend(scan_forbidden_dirs())
        all_issues.extend(scan_forbidden_files())
        all_issues.extend(scan_stale_artifacts())
        all_issues.extend(scan_duplicate_implementations())
        all_issues.extend(check_gitignore())
        all_issues.extend(check_stale_reports())

    auto_cleanable_count = sum(1 for i in all_issues if i.auto_cleanable)

    # Clean if requested
    clean_performed = False
    clean_ok = True
    if args.clean and auto_cleanable_count > 0:
        clean_performed = True
        auto_issues = [i for i in all_issues if i.auto_cleanable]
        results = clean_issues(auto_issues)
        clean_ok = all(success for _, success in results)
        # Re-scan after clean
        all_issues.clear()
        all_issues.extend(scan_forbidden_dirs())
        all_issues.extend(scan_forbidden_files())
        all_issues.extend(scan_stale_artifacts())
        remaining_auto = sum(1 for i in all_issues if i.auto_cleanable)
        if remaining_auto == 0:
            all_issues = [i for i in all_issues if not i.auto_cleanable]

    report = HygieneReport(
        timestamp=time.time(),
        issues=all_issues,
        total=len(all_issues),
        auto_cleanable=auto_cleanable_count,
        clean_performed=clean_performed,
        clean_ok=clean_ok,
    )

    has_issues = len(all_issues) > 0

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 1 if has_issues else 0

    if args.ci:
        return 1 if has_issues else 0

    # ── Print report ─────────────────────────────────────────────────────
    print("=" * 70)
    print("  REPOSITORY HYGIENE CHECK")
    print("=" * 70)

    if clean_performed:
        if clean_ok:
            print("  [OK] Clean operation completed successfully")
        else:
            print("  [!] Clean completed with some failures")

    print(f"  Total issues: {len(all_issues)}")
    print(f"  Auto-cleanable: {auto_cleanable_count}")
    print()
    print("  Categories:")
    print()

    categories: dict[str, list[HygieneIssue]] = {}
    for issue in all_issues:
        categories.setdefault(issue.category, []).append(issue)

    for cat_name, cat_issues in sorted(categories.items()):
        print(f"  [{cat_name}] ({len(cat_issues)} issue(s))")
        for issue in cat_issues[:5]:
            marker = "[CLEANABLE]" if issue.auto_cleanable else "[MANUAL]"
            print(f"       {marker} {issue.path}: {issue.description}")
        if len(cat_issues) > 5:
            print(f"       ... and {len(cat_issues) - 5} more")

    print()
    print("=" * 70)
    if has_issues:
        print("  RESULT: ISSUES FOUND")
        if auto_cleanable_count > 0:
            print(f"    ({auto_cleanable_count} issues can be auto-cleaned with --clean)")
        return 1
    else:
        print("  RESULT: REPOSITORY IS PRISTINE")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
