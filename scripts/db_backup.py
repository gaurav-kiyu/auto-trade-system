"""
Automated Database Backup Script (v2.53+).

Creates timestamped backups of all SQLite database files in the project root
and manages retention (default: keep 30 daily backups).

Supports:
  - Backup all .db files with ISO timestamp suffix
  - Retention-based cleanup (oldest backups removed)
  - Dry-run mode
  - Integration with CI / cron / scheduled tasks

Usage
-----
    python scripts/db_backup.py                     # Backup all .db files
    python scripts/db_backup.py --retention 14      # Keep 14 backups
    python scripts/db_backup.py --dry-run            # Show what would be done
    python scripts/db_backup.py --dir backups        # Custom backup directory

Config keys (index_config.defaults.json)
-----------------------------------------
    db_backup_enabled       : bool   default true
    db_backup_retention_days: int    default 30
    db_backup_dir           : str    default "backups"
    db_backup_exclude       : list   default []
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("db_backup")

# Default DB files to back up (auto-discovered as *.db in project root)
_DEFAULT_DB_PATTERNS = ["*.db"]

# Backup directory relative to project root
_DEFAULT_BACKUP_DIR = "backups"

# Default retention in days
_DEFAULT_RETENTION_DAYS = 30


def find_project_root() -> Path:
    """Find project root by traversing up from script location."""
    # Start from the directory containing this script
    current = Path(__file__).resolve().parent.parent
    # Look for markers that indicate project root
    markers = [".git", "index_config.defaults.json", "pyproject.toml"]
    for _ in range(10):  # Up to 10 levels up
        if any((current / m).exists() for m in markers):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return Path.cwd()


def discover_db_files(project_root: Path, exclude: list[str] | None = None) -> list[Path]:
    """Discover all .db files in the project root matching patterns."""
    exclude = exclude or []
    db_files: list[Path] = []
    for pattern in _DEFAULT_DB_PATTERNS:
        for fpath in project_root.glob(pattern):
            if fpath.is_file():
                # Skip files in excluded patterns
                skip = False
                for excl in exclude:
                    if excl in str(fpath):
                        skip = True
                        break
                if not skip:
                    db_files.append(fpath)
    return sorted(db_files)


def create_backup(
    db_path: Path,
    backup_dir: Path,
    timestamp: str | None = None,
) -> Path:
    """Create a timestamped copy of a database file.

    Args:
        db_path: Path to the source .db file.
        backup_dir: Directory to store the backup.
        timestamp: Optional ISO timestamp string (auto-generated if None).

    Returns:
        Path to the created backup file.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)

    if timestamp is None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")

    stem = db_path.stem  # e.g., "trades" from "trades.db"
    backup_name = f"{stem}_{timestamp}.db"
    backup_path = backup_dir / backup_name

    shutil.copy2(str(db_path), str(backup_path))
    return backup_path


def cleanup_old_backups(
    backup_dir: Path,
    retention_days: int = _DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
) -> list[Path]:
    """Remove backup files older than retention_days.

    Args:
        backup_dir: Directory containing backup files.
        retention_days: Maximum age (in days) for backup retention.
        dry_run: If True, only log what would be removed.

    Returns:
        List of removed backup files.
    """
    if not backup_dir.is_dir():
        return []

    cutoff = time.time() - (retention_days * 86400)
    removed: list[Path] = []

    for fpath in sorted(backup_dir.iterdir()):
        if fpath.is_file() and fpath.suffix == ".db":
            mtime = fpath.stat().st_mtime
            if mtime < cutoff:
                if dry_run:
                    _log.info("[DRY-RUN] Would remove: %s (age: %.1f days)",
                              fpath.name, (time.time() - mtime) / 86400)
                else:
                    fpath.unlink()
                    _log.info("Removed old backup: %s (age: %.1f days)",
                              fpath.name, (time.time() - mtime) / 86400)
                removed.append(fpath)

    return removed


def run_backup(
    project_root: Path | None = None,
    backup_dir_name: str = _DEFAULT_BACKUP_DIR,
    retention_days: int = _DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
    exclude: list[str] | None = None,
) -> dict[str, Any]:
    """Run the full backup cycle: discover → backup → cleanup.

    Args:
        project_root: Project root directory (auto-detected if None).
        backup_dir_name: Name of the backup subdirectory.
        retention_days: Number of days to retain backups.
        dry_run: If True, only simulate.
        exclude: List of file patterns to exclude from backup.

    Returns:
        Dict with backup results.
    """
    root = project_root or find_project_root()
    backup_dir = root / backup_dir_name

    results: dict[str, Any] = {
        "success": True,
        "project_root": str(root),
        "backup_dir": str(backup_dir),
        "db_files_found": [],
        "backups_created": [],
        "backups_removed": [],
        "errors": [],
    }

    # Discover database files
    db_files = discover_db_files(root, exclude=exclude)
    results["db_files_found"] = [str(f) for f in db_files]

    if not db_files:
        _log.info("No .db files found in %s", root)
        results["message"] = "No database files to back up."
        return results

    if dry_run:
        _log.info("[DRY-RUN] Would back up %d file(s):", len(db_files))
        for f in db_files:
            _log.info("  → %s", f.name)
    else:
        # Create backups
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        for db_path in db_files:
            try:
                backup_path = create_backup(db_path, backup_dir, timestamp)
                results["backups_created"].append(str(backup_path))
                _log.info("Backed up: %s → %s", db_path.name, backup_path.name)
            except (OSError, PermissionError, shutil.Error) as exc:
                _log.error("Failed to back up %s: %s", db_path.name, exc)
                results["errors"].append(str(exc))

    # Cleanup old backups
    removed = cleanup_old_backups(backup_dir, retention_days, dry_run=dry_run)
    results["backups_removed"] = [str(f) for f in removed]

    results["success"] = len(results["errors"]) == 0
    if not dry_run:
        _log.info("Backup complete: %d created, %d removed, %d error(s)",
                  len(results["backups_created"]),
                  len(results["backups_removed"]),
                  len(results["errors"]))

    return results


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        prog="python scripts/db_backup.py",
        description="Backup all SQLite database files with timestamped copies and retention cleanup.",
    )
    ap.add_argument("--retention", type=int, default=_DEFAULT_RETENTION_DAYS,
                    help=f"Days to retain backups (default: {_DEFAULT_RETENTION_DAYS})")
    ap.add_argument("--dir", default=_DEFAULT_BACKUP_DIR,
                    help=f"Backup directory name (default: {_DEFAULT_BACKUP_DIR!r})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Simulate without creating or removing files")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="Exclude DB files matching these patterns")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Enable verbose logging")

    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    results = run_backup(
        backup_dir_name=args.dir,
        retention_days=args.retention,
        dry_run=args.dry_run,
        exclude=args.exclude,
    )

    print(f"\nBackup Summary:")
    print(f"  Project root: {results['project_root']}")
    print(f"  Backup dir:   {results['backup_dir']}")
    print(f"  DB files:     {len(results['db_files_found'])} found")
    print(f"  Created:      {len(results['backups_created'])} backup(s)")
    print(f"  Removed:      {len(results['backups_removed'])} old backup(s)")
    print(f"  Errors:       {len(results['errors'])}")
    ok_str = "OK" if results['success'] else "ERRORS"
    print(f"  Status:       [{ok_str}]")

    sys.exit(0 if results['success'] else 1)


if __name__ == "__main__":
    main()
