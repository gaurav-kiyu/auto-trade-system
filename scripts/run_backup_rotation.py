#!/usr/bin/env python3
"""Automated Database Backup & Rotation — OPB v2.57.0

Creates timestamped backups of all SQLite databases and manages retention.

Features:
  - Backup all .db files with timestamps
  - Configurable retention (default: keep 7 daily, 4 weekly, 3 monthly)
  - Compress backups with gzip
  - Verify backup integrity after creation
  - Prune old backups according to retention policy
  - CI mode for nightly cron jobs

Usage:
    python scripts/run_backup_rotation.py
    python scripts/run_backup_rotation.py --retain-daily 14 --retain-weekly 8
    python scripts/run_backup_rotation.py --ci
    python scripts/run_backup_rotation.py --json
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
JSON_REPORT = REPORTS_DIR / "backup_report.json"
DEFAULT_RETAIN_DAILY = 7
DEFAULT_RETAIN_WEEKLY = 4
DEFAULT_RETAIN_MONTHLY = 3

TEST_DB_PATTERNS = ("test_", "temp_", "test_recon_")


def _find_databases() -> list[Path]:
    """Find all SQLite databases to back up."""
    root = Path.cwd()
    dbs = []
    for pattern in ("*.db",):
        for f in root.glob(pattern):
            if not any(f.name.startswith(p) for p in TEST_DB_PATTERNS):
                dbs.append(f)
        data_dir = root / "data"
        if data_dir.exists():
            for f in data_dir.glob(pattern):
                if not any(f.name.startswith(p) for p in TEST_DB_PATTERNS):
                    dbs.append(f)
    return sorted(set(dbs), key=lambda p: p.name)


def _verify_backup(backup_path: Path) -> bool:
    """Verify that a backup file is valid."""
    try:
        # For gzipped backups, decompress and check SQLite header
        if backup_path.suffix == ".gz":
            with gzip.open(backup_path, "rb") as f:
                header = f.read(16)
            if not header.startswith(b"SQLite format 3\x00"):
                return False
        else:
            with open(backup_path, "rb") as f:
                header = f.read(16)
            if not header.startswith(b"SQLite format 3\x00"):
                return False
        return True
    except OSError:
        return False


def _get_backup_age_days(backup_path: Path) -> int:
    """Get the age of a backup in days."""
    try:
        mtime = os.path.getmtime(backup_path)
        age = (time.time() - mtime) / 86400
        return int(age)
    except OSError:
        return 999


def _categorize_backup(backup_path: Path) -> str:
    """Categorize a backup as daily, weekly, or monthly based on age."""
    age_days = _get_backup_age_days(backup_path)
    if age_days <= 1:
        return "current"
    elif age_days <= 7:
        return "daily"
    elif age_days <= 30:
        return "weekly"
    else:
        return "monthly"


def run_backup(
    retain_daily: int = DEFAULT_RETAIN_DAILY,
    retain_weekly: int = DEFAULT_RETAIN_WEEKLY,
    retain_monthly: int = DEFAULT_RETAIN_MONTHLY,
    compress: bool = True,
) -> dict[str, Any]:
    """Run the full backup and rotation cycle.

    Args:
        retain_daily: Number of daily backups to keep (1-7 days old).
        retain_weekly: Number of weekly backups to keep (8-30 days old).
        retain_monthly: Number of monthly backups to keep (31+ days old).
        compress: Whether to gzip-compress backups.

    Returns:
        Dict with backup results.
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    databases = _find_databases()

    results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S IST"),
        "retention": {
            "daily": retain_daily,
            "weekly": retain_weekly,
            "monthly": retain_monthly,
        },
        "databases_found": len(databases),
        "backups_created": [],
        "backups_verified": [],
        "backups_pruned": [],
        "errors": [],
        "total_size_bytes": 0,
        "total_backup_size_bytes": 0,
    }

    # ── Phase 1: Create backups ──
    print(f"\n  Creating backups ({timestamp})...")
    for db_path in databases:
        db_name = db_path.name
        if compress:
            backup_name = f"{db_name}.{timestamp}.db.gz"
        else:
            backup_name = f"{db_name}.{timestamp}.db"
        backup_path = BACKUP_DIR / backup_name

        try:
            if compress:
                with open(db_path, "rb") as f_in:
                    with gzip.open(backup_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            else:
                shutil.copy2(db_path, backup_path)

            size = backup_path.stat().st_size
            results["backups_created"].append({
                "database": db_name,
                "backup": backup_name,
                "size_bytes": size,
            })
            results["total_backup_size_bytes"] += size
            print(f"    ✅ {db_name} → {backup_name} ({size / 1024:.1f} KB)")
        except (OSError, PermissionError) as e:
            results["errors"].append(f"Failed to backup {db_name}: {e}")
            print(f"    ❌ {db_name}: {e}")

    # ── Phase 2: Verify backups ──
    print("\n  Verifying backups...")
    for b in results["backups_created"]:
        backup_path = BACKUP_DIR / b["backup"]
        valid = _verify_backup(backup_path)
        results["backups_verified"].append({
            "backup": b["backup"],
            "valid": valid,
        })
        print(f"    {'✅' if valid else '❌'} {b['backup']}")

    # ── Phase 3: Prune old backups ──
    print(f"\n  Pruning old backups (retention: {retain_daily}d/{retain_weekly}w/{retain_monthly}m)...")

    # Group backups by database
    # Backup filename format: {db_name}.YYYYMMDD_HHMMSS.db[.gz]
    # Use regex to extract original db name reliably even with dots in names
    import re as _re
    _backup_pattern = _re.compile(r'^(.+)\.\d{8}_\d{6}\.db(\.gz)?$')
    backups_by_db: dict[str, list[Path]] = {}
    for f in sorted(BACKUP_DIR.glob("*.db*")):
        match = _backup_pattern.match(f.name)
        if match:
            db_key = match.group(1) + ".db"
        else:
            # Fallback: use filename as-is
            db_key = f.name.rsplit(".", 1)[0] if f.suffix == ".gz" else f.stem
        backups_by_db.setdefault(db_key, []).append(f)

    for db_name, backups in backups_by_db.items():
        # Sort by mtime (oldest first)
        backups.sort(key=lambda p: os.path.getmtime(p))

        daily_count = 0
        weekly_count = 0
        monthly_count = 0

        for backup in backups:
            category = _categorize_backup(backup)

            if category == "current":
                continue  # Always keep the most recent
            elif category == "daily":
                daily_count += 1
                if daily_count > retain_daily:
                    backup.unlink()
                    results["backups_pruned"].append(str(backup.name))
                    print(f"    🗑️  Pruned daily: {backup.name}")
            elif category == "weekly":
                weekly_count += 1
                if weekly_count > retain_weekly:
                    backup.unlink()
                    results["backups_pruned"].append(str(backup.name))
                    print(f"    🗑️  Pruned weekly: {backup.name}")
            elif category == "monthly":
                monthly_count += 1
                if monthly_count > retain_monthly:
                    backup.unlink()
                    results["backups_pruned"].append(str(backup.name))
                    print(f"    🗑️  Pruned monthly: {backup.name}")

    results["total_pruned"] = len(results["backups_pruned"])

    # ── Summary stats ──
    all_backups = list(BACKUP_DIR.glob("*.db*"))
    results["total_backups_remaining"] = len(all_backups)
    results["total_backup_disk_bytes"] = sum(f.stat().st_size for f in all_backups)

    return results


def main() -> int:
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Database Backup & Rotation")
    parser.add_argument("--retain-daily", type=int, default=DEFAULT_RETAIN_DAILY,
                        help=f"Daily backups to keep (default: {DEFAULT_RETAIN_DAILY})")
    parser.add_argument("--retain-weekly", type=int, default=DEFAULT_RETAIN_WEEKLY,
                        help=f"Weekly backups to keep (default: {DEFAULT_RETAIN_WEEKLY})")
    parser.add_argument("--retain-monthly", type=int, default=DEFAULT_RETAIN_MONTHLY,
                        help=f"Monthly backups to keep (default: {DEFAULT_RETAIN_MONTHLY})")
    parser.add_argument("--no-compress", action="store_true", help="Skip gzip compression")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--ci", action="store_true", help="CI mode: exit non-zero on errors")
    args = parser.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    print("=" * 60)
    print("  DATABASE BACKUP & ROTATION v2.57.0")
    print("=" * 60)
    print(f"\n  Backup directory: {BACKUP_DIR}")
    print(f"  Retention: {args.retain_daily}d / {args.retain_weekly}w / {args.retain_monthly}m")

    results = run_backup(
        retain_daily=args.retain_daily,
        retain_weekly=args.retain_weekly,
        retain_monthly=args.retain_monthly,
        compress=not args.no_compress,
    )

    # Summary
    print("\n  ── Summary ──")
    print(f"  Databases found:     {results['databases_found']}")
    print(f"  Backups created:     {len(results['backups_created'])}")
    print(f"  Backups pruned:      {results['total_pruned']}")
    print(f"  Backups remaining:   {results['total_backups_remaining']}")
    print(f"  Errors:              {len(results['errors'])}")

    if results["errors"]:
        for err in results["errors"]:
            print(f"    ❌ {err}")

    if args.json:
        print(json.dumps(results, indent=2, default=str))

    JSON_REPORT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\n  JSON report: {JSON_REPORT}")

    if args.ci and results["errors"]:
        print(f"\n❌ CI FAILED: {len(results['errors'])} error(s)")
        return 1

    print("\n" + "=" * 60)
    print("  BACKUP ROTATION COMPLETE")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
