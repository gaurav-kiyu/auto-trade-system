#!/usr/bin/env python3
"""
AD-KIYU Artifact Cleanup Script v1.0

Removes all runtime test artifacts, leaked databases, cache files, and
temporary files from the repository root before release.

Run: python scripts/clean_artifacts.py [--dry-run] [--force]

Patterns matched:
    - Test artifact databases (*.db) in repo root
    - Runtime state files (trader_state*.json)
    - Cache files (benchmark_cache*.json)
    - Pytest cache directories
    - Log files in repo root
    - Temporary files (*.tmp, *.temp)
"""
from __future__ import annotations

import argparse
import glob
import logging
import os
import shutil
import sys
from pathlib import Path

_log = logging.getLogger(__name__)

# ── Patterns for files/directories to clean ──────────────────────────────────

FILE_PATTERNS: list[str] = [
    # Test artifact databases
    "test_recon_*.db",
    "*_test.db",
    "test_*.sqlite",
    # Runtime databases leaked to root
    "trades.db",
    "execution_state.db",
    "*_journal.db",
    "ml_tracker.db",
    "oi_snapshots.db",
    "manual_signals.db",
    "trader_state.json",
    "trader_state_*.json",
    "stock_trader_state.json",
    "stock_trader_state.json.bak",
    # Cache files
    "benchmark_cache*.json",
    "audit_trail.jsonl",
    "config_audit.log",
    "tg_fallback_alerts.log",
    "crash_recovery.log",
    # Config files (generated)
    "config.local.json",
    # Reports
    "reports/*.db",
    "reports/*.sqlite",
    "reports/_tmp*",
]

DIR_PATTERNS: list[str] = [
    ".pytest_cache/",
    "__pycache__/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".hypothesis/",
    "htmlcov/",
    ".coverage",
    "coverage.xml",
]

# Additional patterns for subdirectories
SUBDIR_PATTERNS: dict[str, list[str]] = {
    "data": [
        "*.db",
        "*.sqlite",
        "*.json",
    ],
    "logs": [
        "*.log",
        "*.bak",
        "*.jsonl",
    ],
    "backups": [
        "*.json",
        "*.db",
    ],
}


def collect_paths(root: Path, dry_run: bool = False) -> list[Path]:
    """Collect all file and directory paths matching cleanup patterns."""
    paths = []
    for pattern in FILE_PATTERNS:
        matches = list(root.glob(pattern))
        paths.extend(matches)
        if dry_run and matches:
            _log.info("  Would remove %d files matching %s", len(matches), pattern)

    for pattern in DIR_PATTERNS:
        p = root / pattern
        if p.exists():
            paths.append(p)
            if dry_run:
                _log.info("  Would remove directory: %s", p)

    for subdir, patterns in SUBDIR_PATTERNS.items():
        base = root / subdir
        if base.exists():
            for pattern in patterns:
                matches = list(base.glob(pattern))
                paths.extend(matches)
                if dry_run and matches:
                    _log.info("  Would remove %d files from %s/ matching %s", len(matches), subdir, pattern)

    return paths


def clean(paths: list[Path], force: bool = False) -> int:
    """Remove collected paths. Returns count of removed items."""
    removed = 0
    for p in paths:
        try:
            if p.is_dir():
                shutil.rmtree(p)
                _log.info("Removed directory: %s", p)
            else:
                p.unlink()
                _log.info("Removed file: %s", p)
            removed += 1
        except Exception as e:
            if force:
                _log.warning("Failed to remove %s (forced): %s", p, e)
            else:
                _log.error("Failed to remove %s: %s", p, e)
                raise
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AD-KIYU Artifact Cleanup — remove runtime test artifacts",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="List files that would be removed without removing them",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Continue on error instead of aborting",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        stream=sys.stdout,
    )

    root = Path.cwd()
    _log.info("AD-KIYU Artifact Cleanup")
    _log.info("Root directory: %s", root)
    _log.info("Mode: %s", "DRY RUN" if args.dry_run else "REMOVE")
    _log.info("")

    paths = collect_paths(root, dry_run=args.dry_run)
    _log.info("")
    _log.info("Found %d items to clean", len(paths))

    if not paths:
        _log.info("Nothing to clean — repository is tidy!")
        return 0

    if args.dry_run:
        _log.info("\nRun without --dry-run to remove these files.")
        return 0

    removed = clean(paths, force=args.force)
    _log.info("\nRemoved %d items. Repository is clean.", removed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
