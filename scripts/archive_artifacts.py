#!/usr/bin/env python3
"""
AD-KIYU Artifact Archiver v1.0

Compresses old runtime artifacts (logs, reports, backups, databases) into
dated ZIP archives for retention before cleanup. Designed to be run as a
weekly maintenance task (e.g., Sunday EOD).

Usage:
    python scripts/archive_artifacts.py                          # archive everything (defaults)
    python scripts/archive_artifacts.py --days 14                # archive items older than 14 days
    python scripts/archive_artifacts.py --dry-run                # show what would be archived
    python scripts/archive_artifacts.py --skip-reports           # skip reports/ directory
    python scripts/archive_artifacts.py --output-dir /backups    # custom output directory
    python scripts/archive_artifacts.py --verbose                # detailed logging
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

_log = logging.getLogger(__name__)

# ── Default paths ──────────────────────────────────────────────────────────
ARCHIVE_DIR_NAME = "archives"
LOG_DIR = "logs"
REPORT_DIR = "reports"
BACKUP_DIR = "backups"
DATA_DIR = "data"

# ── File patterns to include ────────────────────────────────────────────────
INCLUDE_PATTERNS: dict[str, list[str]] = {
    "logs": [
        "*.log",
        "*.log.*",
        "*.jsonl",
        "*.bak",
    ],
    "reports": [
        "*.txt",
        "*.json",
        "*.html",
        "*.pdf",
        "*.csv",
    ],
    "backups": [
        "*.json",
        "*.db",
        "*.sqlite",
        "*.bak",
    ],
    "data": [
        "*.json",
        "*.csv",
        "*.log",
    ],
}

# ── Files/dirs to always exclude ────────────────────────────────────────────
EXCLUDE_NAMES = {".gitkeep", "latest", "current"}


def _is_older_than(path: Path, max_age_days: int, *, allow_missing: bool = False) -> bool:
    """Check if a file's mtime is older than max_age_days."""
    if not path.exists():
        return allow_missing
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        return mtime < cutoff
    except (OSError, ValueError):
        return False


def _collect_archivable(
    root: Path,
    category: str,
    subdir: str,
    patterns: list[str],
    max_age_days: int,
    *,
    dry_run: bool = False,
) -> list[Path]:
    """Collect files matching patterns in a subdirectory that are old enough to archive."""
    target_dir = root / subdir
    if not target_dir.is_dir():
        return []

    files: list[Path] = []
    for pattern in patterns:
        for match in sorted(target_dir.rglob(pattern)):
            if match.name in EXCLUDE_NAMES:
                continue
            if not match.is_file():
                continue
            if not _is_older_than(match, max_age_days):
                continue
            files.append(match)

    if dry_run and files:
        _log.info("  Would collect %d files from %s/ matching %s", len(files), subdir, patterns)

    return files


def _create_archive(
    archive_path: Path,
    files: list[Path],
    root: Path,
    *,
    compress: bool = True,
    dry_run: bool = False,
) -> int:
    """Create a ZIP archive containing the given files. Returns count of archived files."""
    if dry_run:
        return len(files)

    if not files:
        return 0

    archive_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with ZipFile(str(archive_path), "w", compression=ZIP_DEFLATED if compress else 0) as zf:
        for file_path in files:
            try:
                # Store relative path within archive
                arcname = str(file_path.relative_to(root))
                zf.write(str(file_path), arcname)
                count += 1
            except (OSError, ValueError) as exc:
                _log.warning("  Failed to add %s to archive: %s", file_path, exc)

    if count > 0:
        actual_size = archive_path.stat().st_size
        _log.info("  Created archive: %s (%d files, %.1f MB)", archive_path.name, count, actual_size / (1024 * 1024))
    else:
        # Remove empty archive
        archive_path.unlink(missing_ok=True)

    return count


def _summarize(results: dict[str, int], output_dir: Path) -> None:
    """Print summary of archiving results."""
    total = sum(results.values())
    _log.info("")
    _log.info("=" * 50)
    _log.info("Archive Summary")
    _log.info("=" * 50)
    for category, count in sorted(results.items()):
        _log.info("  %-15s: %d files", category, count)
    _log.info("  %-15s: %d files", "TOTAL", total)
    if total > 0:
        _log.info("  Archive location: %s", output_dir)
    _log.info("=" * 50)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AD-KIYU Artifact Archiver — compress old runtime artifacts into dated ZIP files",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root directory (default: parent of script directory)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for archives (default: <root>/archives)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Archive files older than this many days (default: 14)",
    )
    parser.add_argument(
        "--skip-logs",
        action="store_true",
        help="Skip archiving logs/ directory",
    )
    parser.add_argument(
        "--skip-reports",
        action="store_true",
        help="Skip archiving reports/ directory",
    )
    parser.add_argument(
        "--skip-backups",
        action="store_true",
        help="Skip archiving backups/ directory",
    )
    parser.add_argument(
        "--skip-data",
        action="store_true",
        help="Skip archiving data/ directory",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="List what would be archived without creating archive files",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Store files without compression (faster, larger archives)",
    )

    args = parser.parse_args()

    # ── Logging setup ───────────────────────────────────────────────────
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(message)s", stream=sys.stdout)

    # ── Path resolution ─────────────────────────────────────────────────
    root = args.root.resolve() if args.root else Path(__file__).resolve().parent.parent
    output_dir = args.output_dir.resolve() if args.output_dir else root / ARCHIVE_DIR_NAME

    _log.info("AD-KIYU Artifact Archiver v1.0")
    _log.info("Root directory: %s", root)
    _log.info("Output directory: %s", output_dir)
    _log.info("Max age: %d days", args.days)
    _log.info("Mode: %s", "DRY RUN" if args.dry_run else "ARCHIVE")
    _log.info("Compression: %s", "disabled" if args.no_compress else "enabled (ZIP deflate)")
    _log.info("")

    # ── Collect files ──────────────────────────────────────────────────
    categories: list[tuple[str, str, bool]] = [
        ("logs", "logs", args.skip_logs),
        ("reports", "reports", args.skip_reports),
        ("backups", "backups", args.skip_backups),
        ("data", "data", args.skip_data),
    ]

    all_files: dict[str, list[Path]] = {}
    total_collected = 0

    for category_name, subdir, skip in categories:
        if skip:
            _log.info("Skipping %s/ (--skip-%s)", subdir, category_name)
            continue

        patterns = INCLUDE_PATTERNS.get(category_name, ["*"])
        _log.info("Scanning %s/ for files older than %d days...", subdir, args.days)

        files = _collect_archivable(
            root,
            category_name,
            subdir,
            patterns,
            args.days,
            dry_run=args.dry_run,
        )

        if files:
            all_files[category_name] = files
            total_collected += len(files)
            _log.info("  Found %d archivable files in %s/", len(files), subdir)
        else:
            _log.info("  Nothing to archive in %s/", subdir)

    # ── Summary ─────────────────────────────────────────────────────────
    _log.info("")
    _log.info("Total files to archive: %d", total_collected)

    if not total_collected:
        _log.info("Nothing to archive — system is tidy!")
        return 0

    if args.dry_run:
        _log.info("\nRun without --dry-run to create archives.")
        return 0

    # ── Create archives ─────────────────────────────────────────────────
    date_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results: dict[str, int] = {}

    for category, files in all_files.items():
        archive_name = f"{category}_{date_stamp}.zip"
        archive_path = output_dir / archive_name

        _log.info("\nCreating archive: %s", archive_name)
        count = _create_archive(archive_path, files, root, compress=not args.no_compress)
        if count > 0:
            results[category] = count
            _log.info("  Archived %d files from %s/", count, category)
        else:
            _log.info("  Nothing archived from %s/ (0 files)", category)

    # ── Final summary ───────────────────────────────────────────────────
    _summarize(results, output_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
